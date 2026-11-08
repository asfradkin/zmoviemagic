from statistics import quantiles
from threading import Event
from time import perf_counter

import pytest

from services.firetv_service import DeliveryError
from tests.test_api import client
from tests.test_dispatcher import terminal


@pytest.fixture
def api_client(client, monkeypatch):
    http, app = client
    movies = app.extensions["movie_service"]
    for movie in movies._movies:
        movie["key"] = movie["title"].lower()
        movie["aliases"] = []
    movies._validate()
    calls = []
    def launch(provider_id, budget_seconds):
        calls.append(provider_id)
        return {"connection": "connected"}
    monkeypatch.setattr(app.extensions["firetv_service"], "launch_movie_bounded", launch)
    yield http, app, calls
    app.extensions["playback_service"].shutdown()


def post(http, key="luca", idem="request-001", **kwargs):
    return http.post("/api/play", json={"movie_key": key}, headers={"Idempotency-Key": idem}, **kwargs)


def test_catalog_and_status_never_probe_dependencies(api_client, monkeypatch):
    http, app, calls = api_client
    def fail(*a, **k):
        pytest.fail("Read endpoint contacted dependency")
    monkeypatch.setattr(app.extensions["firetv_service"], "get_device", fail)
    monkeypatch.setattr(app.extensions["movie_service"], "fetch_poster_for_title", fail)
    response = http.get("/api/movies")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert "luca-id" not in response.get_data(as_text=True)
    assert response.json["schema_version"] == 2
    assert http.get("/api/status").json["request"] is None
    assert calls == []


def test_acceptance_location_and_terminal_repeat(api_client):
    http, app, calls = api_client
    response = post(http)
    assert response.status_code == 202
    assert response.json["command_state"] == "queued"
    assert response.headers["Location"] == response.json["status_url"]
    assert response.headers["Cache-Control"] == "no-store"
    terminal(app.extensions["playback_service"], response.json["request_id"])
    status = http.get(response.json["status_url"])
    assert status.json["request"]["command_state"] == "command_sent"
    assert status.json["playback"]["state"] == "unknown"
    assert post(http).json == response.json
    assert calls == ["luca-id"]
    conflict = post(http, "moana")
    assert conflict.status_code == 409
    assert conflict.json["error"]["code"] == "idempotency_conflict"


@pytest.mark.parametrize("body,expected", [({}, "invalid_request"), ([], "invalid_request"),
    ({"movie_key": "luca", "id": "private"}, "invalid_request"),
    ({"movie_key": 1}, "invalid_movie_key"), ({"movie_key": "Luca"}, "invalid_movie_key"),
    ({"movie_key": "a" * 81}, "invalid_movie_key"), ({"movie_key": None}, "invalid_movie_key")])
def test_strict_json_object_and_key_validation(api_client, body, expected):
    http, app, calls = api_client
    response = http.post("/api/play", json=body, headers={"Idempotency-Key": "request-001"})
    assert response.status_code == 400
    assert response.json["error"]["code"] == expected
    assert not calls
    assert not app.extensions["playback_service"]._idempotency


@pytest.mark.parametrize("body", [b"{", b"null", b"\xff", b'{"movie_key":"luca","movie_key":"moana"}',
                                  b'{"movie_key":NaN}'])
def test_malformed_json_is_json_error(api_client, body):
    http, app, calls = api_client
    response = http.post("/api/play", data=body, content_type="application/json")
    assert response.status_code == 400
    assert response.is_json
    assert not calls


@pytest.mark.parametrize("key", [None, "short", "x" * 129, "nonascii-é", "newline\tkey"])
def test_idempotency_header_validation(api_client, key):
    http, app, calls = api_client
    headers = {} if key is None else {"Idempotency-Key": key}
    response = http.post("/api/play", json={"movie_key": "luca"}, headers=headers)
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_idempotency_key"
    assert not calls


def test_media_type_size_and_methods(api_client):
    http, app, calls = api_client
    assert http.post("/api/play", data='{}', content_type="text/plain").status_code == 415
    response = http.post("/api/play", data=" " * 4097, content_type="application/json")
    assert response.status_code == 413
    assert response.json["error"]["code"] == "request_too_large"
    for path, method in [("/api/play", "get"), ("/api/movies", "post"), ("/api/status", "post")]:
        response = getattr(http, method)(path)
        assert response.status_code == 405
        assert response.is_json
        assert response.headers["Cache-Control"] == "no-store"
    assert not calls


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.example"}, {"Origin": "null"},
    {"Origin": "http://localhost.evil"}, {"Sec-Fetch-Site": "cross-site"},
    {"Origin": "http://localhost", "Sec-Fetch-Site": "cross-site"}])
def test_cross_site_api_requests_denied(api_client, headers):
    http, app, calls = api_client
    headers = {"Idempotency-Key": "request-001", **headers}
    response = http.post("/api/play", json={"movie_key": "luca"}, headers=headers)
    assert response.status_code == 403
    assert response.is_json
    assert "Access-Control-Allow-Origin" not in response.headers
    assert not calls


def test_same_origin_is_accepted_and_forwarded_headers_do_not_grant_access(api_client):
    http, app, calls = api_client
    response = http.post("/api/play", json={"movie_key": "luca"},
                         headers={"Origin": "http://localhost:80", "Idempotency-Key": "request-001"})
    assert response.status_code == 202
    response = http.get("/api/status", headers={"Origin": "https://evil.example", "X-Forwarded-Host": "evil.example"})
    assert response.status_code == 403


def test_catalog_failures_unavailable_movie_and_missing_request(api_client):
    http, app, calls = api_client
    assert post(http, "missing").status_code == 404
    assert http.get("/api/status?request_id=missing").status_code == 404
    movies = app.extensions["movie_service"]
    movies._movies[0]["id"] = "invalid id"
    movies._validate()
    response = post(http)
    assert response.status_code == 409
    assert response.json["error"]["code"] == "movie_unavailable"
    movies.validation_errors = ["bad_catalog"]
    assert http.get("/api/movies").status_code == post(http).status_code == 503
    # Invalid new catalog does not revoke legacy syntactically valid pass-through.
    assert http.get("/play/unknown-valid").status_code == 200
    assert not calls


def test_busy_cooldown_retry_after_and_device_failure_are_separate(api_client, monkeypatch):
    http, app, calls = api_client
    entered, release = Event(), Event()
    def launch(*a, **k):
        entered.set()
        assert release.wait(3)
        raise DeliveryError("device_unauthorized", connection="unauthorized")
    monkeypatch.setattr(app.extensions["firetv_service"], "launch_movie_bounded", launch)
    service = app.extensions["playback_service"]
    service.cooldown_seconds = 2
    first = post(http)
    try:
        assert first.status_code == 202
        assert entered.wait(3)
        response = post(http, "moana", "request-002")
        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) >= 1
        assert response.json["error"]["code"] == "busy"
    finally:
        release.set()
    terminal(service, first.json["request_id"])
    assert http.get(first.json["status_url"]).json["request"]["error"]["code"] == "device_unauthorized"
    response = post(http, "moana", "request-002")
    assert response.status_code == 429
    assert response.json["error"]["code"] == "cooldown"


def test_flag_off_legacy_and_flag_on_private_html(api_client):
    http, app, calls = api_client
    legacy = http.get("/")
    assert "luca-id" in legacy.get_data(as_text=True)
    assert legacy.headers["Cache-Control"] == "public, max-age=300"
    app.config["TABLET_API_ENABLED"] = True
    modern = http.get("/")
    assert modern.headers["Cache-Control"] == "no-cache"
    assert "luca-id" not in modern.get_data(as_text=True)
    assert "moana-id" not in modern.get_data(as_text=True)
    html = modern.get_data(as_text=True)
    assert 'aria-label="Request Luca on Fire TV"' in html
    assert 'role="status" aria-live="polite" aria-atomic="true"' in html
    assert '<button type="button"' in html
    assert '<noscript>' in html
    app.extensions["movie_service"].validation_errors = ["bad_catalog"]
    broken = http.get("/").get_data(as_text=True)
    assert "catalog is unavailable" in broken
    assert "/play/" not in broken


@pytest.mark.parametrize("path", ["/api/movies?unexpected=true", "/api/status?unexpected=true",
                                   "/api/status?request_id=a&request_id=b", "/api/status?request_id="])
def test_query_fields_are_strict(api_client, path):
    http, app, calls = api_client
    response = http.get(path)
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_request"
    assert not calls


def test_job_cap_and_stopped_dispatcher_return_unadmitted_503(api_client):
    http, app, calls = api_client
    service = app.extensions["playback_service"]
    service.max_records = 1
    first = post(http)
    terminal(service, first.json["request_id"])
    response = post(http, "moana", "request-002")
    assert response.status_code == 503
    assert response.json["error"]["code"] == "dispatcher_unavailable"
    assert ("lan-household", "request-002") not in service._idempotency
    service.shutdown()
    assert post(http, "moana", "request-003").status_code == 503


def test_admission_and_status_p95_with_100_rows(api_client, record_property):
    http, app, calls = api_client
    movies = app.extensions["movie_service"]
    movies._movies = [{"key": f"movie-{i}", "title": f"Movie {i}", "id": f"private-{i}", "aliases": []}
                      for i in range(100)]
    movies._validate()
    durations, status_durations = [], []
    for i in range(50):
        start = perf_counter()
        response = post(http, "movie-0", f"benchmark-{i:03}")
        durations.append((perf_counter() - start) * 1000)
        assert response.status_code == 202
        terminal(app.extensions["playback_service"], response.json["request_id"])
        start = perf_counter()
        assert http.get(response.json["status_url"]).status_code == 200
        status_durations.append((perf_counter() - start) * 1000)
    admission_p95 = quantiles(durations, n=20)[18]
    status_p95 = quantiles(status_durations, n=20)[18]
    record_property("admission_p95_ms", admission_p95)
    record_property("status_p95_ms", status_p95)
    print(f"\nadmission p95={admission_p95:.2f}ms; status p95={status_p95:.2f}ms")
    assert admission_p95 < 250
    assert status_p95 < 250
    assert len(http.get("/api/movies").data) < 256 * 1024
