"""
Arie Onboarding Intelligence Platform web app.

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
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from uk_leads import assignments, refresh_meta
from uk_leads.app_mode import is_production, mode_config, operator_refresh_allowed
from uk_leads.env_config import companies_house_key_status, openai_key_status
from uk_leads.core import TEAM_MEMBERS
from uk_leads.uk_snapshot import refresh_uk_for_date
from uk_leads.dashboard import filter_tab_leads, lead_id
from uk_leads.data_loader import merge_leads_for_date, pipeline_export_path, scan_available_dates
from uk_leads.mauritius_snapshot import (
    mauritius_auto_refresh_enabled,
    refresh_mauritius_for_date,
    should_auto_fetch_mauritius,
)
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

_AUTH_SCHEME = "Bearer"

app = FastAPI(title="Arie Onboarding Intelligence Platform", version="1.0.0")

_OPERATOR_REFRESH_DETAIL = (
    "In-app registry fetch is disabled in production. "
    "Use prepared overnight snapshots or /dev for engineering pipeline runs."
)


def _guard_operator_refresh() -> None:
    if not operator_refresh_allowed():
        detail = (
            "Register data is prepared overnight. Try another date or contact operations."
            if is_production()
            else _OPERATOR_REFRESH_DETAIL
        )
        raise HTTPException(status_code=403, detail=detail)


def _latest_operational_date() -> str | None:
    payload = scan_available_dates()
    recommended = payload.get("recommended")
    if isinstance(recommended, str) and recommended.strip():
        return recommended
    dates = payload.get("dates") or []
    if dates:
        return str(dates[0])
    return None


def _nearest_operational_date(target_date: str) -> str | None:
    payload = scan_available_dates()
    dates = [d for d in (payload.get("dates") or []) if isinstance(d, str) and d]
    if not dates:
        return None
    if target_date in dates:
        return target_date
    for d in dates:
        if d < target_date:
            return d
    return dates[-1]


def _guard_dev_only() -> None:
    if is_production():
        raise HTTPException(status_code=404, detail="Not found")


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


def _read_token() -> str:
    return os.environ.get("ARIE_API_READ_TOKEN", "").strip()


def _write_token() -> str:
    return os.environ.get("ARIE_API_WRITE_TOKEN", "").strip()


def _auth_enabled() -> bool:
    return bool(_read_token() or _write_token())


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != _AUTH_SCHEME.lower() or not value.strip():
        return ""
    return value.strip()


def require_api_read(authorization: str | None = Header(default=None)) -> None:
    if not _auth_enabled():
        return
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    read = _read_token()
    write = _write_token()
    if read and secrets.compare_digest(token, read):
        return
    if write and secrets.compare_digest(token, write):
        return
    raise HTTPException(status_code=403, detail="Invalid API token")


def require_api_write(authorization: str | None = Header(default=None)) -> None:
    if not _auth_enabled():
        return
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    write = _write_token()
    if write and secrets.compare_digest(token, write):
        return
    raise HTTPException(status_code=403, detail="Write token required")


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


def _load_merged_rows(incorporation_date: str) -> tuple[list[dict], dict]:
    rows, meta = merge_leads_for_date(incorporation_date)
    config = load_config()
    pools = config.get("assignment_pools", assignments.DEFAULT_POOLS)
    rows = assignments.merge_saved_fields(rows, pools=pools)
    return rows, meta


def _find_lead(lead_id_key: str, incorporation_date: str | None = None) -> dict | None:
    d = incorporation_date or _latest_operational_date() or (date.today() - timedelta(days=1)).isoformat()
    rows, _ = _load_merged_rows(d)
    for row in rows:
        if row.get("lead_id") == lead_id_key or row.get("company_number") == lead_id_key:
            return row
    return None


def _normalize_tab(tab: str | None) -> str:
    """Normalize dashboard queue tab."""
    if tab in (None, "", "direct_clients"):
        return "direct_clients"
    if tab == "introducers":
        return "introducers"
    return "direct_clients"


def _package_response(
    rows: list[dict],
    tab: str | None,
    incorporation_date: str,
    meta: dict,
    last_refreshed: str | None = None,
    total_fetched: int | None = None,
) -> dict:
    queue_tab = _normalize_tab(tab)
    rows = filter_tab_leads(rows, queue_tab)

    return {
        "incorporation_date": incorporation_date,
        "tab": queue_tab,
        "count": len(rows),
        "total_fetched": total_fetched,
        "last_refreshed": last_refreshed,
        "metrics": compute_tab_metrics(rows),
        "leads": rows,
        "meta": meta,
        "team": TEAM_MEMBERS,
    }


@app.get("/api/available-dates", dependencies=[Depends(require_api_read)])
def api_available_dates():
    payload = scan_available_dates()
    payload["can_fetch_uk"] = bool(os.environ.get("COMPANIES_HOUSE_API_KEY"))
    payload["can_fetch_mauritius"] = mauritius_auto_refresh_enabled()
    return payload


def _maybe_auto_refresh_mauritius(incorporation_date: str) -> dict | None:
    if not should_auto_fetch_mauritius(incorporation_date):
        return None
    return refresh_mauritius_for_date(incorporation_date)


@app.get("/api/data-status", dependencies=[Depends(require_api_read)])
def api_data_status(
    target_date: str | None = Query(None, alias="date"),
):
    d = target_date or _latest_operational_date() or (date.today()).isoformat()
    try:
        date.fromisoformat(d)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date; use YYYY-MM-DD") from exc
    return get_data_status(d)


@app.get("/api/meta", dependencies=[Depends(require_api_read)])
def api_meta():
    config = load_config()
    return {
        "team": TEAM_MEMBERS,
        "assignment_pools": config.get("assignment_pools"),
        "brand": "Arie Finance",
        "positioning": (
            "Daily onboarding intelligence and relationship intelligence — UK Companies House "
            "and Mauritius GBC/AC. Operational queues support both registration candidates "
            "and introducer opportunities."
        ),
        "has_api_key": companies_house_key_status()["configured"],
        "has_openai_key": openai_key_status()["configured"],
        "companies_house_key": companies_house_key_status(),
        "openai_key": openai_key_status(),
        "workflow_statuses": assignments.WORKFLOW_STATUSES,
        "priority_thresholds": {"high": 70, "medium": 40},
        **mode_config(),
        "canonical_pipeline_queue": True,
    }


@app.get("/api/leads", dependencies=[Depends(require_api_read)])
def api_leads(
    target_date: str | None = Query(None, alias="date"),
    incorporation_date: str | None = None,
    tab: str | None = Query(
        None,
        description="Queue tab: direct_clients (default) or introducers.",
    ),
):
    d = incorporation_date or target_date or _latest_operational_date() or (date.today() - timedelta(days=1)).isoformat()
    rows, meta = _load_merged_rows(d)

    if not rows and not pipeline_export_path(d).exists():
        fallback = _nearest_operational_date(d)
        if fallback and fallback != d:
            fallback_rows, fallback_meta = _load_merged_rows(fallback)
            if fallback_rows or pipeline_export_path(fallback).exists():
                fallback_meta.setdefault("fallback", {})
                fallback_meta["fallback"].update(
                    {
                        "requested_date": d,
                        "resolved_date": fallback,
                        "reason": "nearest_available_operational_date",
                    }
                )
                fallback_last = refresh_meta.get_last_refresh(fallback)
                fallback_pipe = pipeline_export_path(fallback)
                if not fallback_last and fallback_pipe.exists():
                    fallback_last = datetime_from_mtime(fallback_pipe)
                return _package_response(
                    fallback_rows,
                    tab,
                    fallback,
                    fallback_meta,
                    last_refreshed=fallback_last,
                )
        detail = (
            f"No validated operational data is available for {d} yet. "
            "Try another date or contact operations."
        )
        raise HTTPException(status_code=404, detail=detail)

    last = refresh_meta.get_last_refresh(d)
    pipe = pipeline_export_path(d)
    if not last and pipe.exists():
        last = datetime_from_mtime(pipe)

    return _package_response(rows, tab, d, meta, last_refreshed=last)


@app.post("/api/refresh", dependencies=[Depends(require_api_write)])
def api_refresh(
    incorporation_date: str | None = None,
    tab: str | None = Query(None),
):
    _guard_operator_refresh()
    if not companies_house_key_status()["configured"]:
        raise HTTPException(
            status_code=503,
            detail="COMPANIES_HOUSE_API_KEY not configured — set a real key in .env",
        )

    d = incorporation_date or (date.today() - timedelta(days=1)).isoformat()
    uk_result = refresh_uk_for_date(d)
    total = uk_result["total_fetched"]
    refreshed = uk_result["refreshed_at"]

    mauritius_result = _maybe_auto_refresh_mauritius(d)

    rows, meta = _load_merged_rows(d)
    if mauritius_result:
        meta["mauritius_refresh"] = mauritius_result
    meta["uk_refresh"] = uk_result
    return _package_response(
        rows, tab, d, meta, total_fetched=total, last_refreshed=refreshed
    )


@app.post("/api/refresh/mauritius", dependencies=[Depends(require_api_write)])
def api_refresh_mauritius(
    incorporation_date: str | None = None,
    tab: str | None = Query(None),
):
    _guard_operator_refresh()
    d = incorporation_date or (date.today() - timedelta(days=1)).isoformat()
    try:
        date.fromisoformat(d)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date; use YYYY-MM-DD") from exc

    if not mauritius_auto_refresh_enabled():
        raise HTTPException(
            status_code=503,
            detail="Mauritius auto-fetch is disabled (MAURITIUS_AUTO_REFRESH=false).",
        )

    try:
        result = refresh_mauritius_for_date(d)
    except Exception as exc:
        logger.exception("Mauritius refresh failed for %s", d)
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if result.get("outcome") == "ERROR":
        raise HTTPException(
            status_code=503,
            detail=result.get("error_message") or "Mauritius register fetch failed",
        )

    rows, meta = _load_merged_rows(d)
    meta["mauritius_refresh"] = result
    last = refresh_meta.get_last_mauritius_refresh(d) or datetime_from_mtime(
        pipeline_export_path(d)
    )
    return _package_response(rows, tab, d, meta, last_refreshed=last)


@app.patch("/api/leads/{lead_id_key}", dependencies=[Depends(require_api_write)])
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


@app.get("/api/leads/{lead_id_key}/people", dependencies=[Depends(require_api_read)])
def api_lead_people(
    lead_id_key: str,
    incorporation_date: str | None = None,
    refresh: bool = Query(False, description="Bypass cache and refetch from Companies House"),
):
    lead = _find_lead(lead_id_key, incorporation_date)
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


@app.post("/api/leads/{lead_id_key}/brief", dependencies=[Depends(require_api_write)])
def api_generate_brief(lead_id_key: str, incorporation_date: str | None = None):
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not set in .env")

    from uk_leads.brief import generate_brief, save_brief
    from uk_leads.companies_house_people import fetch_people
    from uk_leads.signals import compute_signals

    lead = _find_lead(lead_id_key, incorporation_date)
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


@app.get("/api/leads/{lead_id_key}/brief", dependencies=[Depends(require_api_read)])
def api_get_brief(lead_id_key: str):
    from uk_leads.brief import load_brief

    brief = load_brief(lead_id_key)
    if not brief:
        raise HTTPException(status_code=404, detail="No brief generated yet.")
    return {"lead_id": lead_id_key, "brief": brief}


@app.get("/dev")
def dev_page():
    _guard_dev_only()
    return FileResponse(STATIC / "dev.html")


@app.get("/api/dev/health")
def api_dev_health(incorporation_date: str | None = None):
    _guard_dev_only()
    return run_health_checks(incorporation_date)


@app.get("/api/dev/config", dependencies=[Depends(require_api_read)])
def api_dev_config_get():
    _guard_dev_only()
    return load_config()


@app.post("/api/dev/config", dependencies=[Depends(require_api_write)])
def api_dev_config_post(body: DevConfigUpdate):
    _guard_dev_only()
    config = load_config()
    if body.assignment_pools is not None:
        config["assignment_pools"] = body.assignment_pools
    if body.roadmap is not None:
        config["roadmap"] = body.roadmap
    if body.implementation_log is not None:
        config["implementation_log"] = body.implementation_log
    return save_config(config)


@app.post("/api/dev/refresh/uk", dependencies=[Depends(require_api_write)])
def api_dev_refresh_uk(incorporation_date: str | None = None):
    _guard_dev_only()
    return api_refresh(incorporation_date=incorporation_date)


@app.post("/api/dev/refresh/mauritius", dependencies=[Depends(require_api_write)])
def api_dev_refresh_mauritius(incorporation_date: str | None = None):
    _guard_dev_only()
    d = incorporation_date or date.today().isoformat()
    try:
        result = refresh_mauritius_for_date(d)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"date": d, "success": result.get("outcome") == "OK", **result}


@app.get("/api/dev/pipeline-alerts", dependencies=[Depends(require_api_read)])
def api_dev_pipeline_alerts():
    _guard_dev_only()
    return get_pipeline_alert_status()


@app.get("/api/dev/stats", dependencies=[Depends(require_api_read)])
def api_dev_stats(incorporation_date: str | None = None):
    _guard_dev_only()
    d = incorporation_date or (date.today() - timedelta(days=1)).isoformat()
    rows, _ = _load_merged_rows(d)
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
    from app.page_html import render_index_html

    return HTMLResponse(render_index_html())


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def datetime_from_mtime(path: Path) -> str:
    mtime = path.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8080, reload=True)


if __name__ == "__main__":
    main()
