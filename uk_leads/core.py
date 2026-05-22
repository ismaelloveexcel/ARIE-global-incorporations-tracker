"""Shared UK leads pipeline (CLI + web app)."""
from __future__ import annotations

import csv
from pathlib import Path

import connectors.companies_house as ch_connector
import scoring.engine as scorer
from normalization.schema import CompanyRecord
from uk_leads.enrichment import enrich_row, format_sic_codes

CH_PROFILE_BASE = "https://find-and-update.company-information.service.gov.uk/company/"

TEAM_MEMBERS = ["Aisha", "Stephen", "Rajesh", "Tasneem", "Ismael"]

CSV_FIELDS = [
    "run_date",
    "company_name",
    "company_number",
    "verify_url",
    "incorporation_date",
    "jurisdiction",
    "entity_type",
    "sic_codes",
    "score",
    "priority",
    "lead_type",
    "lead_type_reason",
    "assigned_to",
    "source",
    "contact_email",
    "linkedin_company",
    "phone_number",
    "notes",
]


def company_number_for(record: CompanyRecord) -> str:
    raw = record.raw_data or {}
    return str(raw.get("company_number") or "").strip()


def verify_url_for(record: CompanyRecord) -> str:
    num = company_number_for(record)
    if not num:
        return ""
    return f"{CH_PROFILE_BASE}{num}"


def score_records(records: list[CompanyRecord]) -> None:
    for record in records:
        record.score = scorer.score(record)


def filter_records(
    records: list[CompanyRecord],
    min_score: float | None,
    top: int | None,
) -> list[CompanyRecord]:
    out = records
    if min_score is not None:
        out = [r for r in out if r.score is not None and r.score >= min_score]
    out.sort(key=lambda r: r.score or 0.0, reverse=True)
    if top is not None and top > 0:
        out = out[:top]
    return out


def record_to_row(record: CompanyRecord, run_date: str) -> dict:
    base = {
        "run_date": run_date,
        "company_name": record.company_name,
        "company_number": company_number_for(record),
        "verify_url": verify_url_for(record),
        "incorporation_date": record.incorporation_date or "",
        "jurisdiction": record.jurisdiction,
        "entity_type": record.entity_type or "",
        "sic_codes": format_sic_codes(record.raw_data),
        "score": record.score,
        "assigned_to": "",
        "source": record.source,
        "notes": "",
        "contact_email": "",
        "linkedin_company": "",
        "phone_number": "",
    }
    return enrich_row(base, raw_data=record.raw_data)


def fetch_uk_leads(
    date_from: str,
    date_to: str,
    min_score: float | None = None,
    top: int | None = None,
) -> tuple[list[dict], int]:
    records = ch_connector.fetch_new_incorporations(
        date_from=date_from, date_to=date_to
    )
    total = len(records)
    if not records:
        return [], 0

    score_records(records)
    records = filter_records(records, min_score=min_score, top=top)
    rows = [record_to_row(r, run_date=date_to) for r in records]
    return rows, total


def export_csv(rows: list[dict], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})
    return output


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return [enrich_row(dict(r)) for r in rows]


