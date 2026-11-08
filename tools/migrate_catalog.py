"""Explicit, backed-up catalog migration. Importing this module never writes data."""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.movie_service import MovieService


def migrate(rows, manifest):
    if not isinstance(rows, list) or not isinstance(manifest, dict):
        raise ValueError("Catalog must be an array and manifest must be an object")
    result, ids = copy.deepcopy(rows), set()
    for index, movie in enumerate(result):
        if not isinstance(movie, dict):
            raise ValueError(f"Row {index + 1}: expected object")
        provider_id = movie.get("id")
        if not isinstance(provider_id, str) or not provider_id:
            raise ValueError(f"Row {index + 1}: missing provider ID")
        if provider_id in ids:
            raise ValueError(f"Row {index + 1}: duplicate provider ID requires review")
        ids.add(provider_id)
        assignment = manifest.get(provider_id)
        if not isinstance(assignment, dict) or set(assignment) != {"key", "aliases"}:
            raise ValueError(f"Row {index + 1}: missing or invalid manifest assignment")
        if "key" in movie and movie["key"] != assignment["key"]:
            raise ValueError(f"Row {index + 1}: existing key conflicts with manifest")
        movie.setdefault("key", assignment["key"])
        movie.setdefault("aliases", copy.deepcopy(assignment["aliases"]))
    service = MovieService("")
    service._movies = result
    service._validate()
    if service.validation_errors:
        raise ValueError("; ".join(service.validation_errors))
    return result


def atomic_write(path, data):
    """Write beside destination, fsync, then replace; clean up on all failures."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".catalog-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run(input_path, manifest_path, output_path, *, apply=False):
    source, manifest_file, destination = map(lambda p: Path(p).resolve(), (input_path, manifest_path, output_path))
    if manifest_file in (source, destination):
        raise ValueError("Manifest must be separate from input and output")
    original = source.read_bytes()
    rows = json.loads(original.decode("utf-8"))
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    result = migrate(rows, manifest)
    report = {"mode": "apply" if apply else "dry-run", "rows": len(result),
              "changed_rows": sum(a != b for a, b in zip(rows, result)),
              "input_sha256": hashlib.sha256(original).hexdigest(),
              "preserved_original_fields": all(all(b.get(k) == v for k, v in a.items()) for a, b in zip(rows, result)),
              "assignments": [{"row": i, "title": m["title"], "key": m["key"], "aliases": m["aliases"]}
                              for i, m in enumerate(result, 1)]}
    # Dry-run never opens output or creates directories/backups, even for in-place use.
    if apply:
        if source.read_bytes() != original:
            raise ValueError("Input changed during migration; review a new dry-run")
        if destination == source and result == rows:
            report["unchanged"] = True
            return report
        backup_source = destination if destination.exists() else source
        suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = backup_source.with_name(backup_source.name + ".backup-" + suffix)
        with backup.open("xb") as target, backup_source.open("rb") as existing:
            shutil.copyfileobj(existing, target)
            target.flush()
            os.fsync(target.fileno())
        if backup.read_bytes() != backup_source.read_bytes():
            raise ValueError("Backup verification failed")
        encoded = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        atomic_write(destination, encoded)
        report["backup"] = str(backup)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.input, args.manifest, args.output, apply=args.apply), indent=2, ensure_ascii=False))
    except (ValueError, OSError) as error:
        # Parsing errors can contain private input; never print raw diagnostics.
        print(f"Migration rejected ({type(error).__name__}); input/output unchanged unless replacement completed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
