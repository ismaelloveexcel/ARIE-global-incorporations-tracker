"""Track last successful engineering snapshot build per incorporation date."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

META_PATH = Path("data") / "refresh_meta.json"


def _load() -> dict:
    if not META_PATH.exists():
        return {}
    try:
        with META_PATH.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    with META_PATH.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def record_refresh(
    incorporation_date: str, *, total_fetched: int, exported: int
) -> str:
    ts = datetime.now(timezone.utc).isoformat()
    data = _load()
    key = f"uk:{incorporation_date}"
    data[key] = {
        "incorporation_date": incorporation_date,
        "refreshed_at": ts,
        "total_fetched": total_fetched,
        "exported": exported,
    }
    _save(data)
    return ts


def get_last_refresh(incorporation_date: str) -> str | None:
    data = _load()
    entry = data.get(f"uk:{incorporation_date}")
    if entry:
        return entry.get("refreshed_at")
    # Legacy keys from pre-PR1 refresh metadata
    for legacy_key in (incorporation_date, f"{incorporation_date}:full", f"{incorporation_date}:demo"):
        entry = data.get(legacy_key)
        if isinstance(entry, dict) and entry.get("refreshed_at"):
            return entry.get("refreshed_at")
    return None


def record_mauritius_refresh(
    incorporation_date: str,
    exported: int,
    outcome: str,
    error_message: str | None = None,
) -> str:
    ts = datetime.now(timezone.utc).isoformat()
    data = _load()
    key = f"mauritius:{incorporation_date}"
    data[key] = {
        "incorporation_date": incorporation_date,
        "refreshed_at": ts,
        "exported": exported,
        "outcome": outcome,
        "error_message": error_message,
    }
    _save(data)
    return ts


def mauritius_refresh_attempted(incorporation_date: str) -> bool:
    data = _load()
    return f"mauritius:{incorporation_date}" in data


def get_last_mauritius_refresh(incorporation_date: str) -> str | None:
    data = _load()
    entry = data.get(f"mauritius:{incorporation_date}")
    if entry:
        return entry.get("refreshed_at")
    return None


def list_refreshed_dates() -> list[str]:
    """Incorporation dates that were loaded via the in-app UK refresh."""
    data = _load()
    out: list[str] = []
    for key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        if not str(key).startswith("uk:"):
            continue
        d = (entry.get("incorporation_date") or "").strip()
        if d:
            out.append(d)
    # Legacy entries without uk: prefix
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        if entry.get("demo") is not None:
            d = (entry.get("incorporation_date") or "").strip()
            if d:
                out.append(d)
    return sorted(set(out), reverse=True)
