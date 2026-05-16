"""Load pipeline run summary written by main.py to exports/run_summary.json."""
from __future__ import annotations

import json
from pathlib import Path

RUN_SUMMARY_PATH = Path("exports") / "run_summary.json"


def load_run_summary() -> dict | None:
    if not RUN_SUMMARY_PATH.exists():
        return None
    try:
        with RUN_SUMMARY_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def last_run_for_health() -> dict | None:
    """Shape run_summary for /api/dev/health last_run block."""
    summary = load_run_summary()
    if not summary:
        return None
    connectors = summary.get("connectors") or {}
    ch = connectors.get("companies_house") or {}
    mu = connectors.get("mauritius_mns") or {}
    return {
        "date": summary.get("run_date"),
        "timestamp": summary.get("run_timestamp"),
        "pipeline_outcome": summary.get("pipeline_outcome"),
        "companies_house": {
            "outcome": ch.get("outcome"),
            "record_count": ch.get("record_count"),
            "error_message": ch.get("error_message"),
        },
        "mauritius_mns": {
            "outcome": mu.get("outcome"),
            "record_count": mu.get("record_count"),
            "error_message": mu.get("error_message"),
        },
        "notes": summary.get("notes"),
    }
