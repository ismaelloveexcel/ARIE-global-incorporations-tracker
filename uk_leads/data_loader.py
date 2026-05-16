"""Load and merge UK web-app CSV rows with Mauritius pipeline exports."""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from uk_leads.core import csv_path_for_date, load_csv
from uk_leads.dashboard import MU_VERIFY_URL, is_mauritius_includable, lead_id
from uk_leads.enrichment import enrich_row

logger = logging.getLogger(__name__)

PIPELINE_EXPORT = Path("exports") / "{date}.csv"
CH_PROFILE_BASE = "https://find-and-update.company-information.service.gov.uk/company/"


def pipeline_export_path(date: str) -> Path:
    return Path("exports") / f"{date}.csv"


def _parse_score(value) -> float:
    try:
        return float(value) if value not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def pipeline_row_to_lead(row: dict[str, str], run_date: str) -> dict:
    source = (row.get("source") or "").strip().lower()
    base = {
        "run_date": run_date,
        "company_name": (row.get("company_name") or "").strip(),
        "normalized_name": (row.get("normalized_name") or "").strip(),
        "jurisdiction": (row.get("jurisdiction") or "").strip(),
        "entity_type": (row.get("entity_type") or "").strip(),
        "incorporation_date": (row.get("incorporation_date") or "").strip(),
        "score": _parse_score(row.get("score")),
        "source": source,
        "assigned_to": "",
        "notes": "",
        "sic_codes": "",
        "company_number": "",
        "file_no": (row.get("file_no") or "").strip(),
        "verify_url": "",
    }

    if source == "companies_house":
        num = (row.get("canonical_entity_id") or row.get("company_number") or "").strip()
        if num and str(num).isdigit():
            base["company_number"] = str(num)
        base["entity_type"] = base["entity_type"] or "ltd"
        base["jurisdiction"] = base["jurisdiction"] or "UK"
        if base["company_number"]:
            base["verify_url"] = f"{CH_PROFILE_BASE}{base['company_number']}"
    elif source == "mauritius_mns":
        base["jurisdiction"] = base["jurisdiction"] or "Mauritius"
        base["verify_url"] = MU_VERIFY_URL

    return base


def mauritius_export_stats(date: str) -> dict:
    """Count Mauritius rows in pipeline export: total, GBC/AC included, domestic excluded."""
    path = pipeline_export_path(date)
    if not path.exists():
        return {
            "exists": False,
            "path": str(path),
            "total": 0,
            "gbc_ac": 0,
            "domestic_excluded": 0,
        }

    total = 0
    gbc_ac = 0
    domestic = 0
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            if (raw.get("source") or "").strip().lower() != "mauritius_mns":
                continue
            total += 1
            lead = pipeline_row_to_lead(raw, run_date=date)
            if is_mauritius_includable(lead):
                gbc_ac += 1
            else:
                domestic += 1

    return {
        "exists": True,
        "path": str(path),
        "total": total,
        "gbc_ac": gbc_ac,
        "domestic_excluded": domestic,
    }


def load_mauritius_from_pipeline(date: str) -> list[dict]:
    path = pipeline_export_path(date)
    if not path.exists():
        logger.warning("Mauritius pipeline export not found: %s", path)
        return []

    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            source = (raw.get("source") or "").strip().lower()
            if source != "mauritius_mns":
                continue
            lead = pipeline_row_to_lead(raw, run_date=date)
            if not is_mauritius_includable(lead):
                continue
            rows.append(lead)

    logger.info("Loaded %d Mauritius GBC/AC rows from %s", len(rows), path)
    return rows


def load_uk_rows(date: str, demo: bool) -> list[dict]:
    path = csv_path_for_date(date, demo=demo)
    if not path.exists():
        return []
    return load_csv(path)


def merge_leads_for_date(date: str, demo: bool = True) -> tuple[list[dict], dict]:
    """
    Merge UK CSV + Mauritius pipeline export for *date*.
    Returns (enriched rows, meta dict with source paths and warnings).
    """
    meta: dict = {
        "uk_path": str(csv_path_for_date(date, demo=demo)),
        "mauritius_path": str(pipeline_export_path(date)),
        "uk_count": 0,
        "mauritius_count": 0,
        "warnings": [],
    }

    uk_rows = load_uk_rows(date, demo=demo)
    meta["uk_count"] = len(uk_rows)

    mu_stats = mauritius_export_stats(date)
    meta["mauritius_export_exists"] = mu_stats["exists"]
    meta["mauritius_export_stats"] = mu_stats

    mu_rows = load_mauritius_from_pipeline(date)
    meta["mauritius_count"] = len(mu_rows)
    if not mu_stats["exists"]:
        meta["warnings"].append(f"No Mauritius export for {date}")
        meta["mauritius_export_missing"] = True
    else:
        meta["mauritius_export_missing"] = False

    merged: list[dict] = []
    seen_ids: set[str] = set()

    for row in uk_rows + mu_rows:
        base = dict(row)
        enriched = enrich_row(base)
        if enriched.get("source") == "mauritius_mns":
            enriched["verify_url"] = MU_VERIFY_URL
            enriched["sic_codes"] = enriched.get("sic_codes") or "—"
        lid = lead_id(enriched)
        enriched["lead_id"] = lid
        enriched["company_number"] = enriched.get("company_number") or lid
        if lid in seen_ids:
            continue
        seen_ids.add(lid)
        merged.append(enriched)

    merged.sort(key=lambda r: float(r.get("score") or 0), reverse=True)
    return merged, meta
