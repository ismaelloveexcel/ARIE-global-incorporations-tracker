"""Track last successful API refresh per incorporation date."""
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


def record_refresh(incorporation_date: str, demo: bool, total_fetched: int, exported: int) -> str:
    ts = datetime.now(timezone.utc).isoformat()
    data = _load()
    key = f"{incorporation_date}:{'demo' if demo else 'full'}"
    data[key] = {
        "incorporation_date": incorporation_date,
        "demo": demo,
        "refreshed_at": ts,
        "total_fetched": total_fetched,
        "exported": exported,
    }
    _save(data)
    return ts


def get_last_refresh(incorporation_date: str, demo: bool) -> str | None:
    data = _load()
    key = f"{incorporation_date}:{'demo' if demo else 'full'}"
    entry = data.get(key)
    if entry:
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


def list_refreshed_dates(demo: bool) -> list[str]:
    """Incorporation dates that were loaded via the in-app UK refresh."""
    data = _load()
    out: list[str] = []
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        if bool(entry.get("demo")) != demo:
            continue
        d = (entry.get("incorporation_date") or "").strip()
        if d:
            out.append(d)
    return sorted(set(out), reverse=True)
