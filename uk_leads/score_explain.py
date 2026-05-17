"""Human-readable score breakdown for dashboard leads."""
from __future__ import annotations

from typing import Any

from normalization.schema import CompanyRecord
from scoring.engine import (
    _entity_type_score,
    _jurisdiction_score,
    _keyword_score,
    _sic_score,
    score,
)

from uk_leads.enrichment import priority_from_score


def _row_to_record(row: dict[str, Any]) -> CompanyRecord:
    raw: dict[str, Any] = {}
    jurisdiction = (row.get("jurisdiction") or "UK").strip()
    sic = row.get("sic_codes") or ""
    if jurisdiction == "UK" and sic and sic != "—":
        raw["sic_codes"] = [s.strip() for s in str(sic).split(",") if s.strip()]

    return CompanyRecord(
        company_name=row.get("company_name") or "",
        jurisdiction=jurisdiction,
        source=row.get("source") or "",
        entity_type=row.get("entity_type"),
        incorporation_date=row.get("incorporation_date"),
        raw_data=raw,
    )


def build_score_breakdown(row: dict[str, Any]) -> dict[str, Any]:
    """Return score total, priority, and component lines for the UI."""
    record = _row_to_record(row)
    entity = round(_entity_type_score(record), 1)
    juris = round(_jurisdiction_score(record), 1)
    sic = round(_sic_score(record), 1)
    keywords = round(_keyword_score(record), 1)
    total = float(score(record))

    components = [
        {
            "key": "entity_type",
            "label": "Entity type",
            "points": entity,
            "max": 40,
            "detail": (record.entity_type or "Unknown type").strip() or "Not specified",
        },
        {
            "key": "jurisdiction",
            "label": "Jurisdiction",
            "points": juris,
            "max": 20,
            "detail": record.jurisdiction or "—",
        },
        {
            "key": "sic",
            "label": "Industry (SIC)",
            "points": sic,
            "max": 20,
            "detail": "UK financial SIC codes only"
            if record.jurisdiction == "UK"
            else "Not used outside UK",
        },
        {
            "key": "keywords",
            "label": "Name signals",
            "points": keywords,
            "max": 20,
            "detail": "Fintech, payments, capital, fund, etc. in company name",
        },
    ]

    return {
        "total": total,
        "priority": priority_from_score(total),
        "components": components,
        "summary": (
            "Fit for Arie client onboarding (payments, international structures, GBC/AC). "
            "Not a credit rating — use with registry verification."
        ),
    }
