"""
Arie Incorporation Monitor — Phase 1 web app.

Run: python -m app.main
User view: /  (daily incorporation queue)
Ops view:    /dev  (not linked from user UI)
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from uk_leads import assignments, refresh_meta
from uk_leads.core import (
    DEMO_MIN_SCORE,
    DEMO_TOP,
    TEAM_MEMBERS,
    csv_path_for_date,
    export_csv,
    fetch_uk_leads,
)
from uk_leads.dashboard import filter_tab_leads, lead_id
from uk_leads.data_loader import merge_leads_for_date, pipeline_export_path, scan_available_dates
from uk_leads.dev_config import load_config, save_config
from uk_leads.enrichment import enrich_rows
from uk_leads.health import run_health_checks
from uk_leads.data_status import get_data_status
from uk_leads.pipeline_alerts import get_pipeline_alert_status

STATIC = Path(__file__).parent / "static"

logger = logging.getLogger(__name__)

# In-memory TTL cache for Companies House people data (per lead_id)
_people_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL_SECONDS = 3600

_PEOPLE_UNAVAILABLE_MESSAGE = (
    "Director data could not be retrieved at this time. Try again shortly."
)
_MU_PEOPLE_MESSAGE = (
    "Director and PSC data is not yet available for Mauritius companies. "
    "This will be added when MNS API access is confirmed."
)

app = FastAPI(title="Arie Incorporation Monitor", version="1.0.0")


def _get_cached_people(lead_id: str) -> dict | None:
    if lead_id not in _people_cache:
        return None
    timestamp, data = _people_cache[lead_id]
    if time.time() - timestamp > _CACHE_TTL_SECONDS:
        del _people_cache[lead_id]
        return None
    return data


def _set_cached_people(lead_id: str, data: dict) -> None:
    _people_cache[lead_id] = (time.time(), data)


class AssignmentUpdate(BaseModel):
    assigned_to: str | None = None
    notes: str | None = None
    status: str | None = None
    contacted_at: str | None = None
    follow_up_at: str | None = None


class DevConfigUpdate(BaseModel):
    assignment_pools: dict[str, list[str]] | None = None
    roadmap: list[dict] | None = None
    implementation_log: dict | None = None


def _jurisdiction_counts(rows: list[dict]) -> tuple[int, int]:
    uk = 0
    mu = 0
    for r in rows:
        source = (r.get("source") or "").strip().lower()
        jurisdiction = (r.get("jurisdiction") or "").strip()
        if source == "mauritius_mns" or jurisdiction == "Mauritius":
            mu += 1
        else:
            uk += 1
    return uk, mu


def compute_tab_metrics(rows: list[dict]) -> dict:
    total = len(rows)
    high = sum(1 for r in rows if float(r.get("score") or 0) >= 70)
    assigned = sum(1 for r in rows if (r.get("assigned_to") or "").strip())
    uk_count, mauritius_count = _jurisdiction_counts(rows)
    return {
        "total_leads": total,
        "high_priority": high,
        "assigned_count": assigned,
        "unassigned_count": max(0, total - assigned),
        "uk_count": uk_count,
        "mauritius_count": mauritius_count,
    }


def _load_merged_rows(incorporation_date: str, demo: bool) -> tuple[list[dict], dict]:
    rows, meta = merge_leads_for_date(incorporation_date, demo=demo)
    config = load_config()
    pools = config.get("assignment_pools", assignments.DEFAULT_POOLS)
    rows = assignments.apply_assignments(rows, pools=pools)
    return rows, meta


def _find_lead(lead_id_key: str, incorporation_date: str | None = None, demo: bool = True) -> dict | None:
    d = incorporation_date or (date.today() - timedelta(days=1)).isoformat()
    rows, _ = _load_merged_rows(d, demo=demo)
    for row in rows:
        if row.get("lead_id") == lead_id_key or row.get("company_number") == lead_id_key:
            return row
    return None


def _normalize_tab(tab: str | None) -> str:
    """Operator UI uses direct_clients only; introducers tab is deprecated (empty list)."""
    if tab in (None, "", "direct_clients"):
        return "direct_clients"
    if tab == "introducers":
        return "introducers"
    return "direct_clients"


def _package_response(
    rows: list[dict],
    tab: str | None,
    incorporation_date: str,
    demo: bool,
    meta: dict,
    last_refreshed: str | None = None,
    total_fetched: int | None = None,
) -> dict:
    queue_tab = _normalize_tab(tab)
    rows = filter_tab_leads(rows, queue_tab)

    return {
        "incorporation_date": incorporation_date,
        "demo": demo,
        "tab": queue_tab,
        "count": len(rows),
        "total_fetched": total_fetched,
        "last_refreshed": last_refreshed,
        "metrics": compute_tab_metrics(rows),
        "leads": rows,
        "meta": meta,
        "team": TEAM_MEMBERS,
    }


@app.get("/api/available-dates")
def api_available_dates(demo: bool = True):
    return scan_available_dates(demo=demo)


@app.get("/api/data-status")
def api_data_status(
    target_date: str | None = Query(None, alias="date"),
    demo: bool = True,
):
    d = target_date or (date.today()).isoformat()
    try:
        date.fromisoformat(d)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date; use YYYY-MM-DD") from exc
    return get_data_status(d, demo=demo)


@app.get("/api/meta")
def api_meta():
    config = load_config()
    return {
        "team": TEAM_MEMBERS,
        "assignment_pools": config.get("assignment_pools"),
        "brand": "Arie Finance",
        "positioning": (
            "Daily onboarding intelligence — UK Companies House and Mauritius GBC/AC. "
            "One work queue for client onboarding; introducer relationships tracked manually."
        ),
        "has_api_key": bool(os.environ.get("COMPANIES_HOUSE_API_KEY")),
        "has_openai_key": bool(os.environ.get("OPENAI_API_KEY")),
        "workflow_statuses": assignments.WORKFLOW_STATUSES,
        "priority_thresholds": {"high": 70, "medium": 40},
    }


@app.get("/api/leads")
def api_leads(
    incorporation_date: str | None = None,
    demo: bool = True,
    tab: str | None = Query(
        None,
        description="Queue tab: direct_clients (default). introducers is deprecated and returns an empty list.",
    ),
):
    d = incorporation_date or (date.today() - timedelta(days=1)).isoformat()
    rows, meta = _load_merged_rows(d, demo=demo)

    if not rows and not Path(csv_path_for_date(d, demo=demo)).exists():
        raise HTTPException(
            status_code=404,
            detail=f"No data for {d}. Refresh UK leads or run the Mauritius pipeline.",
        )

    last = refresh_meta.get_last_refresh(d, demo)
    uk_path = csv_path_for_date(d, demo=demo)
    if not last and uk_path.exists():
        last = datetime_from_mtime(uk_path)
    if not last:
        mu_path = pipeline_export_path(d)
        if mu_path.exists():
            last = datetime_from_mtime(mu_path)

    return _package_response(rows, tab, d, demo, meta, last_refreshed=last)


@app.post("/api/refresh")
def api_refresh(
    incorporation_date: str | None = None,
    demo: bool = True,
    tab: str | None = Query(None),
):
    if not os.environ.get("COMPANIES_HOUSE_API_KEY"):
        raise HTTPException(status_code=503, detail="COMPANIES_HOUSE_API_KEY not set in .env")

    d = incorporation_date or (date.today() - timedelta(days=1)).isoformat()
    min_score = DEMO_MIN_SCORE if demo else None
    top = DEMO_TOP if demo else None

    uk_rows, total = fetch_uk_leads(d, d, min_score=min_score, top=top)
    path = csv_path_for_date(d, demo=demo)
    export_csv(uk_rows, path)
    refreshed = refresh_meta.record_refresh(d, demo, total, len(uk_rows))

    rows, meta = _load_merged_rows(d, demo=demo)
    return _package_response(
        rows, tab, d, demo, meta, total_fetched=total, last_refreshed=refreshed
    )


@app.patch("/api/leads/{lead_id_key}")
def api_update_lead(lead_id_key: str, body: AssignmentUpdate):
    try:
        entry = assignments.set_assignment(
            lead_id_key,
            assigned_to=body.assigned_to,
            notes=body.notes,
            status=body.status,
            contacted_at=body.contacted_at,
            follow_up_at=body.follow_up_at,
        )
    except assignments.AssignmentLockError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"lead_id": lead_id_key, **entry}


@app.get("/api/leads/{lead_id_key}/people")
def api_lead_people(
    lead_id_key: str,
    incorporation_date: str | None = None,
    demo: bool = True,
    refresh: bool = Query(False, description="Bypass cache and refetch from Companies House"),
):
    lead = _find_lead(lead_id_key, incorporation_date, demo=demo)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if (lead.get("source") or "").lower() != "companies_house":
        return {
            "officers": [],
            "psc": [],
            "strengths": lead.get("strengths", []),
            "cautions": lead.get("cautions", []),
            "source": "mauritius_mns",
            "enrichment_status": "not_available",
            "enrichment_message": _MU_PEOPLE_MESSAGE,
        }

    if not refresh:
        cached = _get_cached_people(lead_id_key)
        if cached:
            logger.debug(
                "People cache hit for %s — skipping API call",
                lead_id_key,
            )
            return cached

    if not os.environ.get("COMPANIES_HOUSE_API_KEY"):
        return {
            "officers": [],
            "psc": [],
            "strengths": lead.get("strengths", []),
            "cautions": lead.get("cautions", []),
            "source": "companies_house",
            "enrichment_status": "unavailable",
            "enrichment_message": _PEOPLE_UNAVAILABLE_MESSAGE,
        }

    from uk_leads.companies_house_people import fetch_people
    from uk_leads.signals import compute_signals

    num = lead.get("company_number") or lead_id_key
    people = fetch_people(num, lead_company_numbers={num})

    if people.get("enrichment_status") == "unavailable":
        return {
            "officers": [],
            "psc": [],
            "strengths": lead.get("strengths", []),
            "cautions": lead.get("cautions", []),
            "source": "companies_house",
            "enrichment_status": "unavailable",
            "enrichment_message": _PEOPLE_UNAVAILABLE_MESSAGE,
        }

    sig = compute_signals(
        lead,
        officer_count=len(people.get("officers") or []),
        director_signals=people.get("director_signals"),
    )
    result = {
        "company_number": people.get("company_number"),
        "officers": people.get("officers") or [],
        "psc": people.get("psc") or [],
        "strengths": sig["strengths"],
        "cautions": sig["cautions"],
        "source": "companies_house",
        "enrichment_status": "ok",
    }
    _set_cached_people(lead_id_key, result)
    return result


@app.post("/api/leads/{lead_id_key}/brief")
def api_generate_brief(lead_id_key: str, incorporation_date: str | None = None, demo: bool = True):
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not set in .env")

    from uk_leads.brief import generate_brief, save_brief
    from uk_leads.companies_house_people import fetch_people
    from uk_leads.signals import compute_signals

    lead = _find_lead(lead_id_key, incorporation_date, demo=demo)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not in loaded dataset.")

    lead = enrich_rows([lead])[0]
    people = None
    if (lead.get("source") or "").lower() == "companies_house" and os.environ.get("COMPANIES_HOUSE_API_KEY"):
        try:
            num = lead.get("company_number") or lead_id_key
            people = fetch_people(num, lead_company_numbers={num})
            sig = compute_signals(
                lead,
                officer_count=len(people.get("officers") or []),
                director_signals=people.get("director_signals"),
            )
            lead["strengths"] = sig["strengths"]
            lead["cautions"] = sig["cautions"]
        except Exception:
            people = None

    try:
        brief = generate_brief(lead, people)
        save_brief(lead_id_key, brief)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"lead_id": lead_id_key, "brief": brief, "lead": lead}


@app.get("/api/leads/{lead_id_key}/brief")
def api_get_brief(lead_id_key: str):
    from uk_leads.brief import load_brief

    brief = load_brief(lead_id_key)
    if not brief:
        raise HTTPException(status_code=404, detail="No brief generated yet.")
    return {"lead_id": lead_id_key, "brief": brief}


@app.get("/dev")
def dev_page():
    return FileResponse(STATIC / "dev.html")


@app.get("/api/dev/health")
def api_dev_health(incorporation_date: str | None = None):
    return run_health_checks(incorporation_date)


@app.get("/api/dev/config")
def api_dev_config_get():
    return load_config()


@app.post("/api/dev/config")
def api_dev_config_post(body: DevConfigUpdate):
    config = load_config()
    if body.assignment_pools is not None:
        config["assignment_pools"] = body.assignment_pools
    if body.roadmap is not None:
        config["roadmap"] = body.roadmap
    if body.implementation_log is not None:
        config["implementation_log"] = body.implementation_log
    return save_config(config)


@app.post("/api/dev/refresh/uk")
def api_dev_refresh_uk(incorporation_date: str | None = None, demo: bool = True):
    return api_refresh(incorporation_date=incorporation_date, demo=demo)


@app.post("/api/dev/refresh/mauritius")
def api_dev_refresh_mauritius(incorporation_date: str | None = None):
    d = incorporation_date or date.today().isoformat()
    cmd = [sys.executable, "main.py", "--date", d, "--skip-difc"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(Path.cwd()),
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Mauritius pipeline timed out after 5 minutes") from None

    return {
        "date": d,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "success": proc.returncode == 0,
    }


@app.get("/api/dev/pipeline-alerts")
def api_dev_pipeline_alerts():
    return get_pipeline_alert_status()


@app.get("/api/dev/stats")
def api_dev_stats(incorporation_date: str | None = None, demo: bool = True):
    d = incorporation_date or (date.today() - timedelta(days=1)).isoformat()
    rows, _ = _load_merged_rows(d, demo=demo)
    direct = filter_tab_leads(rows, "direct_clients")
    return {
        "date": d,
        "assignment_stats": assignments.assignment_stats(rows),
        "unassigned": sum(1 for r in rows if not (r.get("assigned_to") or "").strip()),
        "direct_clients_count": len(direct),
        "auto_introducer_queue_count": 0,
    }


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def datetime_from_mtime(path: Path) -> str:
    mtime = path.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8080, reload=True)


if __name__ == "__main__":
    main()
