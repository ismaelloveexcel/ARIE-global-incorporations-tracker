"""
Arie Incorporation Monitor — stakeholder demo web app.

Run: python -m app.main
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
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
    load_csv,
)
from uk_leads.enrichment import compute_metrics, enrich_rows

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Arie Incorporation Monitor", version="0.2.0")


class AssignmentUpdate(BaseModel):
    assigned_to: str | None = None
    notes: str | None = None
    status: str | None = None
    contacted_at: str | None = None
    follow_up_at: str | None = None


def _lead_company_numbers(incorporation_date: str | None = None) -> set[str]:
    d = incorporation_date or (date.today() - timedelta(days=1)).isoformat()
    numbers: set[str] = set()
    for demo in (True, False):
        path = csv_path_for_date(d, demo=demo)
        if not path.exists():
            continue
        for row in load_csv(path):
            num = row.get("company_number")
            if num:
                numbers.add(str(num))
    return numbers


def _find_lead(company_number: str, incorporation_date: str | None = None) -> dict | None:
    d = incorporation_date or (date.today() - timedelta(days=1)).isoformat()
    for demo in (True, False):
        path = csv_path_for_date(d, demo=demo)
        if not path.exists():
            continue
        for row in load_csv(path):
            if row.get("company_number") == company_number:
                return row
    return None


def _package_response(
    rows: list[dict],
    incorporation_date: str,
    demo: bool,
    source_file: str,
    total_fetched: int | None = None,
    last_refreshed: str | None = None,
) -> dict:
    rows = assignments.merge_into_rows(rows)
    rows = enrich_rows(rows)
    metrics = compute_metrics(rows)
    return {
        "incorporation_date": incorporation_date,
        "demo": demo,
        "count": len(rows),
        "total_fetched": total_fetched,
        "source_file": source_file,
        "last_refreshed": last_refreshed,
        "metrics": metrics,
        "leads": rows,
    }


@app.get("/api/meta")
def api_meta():
    return {
        "team": TEAM_MEMBERS,
        "brand": "Arie Finance",
        "positioning": (
            "UK Companies House monitoring is operational using official API data. "
            "Mauritius API onboarding is underway. Additional jurisdictions will be "
            "added only when reliable official access exists."
        ),
        "jurisdictions": [
            {"code": "UK", "name": "United Kingdom", "status": "live", "source": "Companies House API"},
            {"code": "MU", "name": "Mauritius", "status": "pending", "source": "MNS APIMall (access in progress)"},
            {"code": "DIFC", "name": "UAE / DIFC", "status": "planned", "source": "Access method under evaluation"},
            {"code": "GI", "name": "Gibraltar", "status": "planned", "source": "Manual / future"},
        ],
        "has_api_key": bool(os.environ.get("COMPANIES_HOUSE_API_KEY")),
        "has_openai_key": bool(os.environ.get("OPENAI_API_KEY")),
        "workflow_statuses": assignments.WORKFLOW_STATUSES,
        "priority_thresholds": {"high": 70, "medium": 40},
    }


@app.get("/api/leads")
def api_leads(incorporation_date: str | None = None, demo: bool = True):
    d = incorporation_date or (date.today() - timedelta(days=1)).isoformat()
    path = csv_path_for_date(d, demo=demo)
    rows = load_csv(path)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No data for {d}. Click Refresh to fetch from Companies House.",
        )
    last = refresh_meta.get_last_refresh(d, demo)
    if not last and path.exists():
        last = datetime_from_mtime(path)
    return _package_response(rows, d, demo, str(path), last_refreshed=last)


@app.post("/api/refresh")
def api_refresh(incorporation_date: str | None = None, demo: bool = True):
    if not os.environ.get("COMPANIES_HOUSE_API_KEY"):
        raise HTTPException(status_code=503, detail="COMPANIES_HOUSE_API_KEY not set in .env")

    d = incorporation_date or (date.today() - timedelta(days=1)).isoformat()
    min_score = DEMO_MIN_SCORE if demo else None
    top = DEMO_TOP if demo else None

    rows, total = fetch_uk_leads(d, d, min_score=min_score, top=top)
    path = csv_path_for_date(d, demo=demo)
    export_csv(rows, path)
    refreshed = refresh_meta.record_refresh(d, demo, total, len(rows))

    return _package_response(
        rows, d, demo, str(path), total_fetched=total, last_refreshed=refreshed
    )


@app.patch("/api/leads/{company_number}")
def api_update_lead(company_number: str, body: AssignmentUpdate):
    entry = assignments.set_assignment(
        company_number,
        assigned_to=body.assigned_to,
        notes=body.notes,
        status=body.status,
        contacted_at=body.contacted_at,
        follow_up_at=body.follow_up_at,
    )
    return {"company_number": company_number, **entry}


@app.get("/api/leads/{company_number}/people")
def api_lead_people(company_number: str, incorporation_date: str | None = None):
    if not os.environ.get("COMPANIES_HOUSE_API_KEY"):
        raise HTTPException(status_code=503, detail="COMPANIES_HOUSE_API_KEY not set")
    from uk_leads.companies_house_people import fetch_people
    from uk_leads.signals import compute_signals

    lead_numbers = _lead_company_numbers(incorporation_date)
    try:
        people = fetch_people(company_number, lead_company_numbers=lead_numbers)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Companies House error: {exc}") from exc

    lead = _find_lead(company_number, incorporation_date)
    if lead:
        sig = compute_signals(
            lead,
            officer_count=len(people.get("officers") or []),
            director_signals=people.get("director_signals"),
        )
        people["strengths"] = sig["strengths"]
        people["cautions"] = sig["cautions"]
    return people


@app.post("/api/leads/{company_number}/brief")
def api_generate_brief(company_number: str, incorporation_date: str | None = None):
    if not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not set in .env")

    from uk_leads.brief import generate_brief, save_brief
    from uk_leads.companies_house_people import fetch_people
    from uk_leads.signals import compute_signals

    lead = _find_lead(company_number, incorporation_date)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not in loaded dataset. Refresh data first.")

    enriched = enrich_rows([lead])[0]
    lead = enriched

    people = None
    if os.environ.get("COMPANIES_HOUSE_API_KEY"):
        try:
            people = fetch_people(
                company_number,
                lead_company_numbers=_lead_company_numbers(incorporation_date),
            )
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
        save_brief(company_number, brief)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"company_number": company_number, "brief": brief, "lead": lead}


@app.get("/api/leads/{company_number}/brief")
def api_get_brief(company_number: str):
    from uk_leads.brief import load_brief

    brief = load_brief(company_number)
    if not brief:
        raise HTTPException(status_code=404, detail="No brief generated yet.")
    return {"company_number": company_number, "brief": brief}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")


def datetime_from_mtime(path: Path) -> str:
    from datetime import datetime, timezone

    mtime = path.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8080, reload=True)


if __name__ == "__main__":
    main()
