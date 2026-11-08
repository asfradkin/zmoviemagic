"""Local network/session trust and independent opaque machine credentials."""
import base64
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import stat
from urllib.parse import urlsplit

from flask import request, session

from services.playback_service import APIError


NAME = re.compile(r"[a-zA-Z0-9_-]{1,64}", re.ASCII)
SCOPES = {"catalog:read", "playback:write", "status:read", "resolve:read",
          "control:write", "preferences:read", "preferences:write", "health:read"}


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repeated registry field")
        result[key] = value
    return result


class AuthService:
    def __init__(self, config):
        self.remote_enabled = getattr(config, "REMOTE_API_ENABLED", False)
        secret = config.FLASK_SECRET_KEY
        if (not isinstance(secret, str) or len(secret) < 32
                or secret.startswith("REPLACE_")
                or secret in {"dev-change-in-production", "random-secret-for-sessions"}):
            raise ValueError("FLASK_SECRET_KEY must be a stable random secret of at least 32 characters")
        if self.remote_enabled and os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes"):
            raise ValueError("Debug mode must be off when remote access is enabled")
        cidrs = getattr(config, "TRUSTED_LAN_CIDRS", ())
        hosts = getattr(config, "ALLOWED_HOSTS", ())
        if not cidrs or not hosts:
            raise ValueError("Explicit TRUSTED_LAN_CIDRS and ALLOWED_HOSTS are required")
        self.networks = tuple(ipaddress.ip_network(value, strict=True) for value in cidrs)
        if any(network.prefixlen == 0 for network in self.networks):
            raise ValueError("Trust must not include all addresses")
        self.hosts = frozenset(self.host(value) for value in hosts)
        if None in self.hosts:
            raise ValueError("ALLOWED_HOSTS must contain exact host authorities, including port when used")
        self.tokens = {}
        if self.remote_enabled or getattr(config, "API_TOKEN_FILE", ""):
            self.tokens = self.load_registry(getattr(config, "API_TOKEN_FILE", ""))

    @staticmethod
    def host(value):
        try:
            if not isinstance(value, str) or any(char in value for char in "/\\?#@ \t\r\n"):
                return None
            parsed = urlsplit("http://" + value)
            if not parsed.hostname or parsed.port == 0 or value.endswith(":"):
                return None
            name = parsed.hostname.lower()
            if ":" in name:
                name = "[" + str(ipaddress.IPv6Address(name)) + "]"
            elif not re.fullmatch(r"[a-z0-9.-]+", name):
                return None
            return name + (":" + str(parsed.port) if parsed.port is not None else "")
        except ValueError:
            return None

    @staticmethod
    def load_registry(filename):
        try:
            path = Path(filename)
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > 262144:
                raise ValueError()
            if os.name != "nt" and info.st_mode & 0o077:
                raise ValueError()
            data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=strict_object)
            if (set(data) != {"version", "tokens"} or type(data["version"]) is not int
                    or data["version"] != 1 or not isinstance(data["tokens"], list)
                    or not 1 <= len(data["tokens"]) <= 128):
                raise ValueError()
            tokens = {}
            for token in data["tokens"]:
                if not isinstance(token, dict) or set(token) != {"id", "secret_sha256", "principal", "scopes", "enabled"}:
                    raise ValueError()
                if (not isinstance(token["id"], str) or not NAME.fullmatch(token["id"])
                        or token["id"] in tokens or not isinstance(token["principal"], str)
                        or not NAME.fullmatch(token["principal"]) or token["principal"] == "lan-household"
                        or not isinstance(token["secret_sha256"], str)
                        or not re.fullmatch(r"[a-f0-9]{64}", token["secret_sha256"])
                        or type(token["enabled"]) is not bool or not isinstance(token["scopes"], list)
                        or any(not isinstance(scope, str) or scope not in SCOPES for scope in token["scopes"])
                        or len(set(token["scopes"])) != len(token["scopes"])):
                    raise ValueError()
                tokens[token["id"]] = token
            return tokens
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            raise ValueError("Invalid or inaccessible API token registry; check schema and protected permissions") from None

    def check_host(self):
        if self.host(request.host) not in self.hosts:
            raise APIError("forbidden", 403, "Host is not allowed.")

    def trusted_lan(self):
        try:
            peer = ipaddress.ip_address(request.remote_addr)
            return any(peer in network for network in self.networks)
        except (ValueError, TypeError):
            return False

    def require_lan(self):
        if not self.trusted_lan():
            raise APIError("forbidden", 403, "A trusted local connection is required.")

    @staticmethod
    def check_origin():
        if request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            raise APIError("forbidden", 403, "Cross-site requests are not allowed.")
        origin = request.headers.get("Origin")
        if origin is not None and origin != request.host_url.rstrip("/"):
            raise APIError("forbidden", 403, "Origin does not match this application.")

    def bearer(self, scope, limiter):
        header = request.headers.get("Authorization", "")
        match = re.fullmatch(r"Bearer ([a-zA-Z0-9_-]{1,64})\.([a-zA-Z0-9_-]{43})", header, re.ASCII)
        token = self.tokens.get(match[1]) if match else None
        secret = match[2] if match else ""
        digest = hashlib.sha256(secret.encode("ascii")).hexdigest()
        expected = token["secret_sha256"] if token else "0" * 64
        valid = hmac.compare_digest(digest, expected)
        # Canonical base64url encoding of exactly 256 random bits.
        canonical = False
        if match:
            raw = base64.urlsafe_b64decode(secret + "=")
            canonical = len(raw) == 32 and base64.urlsafe_b64encode(raw).decode().rstrip("=") == secret
        if not (valid and canonical and token and token["enabled"]):
            limiter.consume("failure", request.remote_addr or "unknown")
            raise APIError("authentication_required", 401, "Authentication required.")
        if scope not in token["scopes"]:
            raise APIError("forbidden", 403, "Credential lacks the required scope.")
        return token["principal"]

    def browser(self, command=False):
        self.require_lan()
        self.check_origin()
        if session.get("principal") != "lan-household" or not session.get("csrf"):
            raise APIError("authentication_required", 401, "Authentication required.")
        if command:
            csrf = request.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(csrf.encode(), session["csrf"].encode()):
                raise APIError("forbidden", 403, "Refresh this page before sending a request.")
        return "lan-household"

    def grant_session(self):
        self.require_lan()
        self.check_origin()
        if session.get("principal") != "lan-household" or not session.get("csrf"):
            session.clear()
            session["principal"] = "lan-household"
            session["csrf"] = secrets.token_urlsafe(32)
            session.permanent = True
        return session["csrf"]
