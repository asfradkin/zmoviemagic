import importlib
import sys

import pytest


@pytest.fixture
def client(movie_file, monkeypatch):
    monkeypatch.setenv("TRUSTED_LAN_CIDRS", "127.0.0.1/32,::1/128")
    monkeypatch.setenv("ALLOWED_HOSTS", "localhost,localhost:80,[::1]")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-only-session-key-0123456789abcdef")
    monkeypatch.setenv("REMOTE_API_ENABLED", "false")
    monkeypatch.setenv("TABLET_API_ENABLED", "false")
    monkeypatch.setenv("API_TOKEN_FILE", "")
    monkeypatch.setenv("TMDB_API_KEY", "test-key")
    monkeypatch.setenv("MOVIES_FILE", str(movie_file))
    monkeypatch.setenv("PLAY_COOLDOWN_SECONDS", "0")

    sys.modules.pop("app", None)
    sys.modules.pop("config", None)
    app_module = importlib.import_module("app")
    app = app_module.app
    app.testing = True

    launched = []

    def launch_movie(video_id):
        launched.append(video_id)
        return {"retried": False}

    monkeypatch.setattr(
        app.extensions["firetv_service"], "launch_movie", launch_movie
    )
    app.extensions["test_launched"] = launched
    http = app.test_client()
    http.get("/")
    with http.session_transaction() as session:
        http.environ_base["HTTP_X_CSRF_TOKEN"] = session["csrf"]
    return http, app


def test_legacy_play_route_returns_existing_response(client):
    test_client, app = client

    response = test_client.get("/play/luca-id")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "success",
        "message": "Playing video luca-id",
    }
    assert app.extensions["test_launched"] == ["luca-id"]


def test_legacy_route_keeps_valid_pass_through_behavior(client):
    test_client, app = client

    response = test_client.get("/play/not-in-catalog")

    assert response.status_code == 200
    assert app.extensions["test_launched"] == ["not-in-catalog"]


def test_legacy_play_route_rejects_invalid_id(client):
    test_client, app = client

    response = test_client.get("/play/not%20valid")

    assert response.status_code == 400
    assert response.get_json()["message"] == "Invalid video ID"
    assert app.extensions["test_launched"] == []


def test_health_does_not_contact_firetv(client, monkeypatch):
    test_client, app = client

    def unexpected_call(*args, **kwargs):
        pytest.fail("Health check contacted Fire TV")

    monkeypatch.setattr(app.extensions["firetv_service"], "get_device", unexpected_call)
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("error,code", [
    (PermissionError("device unauthorized"), 403),
    (RuntimeError("ADB operation timed out"), 500),
])
def test_playback_failures_remain_json(client, monkeypatch, error, code):
    test_client, app = client

    def launch(video_id):
        raise error

    monkeypatch.setattr(app.extensions["firetv_service"], "launch_movie", launch)
    response = test_client.get("/play/luca-id")
    assert response.status_code == code
    assert response.get_json() == {"status": "error", "message": str(error)}
