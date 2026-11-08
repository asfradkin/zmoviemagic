import json
from pathlib import Path

import pytest

from tools.migrate_catalog import migrate, run


def inputs(tmp_path):
    source, manifest = tmp_path / "movies.json", tmp_path / "manifest.json"
    rows = [{"title": "Luca", "id": "private-id", "poster": "original", "extra": {"a": [1]}}]
    source.write_text(json.dumps(rows), encoding="utf-8")
    manifest.write_text(json.dumps({"private-id": {"key": "luca", "aliases": []}}), encoding="utf-8")
    return source, manifest


def test_dry_run_writes_nothing_even_in_place(tmp_path):
    source, manifest = inputs(tmp_path)
    original = source.read_bytes()
    before = set(tmp_path.iterdir())
    report = run(source, manifest, source)
    assert report["rows"] == report["changed_rows"] == 1
    assert report["preserved_original_fields"]
    assert source.read_bytes() == original
    assert set(tmp_path.iterdir()) == before
    run(source, manifest, tmp_path / "absent" / "output.json")
    assert set(tmp_path.iterdir()) == before


def test_apply_backup_and_second_run_unchanged(tmp_path):
    source, manifest = inputs(tmp_path)
    original = source.read_bytes()
    report = run(source, manifest, source, apply=True)
    assert Path(report["backup"]).read_bytes() == original
    migrated = source.read_bytes()
    assert json.loads(migrated)[0]["extra"] == {"a": [1]}
    assert run(source, manifest, source, apply=True)["unchanged"]
    assert source.read_bytes() == migrated
    assert len(list(tmp_path.glob("*.backup-*"))) == 1


@pytest.mark.parametrize("operation", ["replace", "fsync"])
def test_write_failure_leaves_original_intact(tmp_path, monkeypatch, operation):
    source, manifest = inputs(tmp_path)
    original = source.read_bytes()
    def fail(*args):
        raise OSError("injected")
    monkeypatch.setattr("tools.migrate_catalog.os." + operation, fail)
    with pytest.raises(OSError):
        run(source, manifest, source, apply=True)
    assert source.read_bytes() == original
    assert not list(tmp_path.glob(".catalog-*"))


def test_duplicate_ids_and_conflicting_keys_require_review(tmp_path):
    source, manifest = inputs(tmp_path)
    rows = json.loads(source.read_text())
    assignments = json.loads(manifest.read_text())
    with pytest.raises(ValueError, match="duplicate provider ID"):
        migrate(rows * 2, assignments)
    rows[0]["key"] = "permanent"
    with pytest.raises(ValueError, match="existing key conflicts"):
        migrate(rows, assignments)


def test_all_44_rows_preserved_and_manifest_valid():
    root = Path(__file__).resolve().parents[1]
    rows = json.loads((root / "movies.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "docs/catalog-key-manifest.json").read_text(encoding="utf-8"))
    result = migrate(rows, manifest)
    assert len(result) == 44
    assert len({m["key"] for m in result}) == 44
    assert all(all(after[k] == v for k, v in before.items()) for before, after in zip(rows, result))
    assert migrate(result, manifest) == result
