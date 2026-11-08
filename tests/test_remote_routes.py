import re
from pathlib import Path

import pytest

from tests.test_api import client
from tests.test_api_v2 import api_client
from tests.test_auth import remote
from tests.test_dispatcher import terminal


@pytest.mark.parametrize("path,method,scope", [("movies", "GET", "catalog:read"),
    ("play", "POST", "playback:write"), ("status", "GET", "status:read")])
def test_remote_route_method_scope_matrix(remote, path, method, scope):
    http, app, calls, headers = remote
    token = app.extensions["auth_service"].tokens["test-v1"]
    token["scopes"] = [scope]
    for candidate in ("GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"):
        response = http.open("/remote/api/" + path, method=candidate, headers=headers)
        if candidate != method:
            assert response.status_code == 405
        else:
            assert response.status_code == (415 if method == "POST" else 200)
    token["scopes"] = []
    assert http.open("/remote/api/" + path, method=method, headers=headers).status_code == 403
    assert calls == []


@pytest.mark.parametrize("path", ["/remote/", "/remote/health", "/remote/play/luca-id",
    "/remote/static/tablet.js", "/remote/api/control", "/remote/api/resolve", "/remote/api/admin"])
def test_remote_unknown_paths_denied(remote, path):
    http, app, calls, headers = remote
    response = http.get(path, headers=headers)
    assert response.status_code == 404 and response.is_json
    assert calls == []


def test_remote_disabled_is_404_and_browser_cookie_never_authenticates(remote):
    http, app, calls, headers = remote
    http.get("/")
    assert http.get("/remote/api/movies").status_code == 401
    app.extensions["auth_service"].remote_enabled = False
    assert http.get("/remote/api/movies", headers=headers).status_code == 404
    assert http.get("/api/movies").status_code == 200


@pytest.mark.parametrize("path,method,body,expected", [
    ("/remote/api/play", "POST", " " * 4097, 413),
    ("/remote/api/play?extra=1", "POST", "{}", 400),
    ("/remote/api/movies?extra=1", "GET", "", 400),
    ("/remote/api/movies", "GET", "{}", 400),
    ("/remote/api/status?request_id=a&request_id=b", "GET", "", 400),
    ("/remote/api/play", "POST", '{"movie_key":"luca","movie_key":"moana"}', 400),
])
def test_remote_validation_before_effects(remote, path, method, body, expected):
    http, app, calls, headers = remote
    response = http.open(path, method=method, data=body, headers=headers, content_type="application/json")
    assert response.status_code == expected and response.is_json
    assert calls == []


def test_local_bearer_uses_same_principal_and_remote_never_trusts_ip(remote):
    http, app, calls, headers = remote
    assert http.get("/api/movies", headers=headers, environ_overrides={"REMOTE_ADDR": "192.0.2.9"}).status_code == 200
    assert http.get("/api/movies", environ_overrides={"REMOTE_ADDR": "192.0.2.9"}).status_code == 403
    assert http.get("/remote/api/movies").status_code == 401


def test_replay_general_quota_and_command_quota(remote):
    http, app, calls, headers = remote
    now = [0]
    limiter = app.extensions["rate_limit_service"]
    limiter.clock = lambda: now[0]
    body = {"movie_key": "luca"}
    first_headers = {**headers, "Idempotency-Key": "request-one"}
    first = http.post("/remote/api/play", json=body, headers=first_headers)
    assert first.status_code == 202
    terminal(app.extensions["playback_service"], first.json["request_id"], "machine-one")
    for _ in range(9):
        assert http.post("/remote/api/play", json=body, headers=first_headers).json == first.json
    assert len(limiter._buckets[("command", "machine-one")][0]) == 1
    response = http.post("/remote/api/play", json=body, headers=first_headers)
    assert response.status_code == 429 and response.headers["Retry-After"] == "1"
    now[0] = 1
    second = http.post("/remote/api/play", json=body, headers={**headers, "Idempotency-Key": "request-two"})
    assert second.status_code == 202
    terminal(app.extensions["playback_service"], second.json["request_id"], "machine-one")
    third = http.post("/remote/api/play", json=body, headers={**headers, "Idempotency-Key": "request-three"})
    assert third.status_code == 429
    assert calls == ["luca-id", "luca-id"]


def test_proxy_aggregate_is_independent_of_valid_principals(remote):
    http, app, calls, headers = remote
    limiter = app.extensions["rate_limit_service"]
    limiter.clock = lambda: 0
    for _ in range(300):
        limiter.consume("proxy", "origin")
    assert http.get("/remote/api/movies", headers=headers).status_code == 429
    assert http.get("/").status_code == 200


def test_remote_errors_do_not_leak_credentials_or_diagnostics(remote, monkeypatch, caplog):
    http, app, calls, headers = remote
    canary = "TEST_CANARY_NEVER_LOG_THIS"
    def fail(*args):
        raise RuntimeError(canary)
    monkeypatch.setattr(app.extensions["movie_service"], "public_catalog", fail)
    response = http.get("/remote/api/movies", headers={**headers, "CF-Access-Client-Secret": canary})
    assert response.status_code == 500 and response.json["error"]["code"] == "internal_error"
    assert canary not in response.text + caplog.text
    assert headers["Authorization"] not in response.text + caplog.text


def proxy_allowed(uri):
    """Evaluate the actual raw-URI map regexes, not an independently copied policy."""
    config = (Path(__file__).resolve().parents[1] / "ops/nginx/zmoviemagic-remote.conf.example").read_text()
    for pattern in re.findall(r'^\s*"?~([^\n]+?)"?\s+1;', config, re.M):
        if re.fullmatch(pattern, uri):
            return True
    return False


@pytest.mark.parametrize("uri", ["/", "/play/luca", "/health", "/static/tablet.js", "/remote/api/play",
    "/api/control", "/api/resolve", "/api%2fplay", "/api%252fplay", "/api//play", "/api/./play",
    "/x/../api/play", "/api/play?", "/api/play?x=1", "/api/status?request_id=a&x=b",
    "/api/status?request_id=a&request_id=b", "/api/status?request_id=%61", "/api/status?request_id=",
    "/api/status?request_id=" + "a" * 129])
def test_proxy_raw_uri_map_rejects_normalization_and_publication_bypasses(uri):
    assert not proxy_allowed(uri)


@pytest.mark.parametrize("uri", ["/api/movies", "/api/play", "/api/status", "/api/status?request_id=uuid-123"])
def test_proxy_raw_uri_map_allows_only_phase4(uri):
    assert proxy_allowed(uri)


def test_proxy_template_transport_and_header_invariants():
    config = (Path(__file__).resolve().parents[1] / "ops/nginx/zmoviemagic-remote.conf.example").read_text()
    assert "listen 127.0.0.1:8081" in config
    assert "proxy_pass_request_headers off;" in config
    assert "proxy_next_upstream off;" in config
    assert config.count("proxy_pass http://127.0.0.1:8000/remote/api/") == 3
    assert "location / { return 404; }" in config
