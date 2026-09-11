import json

import pytest

from services.movie_service import MovieService


@pytest.fixture
def movie_file(tmp_path):
    path = tmp_path / "movies.json"
    path.write_text(
        json.dumps(
            [
                {
                    "title": "Luca",
                    "id": "luca-id",
                    "poster": "https://example.com/luca.jpg",
                },
                {
                    "title": "Moana",
                    "id": "moana-id",
                    "poster": "https://example.com/moana.jpg",
                },
            ]
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def movie_service(movie_file):
    service = MovieService(str(movie_file), tmdb_api_key="test")
    service.load()
    return service


@pytest.fixture
def fake_firetv():
    class FakeFireTV:
        def __init__(self):
            self.launched = []
            self.retried = False

        def launch_movie(self, video_id):
            self.launched.append(video_id)
            return {"retried": self.retried}

    return FakeFireTV()
