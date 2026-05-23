"""Filesystem snapshot registry with additive compatibility for legacy exports/<date>.csv."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

SCHEMA_VERSION = 1

EXPORTS_DIR = Path("exports")
REGISTRY_DIR = EXPORTS_DIR / "_registry"
POINTER_PATH = REGISTRY_DIR / "published_pointer.json"
LOCK_PATH = REGISTRY_DIR / ".snapshot_registry.lock"

CANDIDATES_DIR = EXPORTS_DIR / "candidates"
PUBLISHED_DIR = EXPORTS_DIR / "published"
ARCHIVE_DIR = EXPORTS_DIR / "archive"


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _version_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_dirs() -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp_path, path)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            raw = json.load(fh)
            return raw if isinstance(raw, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _relative(path: Path) -> str:
    return path.as_posix()


def read_published_pointer() -> dict:
    _ensure_dirs()
    with FileLock(str(LOCK_PATH)):
        data = _read_json(POINTER_PATH)
    dates = data.get("dates")
    if not isinstance(dates, dict):
        dates = {}
    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": data.get("updated_at"),
        "dates": dates,
    }


def _write_published_pointer(payload: dict) -> None:
    with FileLock(str(LOCK_PATH)):
        _atomic_write_json(POINTER_PATH, payload)


def _manifest_path_for(csv_path: Path) -> Path:
    return csv_path.with_suffix(".manifest.json")


def _build_manifest(
    *,
    state: str,
    incorporation_date: str,
    csv_path: Path,
    source_kind: str,
    previous_published: str | None = None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "state": state,
        "mutable": state == "candidate",
        "incorporation_date": incorporation_date,
        "created_at": _now_utc(),
        "csv_path": _relative(csv_path),
        "source_kind": source_kind,
        "integrity": {
            "sha256": _sha256(csv_path),
            "size_bytes": csv_path.stat().st_size,
        },
        "previous_published": previous_published,
    }


def stage_candidate_from_legacy(incorporation_date: str, legacy_path: Path) -> tuple[Path, Path]:
    """Stage a mutable candidate by copying the legacy exports/<date>.csv file."""
    _ensure_dirs()
    if not legacy_path.exists():
        raise FileNotFoundError(f"Legacy snapshot not found: {legacy_path}")

    stamp = _version_stamp()
    day_dir = CANDIDATES_DIR / incorporation_date
    day_dir.mkdir(parents=True, exist_ok=True)
    candidate_csv = day_dir / f"candidate-{stamp}.csv"
    shutil.copy2(legacy_path, candidate_csv)

    manifest = _build_manifest(
        state="candidate",
        incorporation_date=incorporation_date,
        csv_path=candidate_csv,
        source_kind="legacy_export",
    )
    candidate_manifest = _manifest_path_for(candidate_csv)
    _atomic_write_json(candidate_manifest, manifest)
    return candidate_csv, candidate_manifest


def publish_candidate(incorporation_date: str, candidate_csv: Path) -> tuple[Path, Path]:
    """Promote candidate to published and atomically swap date pointer on Windows-safe os.replace."""
    _ensure_dirs()
    if not candidate_csv.exists():
        raise FileNotFoundError(f"Candidate snapshot not found: {candidate_csv}")

    day_dir = PUBLISHED_DIR / incorporation_date
    day_dir.mkdir(parents=True, exist_ok=True)
    stamp = _version_stamp()
    published_csv = day_dir / f"published-{stamp}.csv"

    pointer = read_published_pointer()
    previous = pointer.get("dates", {}).get(incorporation_date, {})
    previous_path = previous.get("csv_path") if isinstance(previous, dict) else None

    os.replace(candidate_csv, published_csv)
    candidate_manifest = _manifest_path_for(candidate_csv)
    if candidate_manifest.exists():
        os.replace(candidate_manifest, _manifest_path_for(published_csv))

    published_manifest_payload = _build_manifest(
        state="published",
        incorporation_date=incorporation_date,
        csv_path=published_csv,
        source_kind="registry_candidate",
        previous_published=previous_path,
    )
    published_manifest = _manifest_path_for(published_csv)
    _atomic_write_json(published_manifest, published_manifest_payload)

    if previous_path:
        previous_csv = Path(previous_path)
        if previous_csv.exists():
            archive_day = ARCHIVE_DIR / incorporation_date
            archive_day.mkdir(parents=True, exist_ok=True)
            archived_csv = archive_day / f"archived-{stamp}.csv"
            shutil.copy2(previous_csv, archived_csv)
            archived_manifest = _manifest_path_for(archived_csv)
            archived_manifest_payload = _build_manifest(
                state="archived",
                incorporation_date=incorporation_date,
                csv_path=archived_csv,
                source_kind="published_rollover",
                previous_published=previous_path,
            )
            _atomic_write_json(archived_manifest, archived_manifest_payload)

    pointer_payload = read_published_pointer()
    pointer_payload["updated_at"] = _now_utc()
    pointer_payload.setdefault("dates", {})[incorporation_date] = {
        "csv_path": _relative(published_csv),
        "manifest_path": _relative(published_manifest),
        "published_at": _now_utc(),
        "schema_version": SCHEMA_VERSION,
    }
    _write_published_pointer(pointer_payload)
    return published_csv, published_manifest


def publish_legacy_snapshot(incorporation_date: str) -> tuple[Path, Path]:
    """Convenience path: stage exports/<date>.csv as candidate and publish it."""
    legacy = EXPORTS_DIR / f"{incorporation_date}.csv"
    candidate_csv, _ = stage_candidate_from_legacy(incorporation_date, legacy)
    return publish_candidate(incorporation_date, candidate_csv)


def resolve_snapshot_path(incorporation_date: str) -> Path:
    """Resolve snapshot path using published pointer first, then legacy exports/<date>.csv."""
    pointer = read_published_pointer()
    entry = pointer.get("dates", {}).get(incorporation_date, {})
    published_path = entry.get("csv_path") if isinstance(entry, dict) else None
    if published_path:
        p = Path(published_path)
        if p.exists():
            return p
    return EXPORTS_DIR / f"{incorporation_date}.csv"