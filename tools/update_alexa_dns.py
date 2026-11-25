"""Keep only movies-api.fradkin.net's existing A record current; dry run by default."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


RECORDS_URL = "https://api.godaddy.com/v3/domains/zones/fradkin.net/dns-records"
LOOKUP_URL = RECORDS_URL + "?type=A&name=movies-api&pageSize=2&totalRequired=true"
PUBLIC_IP_URL = "https://api.ipify.org?format=json"
TOKEN_FILE = Path.home() / ".config/moviemagic-dns/token"
MAX_RESPONSE = 131072


class DNSUpdateError(RuntimeError):
    """An operator-safe message: never include credentials or response bodies."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DNSUpdateError("HTTP redirect refused; no DNS retry was sent")


def read_token(path):
    with path.open("rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise DNSUpdateError("Token must be a regular file")
        if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise DNSUpdateError("Token must belong to this user and have mode 600")
        raw = handle.read(4097)
    token = raw.strip()
    if not token or len(raw) > 4096 or any(c < 33 or c > 126 for c in token):
        raise DNSUpdateError("Token file must contain one token only")
    return token.decode("ascii")


def http_json(url, token=None, payload=None):
    headers = {"Accept": "application/json", "User-Agent": "MovieMagic-DNS/1"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, headers=headers,
                      method="PUT" if body is not None else "GET")
    # No proxy environment or redirect can forward the GoDaddy token elsewhere.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=5) as response:
            raw = response.read(MAX_RESPONSE + 1)
    except HTTPError as error:
        code = error.code
        error.close()
        raise DNSUpdateError(f"HTTP {code}; check token permissions, expiry or API availability") from None
    except (URLError, OSError, TimeoutError):
        raise DNSUpdateError("Network request failed; no immediate retry was sent") from None
    if len(raw) > MAX_RESPONSE:
        raise DNSUpdateError("Oversized response refused")
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise DNSUpdateError("Invalid JSON response refused") from None
    if not isinstance(result, dict):
        raise DNSUpdateError("Unexpected response shape refused")
    return result


def public_ipv4(value):
    if not isinstance(value, str):
        raise DNSUpdateError("Invalid public IPv4 address; no DNS change")
    try:
        address = ipaddress.IPv4Address(value)
    except (ValueError, TypeError):
        raise DNSUpdateError("Invalid public IPv4 address; no DNS change") from None
    if not address.is_global or address.is_multicast:
        raise DNSUpdateError("Non-public IPv4 address; no DNS change")
    return str(address)


def sync_dns(token, apply=False):
    listing = http_json(LOOKUP_URL, token)
    records = listing.get("items")
    if (not isinstance(records, list) or len(records) != 1
            or listing.get("totalItems") != 1 or listing.get("totalPages", 1) != 1):
        raise DNSUpdateError("Expected exactly one existing movies-api A record; no DNS change")
    record = records[0]
    if not isinstance(record, dict) or record.get("name") != "movies-api" or record.get("type") != "A":
        raise DNSUpdateError("Unexpected record name or type; no DNS change")
    record_id, ttl = record.get("recordId"), record.get("ttl")
    if (not isinstance(record_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,512}", record_id)
            or type(ttl) is not int or not 600 <= ttl <= 86400):
        raise DNSUpdateError("Invalid record ID or TTL; no DNS change")
    current = public_ipv4(record.get("data"))
    wanted = public_ipv4(http_json(PUBLIC_IP_URL).get("ip"))
    if current == wanted:
        return f"DNS already current for movies-api.fradkin.net ({wanted})"
    if not apply:
        return f"CHECK ONLY: movies-api.fradkin.net would change {current} -> {wanted}; TTL {ttl} preserved"
    payload = {"name": "movies-api", "type": "A", "data": wanted, "ttl": ttl}
    result = http_json(RECORDS_URL + "/" + record_id, token, payload)
    if any(result.get(key) != value for key, value in payload.items()):
        raise DNSUpdateError("Update response unconfirmed; check DNS before any manual retry")
    return f"Updated movies-api.fradkin.net: {current} -> {wanted}; DNS caches may still hold the old IP"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", type=Path, default=TOKEN_FILE)
    parser.add_argument("--apply", action="store_true", help="Allow updating the existing A record")
    args = parser.parse_args(argv)
    try:
        print(sync_dns(read_token(args.token_file), apply=args.apply))
    except DNSUpdateError as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError:
        print("Cannot read token file; check its location and permissions", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
