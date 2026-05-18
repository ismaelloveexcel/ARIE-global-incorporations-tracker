"""Data freshness status and dashboard banner for /api/data-status."""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from pathlib import Path

from uk_leads.app_mode import is_production
from uk_leads.core import csv_path_for_date
from uk_leads.data_loader import mauritius_export_stats, pipeline_export_path
from uk_leads.run_summary import load_run_summary


def _mtime_iso(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as fh:
        return sum(1 for _ in csv.DictReader(fh))


def _count_pipeline_uk(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            source = (row.get("source") or "").strip().lower()
            if source == "companies_house" or (row.get("jurisdiction") or "").strip() == "UK":
                count += 1
    return count


def _format_display_date(iso_date: str) -> str:
    try:
        d = date.fromisoformat(iso_date[:10])
        return d.strftime("%d %b %Y")
    except ValueError:
        return iso_date


def _uk_status(target: str, demo: bool) -> dict:
    path = csv_path_for_date(target, demo=demo)
    if path.exists():
        return {
            "exists": True,
            "row_count": _count_csv_rows(path),
            "file_modified": _mtime_iso(path),
            "path": str(path),
        }
    if demo:
        full = csv_path_for_date(target, demo=False)
        if full.exists():
            return {
                "exists": True,
                "row_count": _count_csv_rows(full),
                "file_modified": _mtime_iso(full),
                "path": str(full),
            }
    pipe = pipeline_export_path(target)
    uk_rows = _count_pipeline_uk(pipe)
    if uk_rows > 0:
        return {
            "exists": True,
            "row_count": uk_rows,
            "file_modified": _mtime_iso(pipe),
            "path": str(pipe),
        }
    return {"exists": False, "row_count": 0, "file_modified": None, "path": str(path)}


def _mauritius_status(target: str) -> dict:
    stats = mauritius_export_stats(target)
    path = pipeline_export_path(target)
    return {
        "exists": bool(stats.get("gbc_ac", 0) > 0),
        "export_file_exists": stats.get("exists", False),
        "row_count": int(stats.get("gbc_ac", 0)),
        "file_modified": _mtime_iso(path) if path.exists() else None,
        "path": str(path),
    }


def _summary_for_date(target: str) -> dict | None:
    summary = load_run_summary()
    if not summary:
        return None
    if summary.get("run_date") != target:
        return {
            "pipeline_outcome": summary.get("pipeline_outcome"),
            "notes": summary.get("notes"),
            "run_date": summary.get("run_date"),
            "matches_selected_date": False,
            "connectors": summary.get("connectors") or {},
            "run_timestamp": summary.get("run_timestamp"),
        }
    return {
        "pipeline_outcome": summary.get("pipeline_outcome"),
        "notes": summary.get("notes"),
        "run_date": summary.get("run_date"),
        "matches_selected_date": True,
        "connectors": summary.get("connectors") or {},
        "run_timestamp": summary.get("run_timestamp"),
    }


def _connector_error(summary: dict | None, key: str) -> str | None:
    if not summary:
        return None
    conn = (summary.get("connectors") or {}).get(key) or {}
    if conn.get("outcome") == "ERROR":
        return conn.get("error_message") or "failed"
    return None


def _build_banner(
    target: str,
    is_today: bool,
    uk: dict,
    mu: dict,
    summary: dict | None,
    now: datetime,
) -> dict:
    none = {
        "type": "none",
        "message": "",
        "show_alerts_link": False,
        "pipeline_command": None,
        "auto_hide_seconds": None,
        "details": {},
    }
    display = _format_display_date(target)
    pipeline_cmd = None if is_production() else f"python main.py --date {target} --skip-difc"

    if not is_today:
        if uk["exists"] or mu["exists"]:
            return none
        return none

    outcome = (summary or {}).get("pipeline_outcome") if (summary or {}).get(
        "matches_selected_date", True
    ) else None
    if summary and not summary.get("matches_selected_date"):
        outcome = None

    ch_err = _connector_error(summary, "companies_house")
    mu_err = _connector_error(summary, "mauritius_mns")
    past_07 = now.hour >= 7

    if outcome == "FAILED":
        return {
            "type": "red",
            "message": (
                f"Pipeline failed on {display} — no new leads loaded. "
                "Both UK and Mauritius connectors failed."
            ),
            "show_alerts_link": True,
            "pipeline_command": None,
            "auto_hide_seconds": None,
            "details": {"display_date": display},
        }

    if outcome == "PARTIAL":
        uk_bit = f"UK: {uk['row_count']} leads ✓" if uk["exists"] else "UK: failed ✗"
        if mu["exists"]:
            mu_bit = f"Mauritius: {mu['row_count']} leads ✓"
        elif mu_err:
            mu_bit = f"Mauritius: failed ✗"
        else:
            mu_bit = "Mauritius: missing ✗"
        return {
            "type": "amber",
            "message": (
                f"Partial data for {display} — {uk_bit} · {mu_bit}. "
                "One connector failed. Showing available data only."
            ),
            "show_alerts_link": True,
            "pipeline_command": None,
            "auto_hide_seconds": None,
            "details": {
                "display_date": display,
                "variant": "partial",
                "uk_ok": uk["exists"],
                "mu_ok": mu["exists"],
            },
        }

    if not uk["exists"] and past_07:
        return {
            "type": "red",
            "message": (
                f"Pipeline failed on {display} — no new leads loaded. "
                "No UK export file found for today."
            ),
            "show_alerts_link": True,
            "pipeline_command": None,
            "auto_hide_seconds": None,
            "details": {"display_date": display},
        }

    if uk["exists"] and not mu["exists"] and not mu_err and outcome not in (
        "FAILED",
        "PARTIAL",
    ):
        mu_tail = (
            "Mauritius will appear when the overnight snapshot includes it."
            if is_production()
            else "To add Mauritius, run the pipeline for this date."
        )
        return {
            "type": "amber",
            "message": (
                f"Mauritius data not available for {display}. "
                f"Showing UK leads only. {mu_tail}"
            ),
            "show_alerts_link": is_production(),
            "pipeline_command": pipeline_cmd,
            "auto_hide_seconds": None,
            "details": {"display_date": display, "variant": "mauritius_missing"},
        }

    if is_today and (
        (uk["exists"] and not mu["exists"] and mu_err)
        or (not uk["exists"] and mu["exists"])
    ):
        return {
            "type": "amber",
            "message": (
                f"Partial data for {display} — "
                f"{'UK: ' + str(uk['row_count']) + ' leads ✓' if uk['exists'] else 'UK: failed ✗'} · "
                f"{'Mauritius: ' + str(mu['row_count']) + ' leads ✓' if mu['exists'] else 'Mauritius: failed ✗'}. "
                "One connector failed. Showing available data only."
            ),
            "show_alerts_link": True,
            "pipeline_command": None,
            "auto_hide_seconds": None,
            "details": {"display_date": display, "variant": "partial"},
        }

    if uk["exists"] and outcome in ("OK", "ALL_EMPTY", None):
        if mu["exists"] or outcome == "ALL_EMPTY":
            ts = (summary or {}).get("run_timestamp") or uk.get("file_modified") or ""
            time_part = ""
            if ts:
                try:
                    t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    time_part = t.strftime("%H:%M")
                except ValueError:
                    time_part = ts
            mu_n = mu["row_count"] if mu["exists"] else 0
            return {
                "type": "green",
                "message": (
                    f"Data is fresh — last updated {time_part} UTC · "
                    f"UK: {uk['row_count']} leads · Mauritius: {mu_n} leads"
                ),
                "show_alerts_link": False,
                "pipeline_command": None,
                "auto_hide_seconds": 5,
                "details": {"display_date": display},
            }

    return none


def get_data_status(target: str, demo: bool = True) -> dict:
    today = date.today().isoformat()
    is_today = target == today
    now = datetime.now(timezone.utc)

    uk = _uk_status(target, demo=demo)
    mu = _mauritius_status(target)
    summary = _summary_for_date(target)
    banner = _build_banner(target, is_today, uk, mu, summary, now)

    run_summary_out = None
    if summary:
        run_summary_out = {
            "pipeline_outcome": summary.get("pipeline_outcome"),
            "notes": summary.get("notes"),
            "run_date": summary.get("run_date"),
            "matches_selected_date": summary.get("matches_selected_date", True),
        }

    return {
        "date": target,
        "is_today": is_today,
        "uk": {
            "exists": uk["exists"],
            "row_count": uk["row_count"],
            "file_modified": uk["file_modified"],
        },
        "mauritius": {
            "exists": mu["exists"],
            "row_count": mu["row_count"],
            "file_modified": mu["file_modified"],
        },
        "run_summary": run_summary_out,
        "banner": banner,
    }
