"""Persist lead workflow fields keyed by company_number."""
from __future__ import annotations

import json
from pathlib import Path

ASSIGNMENTS_PATH = Path("data") / "assignments.json"

WORKFLOW_STATUSES = [
    "Not contacted",
    "Contacted",
    "Follow-up",
    "Interested",
    "Onboarding",
    "Not fit",
]


def _load_all() -> dict[str, dict]:
    if not ASSIGNMENTS_PATH.exists():
        return {}
    try:
        with ASSIGNMENTS_PATH.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_all(data: dict[str, dict]) -> None:
    ASSIGNMENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with ASSIGNMENTS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def get(company_number: str) -> dict:
    return _load_all().get(company_number, {})


def set_assignment(
    company_number: str,
    assigned_to: str | None = None,
    notes: str | None = None,
    status: str | None = None,
    contacted_at: str | None = None,
    follow_up_at: str | None = None,
) -> dict:
    data = _load_all()
    entry = data.get(company_number, {})
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
    data[company_number] = entry
    _save_all(data)
    return entry


def merge_into_rows(rows: list[dict]) -> list[dict]:
    stored = _load_all()
    for row in rows:
        num = row.get("company_number", "")
        if not num:
            continue
        entry = stored.get(num, {})
        if entry.get("assigned_to"):
            row["assigned_to"] = entry["assigned_to"]
        if entry.get("notes"):
            row["notes"] = entry["notes"]
        row["status"] = entry.get("status") or "Not contacted"
        row["contacted_at"] = entry.get("contacted_at") or ""
        row["follow_up_at"] = entry.get("follow_up_at") or ""
    return rows
