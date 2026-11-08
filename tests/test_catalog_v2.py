import json

import pytest

from services.movie_service import MovieService, normalize_name, safe_poster


def load_catalog(tmp_path, rows):
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    service = MovieService(str(path))
    service.load()
    return service


def row(key="luca", **extra):
    return {"key": key, "title": "Luca", "id": "private-id", "aliases": [], **extra}


def test_legacy_and_mixed_catalogs_block_new_api_only(tmp_path):
    service = load_catalog(tmp_path, [row(), {"title": "Legacy", "id": "old"}])
    assert not service.catalog_available
    assert len(service.library()) == 2
    with pytest.raises(ValueError, match="catalog_unavailable"):
        service.public_catalog()


@pytest.mark.parametrize("rows", [[row(), row()], [row("Bad Key")], [row(aliases=[""])],
                                  [row(aliases=["a"] * 21)], [row(title="")], [None]])
def test_invalid_catalog_rejected(tmp_path, rows):
    assert not load_catalog(tmp_path, rows).catalog_available


def test_empty_valid_is_distinct_from_unreadable(tmp_path):
    service = load_catalog(tmp_path, [])
    assert service.catalog_available
    assert service.public_catalog()["movies"] == []
    path = tmp_path / "catalog.json"
    path.write_text("invalid", encoding="utf-8")
    service.load()
    assert not service.catalog_available
    with pytest.raises(ValueError):
        service.save()
    assert path.read_text() == "invalid"


def test_normalization_and_ambiguity(tmp_path):
    service = load_catalog(tmp_path, [row("wall-e", title="WALL·E", aliases=["wall ee"]),
                                     row("other", title="Other", aliases=["Wall EE"])])
    assert normalize_name("  ＷＡＬＬ·Ｅ  ") == "wall e"
    assert service.resolve("wall ee") == {"state": "ambiguous", "candidates": ["other", "wall-e"]}
    assert service.resolve("WALL-E")["candidates"] == ["wall-e"]
    assert service.resolve("unknown")["state"] == "unknown"
    assert "wall ee" in service.ambiguous_names


def test_public_catalog_revision_has_no_provider_material(tmp_path):
    service = load_catalog(tmp_path, [row(extra={"keep": True})])
    original = service.public_catalog()
    assert "private-id" not in json.dumps(original)
    service._movies[0]["id"] = "different-id"
    assert service.public_catalog() == original
    service._movies[0]["id"] = "invalid id"
    assert service.public_catalog()["movies"][0]["available"] is False
    copy = service.get_by_key("luca")
    copy["title"] = "Renamed"
    assert service.get_by_key("luca")["title"] == "Luca"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://example.com/a", "//example.com/a",
                                 "/static/../evil", "/static/%2e%2e/evil", "https://user:pass@example.com/a"])
def test_unsafe_posters_use_local_fallback(url):
    assert safe_poster(url) == "/static/poster-fallback.svg"


def test_posters_refresh_without_losing_keys_or_unknown_fields(tmp_path, monkeypatch):
    service = load_catalog(tmp_path, [row(custom={"preserved": True})])
    monkeypatch.setattr(service, "fetch_poster_for_title", lambda title: "https://example.com/a.jpg")
    service.refresh_missing_posters()
    saved = json.loads((tmp_path / "catalog.json").read_text())
    assert saved[0]["key"] == "luca"
    assert saved[0]["custom"] == {"preserved": True}


def test_numbers_require_explicit_alias_and_title_change_preserves_key(tmp_path):
    service = load_catalog(tmp_path, [row("frozen-2", title="Frozen II", aliases=["frozen two"])])
    assert service.resolve("frozen 2")["state"] == "unknown"
    assert service.resolve("Frozen TWO")["candidates"] == ["frozen-2"]
    service._movies[0]["title"] = "Changed title"
    service._validate()
    assert service.get_by_key("frozen-2")["title"] == "Changed title"


def test_missing_file_does_not_become_valid_or_save_empty(tmp_path):
    service = MovieService(str(tmp_path / "absent.json"))
    service.load()
    assert service.library() == []
    assert not service.catalog_available
    with pytest.raises(ValueError):
        service.save()
    assert not (tmp_path / "absent.json").exists()
