def test_movie_service_loads_existing_schema(movie_service):
    movies = movie_service.all()

    assert len(movies) == 2
    assert movies[0] == {
        "title": "Luca",
        "id": "luca-id",
        "poster": "https://example.com/luca.jpg",
    }


def test_movie_service_finds_movie_by_disney_id(movie_service):
    assert movie_service.get_by_id("moana-id")["title"] == "Moana"


def test_movie_service_returns_none_for_unknown_id(movie_service):
    assert movie_service.get_by_id("does-not-exist") is None


def test_library_preserves_existing_ui_shape(movie_service):
    assert movie_service.library() == movie_service.all()
