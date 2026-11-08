import hashlib
import json
import secrets
from types import SimpleNamespace

import pytest
from flask.testing import FlaskClient

from services.auth_service import AuthService
from tests.test_api import client
from tests.test_api_v2 import api_client
from tests.test_dispatcher import terminal


def registry(tmp_path, **changes):
    secret = secrets.token_urlsafe(32)
    token = dict(id="test-v1", principal="machine-one", enabled=True,
                 secret_sha256=hashlib.sha256(secret.encode()).hexdigest(),
                 scopes=["catalog:read", "playback:write", "status:read"])
    token.update(changes)
    path = tmp_path / "registry.json"
    path.write_text(json.dumps({"version": 1, "tokens": [token]}))
    path.chmod(0o600)
    return path, "test-v1." + secret


@pytest.fixture
def remote(api_client, tmp_path):
    _, app, calls = api_client
    path, token = registry(tmp_path)
    auth = app.extensions["auth_service"]
    auth.tokens = AuthService.load_registry(path)
    auth.remote_enabled = True
    return FlaskClient(app), app, calls, {"Authorization": "Bearer " + token}


@pytest.mark.parametrize("secret,cidrs,hosts", [("dev-change-in-production", ["127.0.0.1/32"], ["localhost"]),
    ("x" * 32, [], ["localhost"]), ("x" * 32, ["127.0.0.1/32"], []),
    ("x" * 32, ["0.0.0.0/0"], ["localhost"]), ("x" * 32, ["127.0.0.1/32"], ["*.example"]),
    ("REPLACE_WITH_RANDOM_SESSION_SECRET", ["127.0.0.1/32"], ["localhost"])])
def test_startup_fails_closed(secret, cidrs, hosts):
    with pytest.raises(ValueError):
        AuthService(SimpleNamespace(FLASK_SECRET_KEY=secret, TRUSTED_LAN_CIDRS=cidrs, ALLOWED_HOSTS=hosts))


@pytest.mark.parametrize("changes", [dict(enabled=1), dict(secret_sha256="placeholder"),
    dict(scopes=["all"]), dict(scopes=["catalog:read", "catalog:read"]),
    dict(principal="lan-household"), dict(id="unsafe\nname"), dict(unexpected=True)])
def test_invalid_registry_rejected(tmp_path, changes):
    path, _ = registry(tmp_path, **changes)
    with pytest.raises(ValueError, match="Invalid or inaccessible"):
        AuthService.load_registry(path)


def test_duplicate_registry_and_missing_file_rejected(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text('{"version":1,"version":1,"tokens":[]}')
    path.chmod(0o600)
    with pytest.raises(ValueError):
        AuthService.load_registry(path)
    with pytest.raises(ValueError):
        AuthService.load_registry(tmp_path / "absent")


@pytest.mark.parametrize("authorization", [None, "Bearer invalid", "Basic secret", "Bearer unknown." + "A" * 43])
def test_remote_uniform_401_and_forwarded_identity_is_not_auth(remote, authorization):
    http, app, calls, _ = remote
    headers = {"CF-Connecting-IP": "127.0.0.1", "X-Forwarded-For": "127.0.0.1",
               "CF-Access-Jwt-Assertion": "fake", "X-Forwarded-Host": "localhost"}
    if authorization:
        headers["Authorization"] = authorization
    response = http.get("/remote/api/movies", headers=headers)
    assert response.status_code == 401
    assert response.json["error"]["code"] == "authentication_required"
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["Cache-Control"] == "no-store"
    assert calls == []


def test_disabled_token_missing_scope_and_constant_time(remote, monkeypatch):
    http, app, calls, headers = remote
    import services.auth_service as module
    compared = []
    original = module.hmac.compare_digest
    monkeypatch.setattr(module.hmac, "compare_digest", lambda a, b: compared.append((len(a), len(b))) or original(a, b))
    token = app.extensions["auth_service"].tokens["test-v1"]
    token["enabled"] = False
    assert http.get("/remote/api/movies", headers=headers).status_code == 401
    token["enabled"] = True
    token["scopes"] = []
    assert http.get("/remote/api/movies", headers=headers).status_code == 403
    assert (64, 64) in compared
    assert calls == []


def test_principal_jobs_replays_and_cookies_are_isolated(remote):
    http, app, calls, headers = remote
    headers = {**headers, "Idempotency-Key": "request-one"}
    first = http.post("/remote/api/play", json={"movie_key": "luca"}, headers=headers)
    assert first.status_code == 202
    assert "Set-Cookie" not in first.headers
    terminal(app.extensions["playback_service"], first.json["request_id"], "machine-one")
    path = "/remote" + first.json["status_url"]
    own = http.get(path, headers=headers)
    assert own.json["request"]["command_state"] == "command_sent"
    assert own.json["playback"]["state"] == "unknown" and "device" not in own.json
    assert http.post("/remote/api/play", json={"movie_key": "luca"}, headers=headers).json == first.json
    token = app.extensions["auth_service"].tokens["test-v1"]
    token["principal"] = "machine-two"
    assert http.get(path, headers=headers).status_code == 404
    assert http.get("/remote/api/status", headers=headers).json["request"] is None
    assert calls == ["luca-id"]


@pytest.mark.parametrize("peer,host,expected", [("127.0.0.1", "localhost", 200),
    ("::1", "[::1]", 200), ("192.0.2.8", "localhost", 403),
    ("2001:db8::1", "localhost", 403), ("127.0.0.1", "evil.example", 403),
    ("127.0.0.1", "localhost:1234", 403)])
def test_direct_lan_and_host_checks(api_client, peer, host, expected):
    _, app, calls = api_client
    http = FlaskClient(app)
    response = http.get("/", headers={"Host": host, "X-Forwarded-For": "127.0.0.1"},
                        environ_overrides={"REMOTE_ADDR": peer})
    assert response.status_code == expected
    assert ("Set-Cookie" in response.headers) == (expected == 200)
    assert calls == []


def test_session_csrf_origin_expiry_and_legacy(api_client):
    _, app, calls = api_client
    http = FlaskClient(app)
    assert http.get("/api/movies").status_code == 401
    page = http.get("/")
    cookie = page.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Secure" not in cookie
    assert page.headers["Cache-Control"] == "private, no-store"
    with http.session_transaction() as session:
        csrf = session["csrf"]
    payload = dict(json={"movie_key": "luca"})
    assert http.post("/api/play", **payload).status_code == 403
    for extra in ({"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}, {"Origin": "null"}):
        assert http.post("/api/play", headers={"X-CSRF-Token": csrf, **extra}, **payload).status_code == 403
    assert http.post("/api/play", data="{}", content_type="text/plain", headers={"X-CSRF-Token": csrf}).status_code == 415
    assert calls == []
    # Old cached clients need no session or new headers, including valid unknown IDs.
    old = FlaskClient(app)
    assert old.get("/play/not-in-catalog").status_code == 200
    assert old.get("/play/not-in-catalog", headers={"Origin": "https://evil.example"}).status_code == 403
    # Create an actually expired signature; no wall-clock sleep or session forgery.
    import itsdangerous.timed
    from unittest.mock import patch
    with patch.object(itsdangerous.timed.time, "time", return_value=1):
        expired = app.session_interface.get_signing_serializer(app).dumps({"principal": "lan-household", "csrf": csrf, "_permanent": True})
    http.set_cookie("session", expired)
    assert http.get("/api/movies").status_code == 401
    assert http.get("/").status_code == 200


def test_auth_failure_limiter_ignores_spoofed_peer(remote):
    http, app, calls, _ = remote
    for index in range(30):
        assert http.get("/remote/api/movies", headers={"X-Forwarded-For": f"192.0.2.{index}"}).status_code == 401
    response = http.get("/remote/api/movies")
    assert response.status_code == 429 and int(response.headers["Retry-After"]) > 0
    assert calls == []
