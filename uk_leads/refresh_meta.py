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
