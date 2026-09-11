import importlib
import sys

import pytest


@pytest.fixture
def client(movie_file, monkeypatch):
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
    return app.test_client(), app


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
