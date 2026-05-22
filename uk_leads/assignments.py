"""Persist lead workflow fields keyed by lead_id."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from filelock import FileLock, Timeout

from uk_leads.dashboard import lead_id

logger = logging.getLogger(__name__)

ASSIGNMENTS_FILE = Path("data") / "assignments.json"
LOCK_FILE = Path("data") / "assignments.json.lock"

WORKFLOW_STATUSES = [
    "Not contacted",
    "Contacted",
    "Follow-up",
    "Interested",
    "Onboarding",
    "Not fit",
]

DEFAULT_POOLS = {
    "direct_clients": ["Ismael", "Tasneem"],
    "introducers": ["Aisha", "Stephen", "Rajesh"],
}

LOCK_TIMEOUT_SECONDS = 10
LOCK_WRITE_MESSAGE = (
    "Assignment save failed — file is locked, please try again in a moment"
)


class AssignmentLockError(Exception):
    """Raised when assignments.json cannot be locked for writing."""


def _empty_store() -> dict:
    return {"leads": {}}


def _load() -> dict:
    lock = FileLock(LOCK_FILE, timeout=LOCK_TIMEOUT_SECONDS)
    try:
        with lock:
            if not ASSIGNMENTS_FILE.exists():
                return _empty_store()
            try:
                with ASSIGNMENTS_FILE.open(encoding="utf-8") as fh:
                    data = json.load(fh)
            except (json.JSONDecodeError, OSError):
                return _empty_store()

            if "leads" in data:
                return {"leads": dict(data.get("leads") or {})}

            leads = {}
            for key, entry in data.items():
                if key in ("counters", "leads"):
                    continue
                if isinstance(entry, dict):
                    leads[key] = entry
            return {"leads": leads}
    except Timeout:
        logger.warning("Could not acquire assignments lock for read within %ss", LOCK_TIMEOUT_SECONDS)
        if ASSIGNMENTS_FILE.exists():
            try:
                with ASSIGNMENTS_FILE.open(encoding="utf-8") as fh:
                    data = json.load(fh)
                if "leads" in data:
                    return {"leads": dict(data.get("leads") or {})}
            except (json.JSONDecodeError, OSError):
                pass
        return _empty_store()


def _save(data: dict) -> None:
    lock = FileLock(LOCK_FILE, timeout=LOCK_TIMEOUT_SECONDS)
    try:
        with lock:
            ASSIGNMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            payload = {"leads": dict(data.get("leads") or {})}
            with ASSIGNMENTS_FILE.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
    except Timeout as exc:
        logger.warning("Could not acquire assignments lock for write within %ss", LOCK_TIMEOUT_SECONDS)
        raise AssignmentLockError(LOCK_WRITE_MESSAGE) from exc


def get(lead_id_key: str) -> dict:
    return _load()["leads"].get(lead_id_key, {})


def set_assignment(
    lead_id_key: str,
    assigned_to: str | None = None,
    notes: str | None = None,
    status: str | None = None,
    contacted_at: str | None = None,
    follow_up_at: str | None = None,
) -> dict:
    store = _load()
    entry = store["leads"].get(lead_id_key, {})
    if assigned_to is not None:
        entry["assigned_to"] = assigned_to
    if notes is not None:
        entry["notes"] = notes
    if status is not None:
        entry["status"] = status
    if contacted_at is not None:
        entry["contacted_at"] = contacted_at
    if follow_up_at is not None:
        entry["follow_up_at"] = follow_up_at
    if "status" not in entry:
        entry.setdefault("status", "Not contacted")
    store["leads"][lead_id_key] = entry
    _save(store)
    return entry


def merge_saved_fields(rows: list[dict], pools: dict[str, list[str]] | None = None) -> list[dict]:
    """Merge persisted workflow fields only. Does not assign or write."""
    _ = pools
    store = _load()

    for row in rows:
        lid = row.get("lead_id") or lead_id(row)
        row["lead_id"] = lid
        entry = store["leads"].get(lid, {})
        row["assigned_to"] = (entry.get("assigned_to") or "").strip()
        row["notes"] = entry.get("notes") or ""
        row["status"] = entry.get("status") or "Not contacted"
        row["contacted_at"] = entry.get("contacted_at") or ""
        row["follow_up_at"] = entry.get("follow_up_at") or ""

    return rows


def apply_assignments(rows: list[dict], pools: dict[str, list[str]] | None = None) -> list[dict]:
    """Backward-compatible alias for read-only merge (no auto-assign on load)."""
    return merge_saved_fields(rows, pools=pools)


def merge_into_rows(rows: list[dict]) -> list[dict]:
    """Backward-compatible wrapper."""
    from uk_leads.dev_config import load_config

    config = load_config()
    pools = config.get("assignment_pools", DEFAULT_POOLS)
    return merge_saved_fields(rows, pools=pools)


def assignment_stats(rows: list[dict]) -> dict[str, int]:
    stats: dict[str, int] = {}
    for row in rows:
        who = (row.get("assigned_to") or "").strip()
        if who:
            stats[who] = stats.get(who, 0) + 1
    return stats
