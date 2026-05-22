"""System health checks for /dev dashboard."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from uk_leads.data_loader import (
    mauritius_export_stats,
    pipeline_export_path,
    uk_pipeline_export_stats,
)
from uk_leads.env_config import companies_house_key_status, openai_key_status
from uk_leads.run_summary import last_run_for_health

CH_TEST_URL = "https://api.company-information.service.gov.uk/search/companies?q=test&items_per_page=1"


def _mtime_iso(path: Path) -> str | None:
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


def _ago_label(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - then
        mins = int(delta.total_seconds() // 60)
        if mins < 60:
            return f"{mins} min{'s' if mins != 1 else ''} ago"
        hours = mins // 60
        if hours < 48:
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        days = hours // 24
        return f"{days} day{'s' if days != 1 else ''} ago"
    except ValueError:
        return ""


def _count_csv_rows(path: Path) -> int:
    if not path.exists():
        return 0
    import csv

    with path.open(encoding="utf-8") as fh:
        return sum(1 for _ in csv.DictReader(fh))


def _format_display_date(iso_date: str) -> str:
    try:
        d = date.fromisoformat(iso_date[:10])
        return d.strftime("%d %b %Y")
    except ValueError:
        return iso_date


def run_health_checks(target_date: str | None = None) -> dict:
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    d = target_date or today.isoformat()

    checks: list[dict] = []
    checked_at = datetime.now(timezone.utc).isoformat()

    # Companies House API
    ch_status = companies_house_key_status()
    if not ch_status["configured"]:
        reason = ch_status.get("reason")
        msg = (
            "COMPANIES_HOUSE_API_KEY looks like a placeholder — set a real key in .env"
            if reason == "placeholder"
            else "COMPANIES_HOUSE_API_KEY not set in .env"
        )
        checks.append(
            {
                "id": "companies_house_api",
                "name": "Companies House API",
                "status": "error",
                "message": msg,
                "fix": "Add COMPANIES_HOUSE_API_KEY to your .env file and restart the app.",
            }
        )
    else:
        key = os.environ.get("COMPANIES_HOUSE_API_KEY", "").strip()
        try:
            resp = requests.get(CH_TEST_URL, auth=(key, ""), timeout=15)
            if resp.status_code == 200:
                checks.append(
                    {
                        "id": "companies_house_api",
                        "name": "Companies House API",
                        "status": "ok",
                        "message": "OK — API responding",
                    }
                )
            elif resp.status_code == 401:
                checks.append(
                    {
                        "id": "companies_house_api",
                        "name": "Companies House API",
                        "status": "error",
                        "message": "401 Unauthorized",
                        "fix": (
                            "Companies House API returned 401 — check that "
                            "COMPANIES_HOUSE_API_KEY in .env is correct and the key is active."
                        ),
                    }
                )
            else:
                checks.append(
                    {
                        "id": "companies_house_api",
                        "name": "Companies House API",
                        "status": "warning",
                        "message": f"Unexpected status {resp.status_code}",
                    }
                )
        except requests.RequestException as exc:
            checks.append(
                {
                    "id": "companies_house_api",
                    "name": "Companies House API",
                    "status": "error",
                    "message": str(exc),
                    "fix": "Check network connectivity and API key.",
                }
            )

    # Mauritius snapshot in pipeline export
    mu_path = pipeline_export_path(d)
    mu_yesterday = pipeline_export_path(yesterday)
    mu_file = mu_path if mu_path.exists() else (mu_yesterday if mu_yesterday.exists() else None)
    report_date = d if mu_path.exists() else yesterday
    if mu_file:
        stats = mauritius_export_stats(report_date if mu_path.exists() else yesterday)
        mtime = _mtime_iso(mu_file)
        display_date = _format_display_date(report_date if mu_path.exists() else yesterday)
        checks.append(
            {
                "id": "mauritius_export",
                "name": "Mauritius snapshot",
                "status": "ok" if stats["gbc_ac"] > 0 else "warning",
                "message": (
                    f"{display_date} — {stats['gbc_ac']} GBC/AC included · "
                    f"{stats['domestic_excluded']} domestic excluded"
                ),
                "detail": f"{stats['total']} Mauritius rows in export",
                "mtime": mtime,
                "ago": _ago_label(mtime),
            }
        )
    else:
        checks.append(
            {
                "id": "mauritius_export",
                "name": "Mauritius snapshot",
                "status": "warning",
                "message": "No file for today or yesterday",
                "fix": f"Run: python main.py --date {d} --skip-difc",
            }
        )

    # UK pipeline snapshot
    uk_pipe = pipeline_export_path(d)
    uk_stats = uk_pipeline_export_stats(d)
    if uk_stats.get("exists") and uk_stats.get("row_count", 0) > 0:
        mtime = _mtime_iso(uk_pipe)
        checks.append(
            {
                "id": "uk_export",
                "name": "UK snapshot",
                "status": "ok",
                "message": f"{uk_stats['row_count']} UK rows — {uk_pipe.name}",
                "mtime": mtime,
                "ago": _ago_label(mtime),
            }
        )
    else:
        checks.append(
            {
                "id": "uk_export",
                "name": "UK snapshot",
                "status": "warning",
                "message": f"No UK rows in exports/{d}.csv",
                "fix": f"Run: python main.py --date {d} --skip-difc",
            }
        )

    # DIFC / Gibraltar placeholders
    for jid, label in (("difc", "DIFC"), ("gibraltar", "Gibraltar")):
        checks.append(
            {
                "id": jid,
                "name": label,
                "status": "pending",
                "message": "Pending — no source configured",
            }
        )

    # OpenAI (optional — AI brief only)
    oai = openai_key_status()
    if oai["configured"]:
        checks.append({"id": "openai", "name": "OpenAI", "status": "ok", "message": "API key configured"})
    elif oai.get("reason") == "placeholder":
        checks.append(
            {
                "id": "openai",
                "name": "OpenAI",
                "status": "warning",
                "message": "OPENAI_API_KEY looks like a placeholder (optional)",
            }
        )
    else:
        checks.append(
            {
                "id": "openai",
                "name": "OpenAI",
                "status": "warning",
                "message": "OPENAI_API_KEY not set (optional)",
            }
        )

    # Latest prepared snapshot file
    export_candidates = sorted(Path("exports").glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if export_candidates:
        latest = export_candidates[0]
        mtime = _mtime_iso(latest)
        checks.append(
            {
                "id": "last_pipeline",
                "name": "Last pipeline run",
                "status": "ok",
                "message": latest.name,
                "mtime": mtime,
                "ago": _ago_label(mtime),
            }
        )

    # Total leads today
    total = 0
    if mu_file:
        total += mauritius_export_stats(
            d if mu_path.exists() else yesterday
        ).get("gbc_ac", 0)
    if uk_pipe.exists():
        total += uk_stats.get("row_count", 0) or _count_csv_rows(uk_pipe)
    checks.append(
        {
            "id": "total_leads",
            "name": "Total leads in snapshot (UK + MU GBC/AC)",
            "status": "ok" if total else "warning",
            "message": str(total),
        }
    )

    return {
        "checked_at": checked_at,
        "target_date": d,
        "checks": checks,
        "last_run": last_run_for_health(),
    }
