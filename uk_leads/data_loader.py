"""Load and merge UK + Mauritius rows from the canonical pipeline export."""
from __future__ import annotations

import csv
import logging
import os
import re
from datetime import date, timedelta
from pathlib import Path

from uk_leads import refresh_meta
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
        num = (row.get("company_number") or row.get("canonical_entity_id") or "").strip()
        if num:
            base["company_number"] = str(num)
        base["sic_codes"] = (row.get("sic_codes") or "").strip().replace("|", ", ")
        base["entity_type"] = base["entity_type"] or "ltd"
        base["jurisdiction"] = base["jurisdiction"] or "UK"
        if base["company_number"]:
            base["verify_url"] = f"{CH_PROFILE_BASE}{base['company_number']}"
    elif source == "mauritius_mns":
        base["jurisdiction"] = base["jurisdiction"] or "Mauritius"
        base["verify_url"] = MU_VERIFY_URL

    return base


def _is_uk_pipeline_row(raw: dict[str, str]) -> bool:
    source = (raw.get("source") or "").strip().lower()
    if source == "companies_house":
        return True
    return (raw.get("jurisdiction") or "").strip() == "UK"


def uk_pipeline_export_stats(date: str) -> dict:
    """Count UK rows in the canonical pipeline export."""
    path = pipeline_export_path(date)
    if not path.exists():
        return {
            "exists": False,
            "path": str(path),
            "row_count": 0,
        }

    count = 0
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            if _is_uk_pipeline_row(raw):
                count += 1

    return {
        "exists": True,
        "path": str(path),
        "row_count": count,
    }


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


def load_uk_from_pipeline(date: str) -> list[dict]:
    path = pipeline_export_path(date)
    if not path.exists():
        logger.warning("Pipeline export not found for UK rows: %s", path)
        return []

    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            if not _is_uk_pipeline_row(raw):
                continue
            rows.append(pipeline_row_to_lead(raw, run_date=date))

    logger.info("Loaded %d UK rows from %s", len(rows), path)
    return rows


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


def merge_leads_for_date(date: str, demo: bool = True) -> tuple[list[dict], dict]:
    """
    Merge UK + Mauritius rows from exports/{date}.csv (canonical pipeline snapshot).

    The *demo* parameter is retained for API compatibility; merge source is always the
    pipeline export file, not uk-leads-* snapshot files.
    """
    _ = demo
    pipeline_path = pipeline_export_path(date)
    meta: dict = {
        "pipeline_path": str(pipeline_path),
        "uk_path": str(pipeline_path),
        "mauritius_path": str(pipeline_path),
        "uk_count": 0,
        "mauritius_count": 0,
        "warnings": [],
    }

    uk_stats = uk_pipeline_export_stats(date)
    meta["uk_pipeline_export_exists"] = uk_stats["exists"]
    meta["uk_pipeline_export_stats"] = uk_stats

    uk_rows = load_uk_from_pipeline(date)
    meta["uk_count"] = len(uk_rows)

    mu_stats = mauritius_export_stats(date)
    meta["mauritius_export_exists"] = mu_stats["exists"]
    meta["mauritius_export_stats"] = mu_stats

    mu_rows = load_mauritius_from_pipeline(date)
    meta["mauritius_count"] = len(mu_rows)
    if not pipeline_path.exists():
        meta["warnings"].append(f"No pipeline export for {date}")
        meta["pipeline_export_missing"] = True
    else:
        meta["pipeline_export_missing"] = False
    if not mu_stats["exists"] or mu_stats.get("gbc_ac", 0) == 0:
        meta["warnings"].append(f"No Mauritius GBC/AC rows in pipeline export for {date}")
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


_PIPELINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.csv$")


def default_nav_lookback_days() -> int:
    raw = os.environ.get("SNAPSHOT_NAV_DAYS", "30").strip()
    try:
        return max(1, min(366, int(raw)))
    except ValueError:
        return 30


def _discover_export_dates() -> set[str]:
    exports = Path("exports")
    if not exports.is_dir():
        return set()

    discovered: set[str] = set()
    for path in exports.iterdir():
        if not path.is_file() or path.suffix.lower() != ".csv":
            continue
        name = path.name
        m = _PIPELINE_RE.match(name)
        if m:
            discovered.add(m.group(1))
    return discovered


def _calendar_nav_dates(lookback_days: int) -> list[str]:
    """Incorporation dates for the nav window (newest first), ending at yesterday."""
    end = date.today() - timedelta(days=1)
    return [(end - timedelta(days=i)).isoformat() for i in range(lookback_days)]


def _has_snapshot_files(date: str, demo: bool) -> bool:
    _ = demo
    return pipeline_export_path(date).exists()


def _date_counts_for_scan(date: str, demo: bool) -> dict:
    _ = demo
    uk_stats = uk_pipeline_export_stats(date)
    uk_count = uk_stats.get("row_count", 0)
    mu_stats = mauritius_export_stats(date)
    has_snapshot = _has_snapshot_files(date, demo=False)
    has_uk = uk_count > 0
    has_mauritius = mu_stats.get("gbc_ac", 0) > 0
    return {
        "date": date,
        "uk_count": uk_count,
        "mauritius_count": mu_stats.get("gbc_ac", 0),
        "has_uk": has_uk,
        "has_mauritius": has_mauritius,
        "has_data": has_uk or has_mauritius,
        "has_snapshot": has_snapshot,
        "mauritius_export_exists": mu_stats.get("exists", False),
    }


def scan_available_dates(demo: bool = True, lookback_days: int | None = None) -> dict:
    """
    Dates the user can navigate to: rolling calendar window + any export/refresh files.
    Returns navigable dates (newest first), per-date counts, and recommended default.
    """
    lookback = lookback_days if lookback_days is not None else default_nav_lookback_days()
    discovered = _discover_export_dates()
    refreshed = set(refresh_meta.list_refreshed_dates(demo=demo))
    navigable = sorted(
        set(_calendar_nav_dates(lookback)) | discovered | refreshed,
        reverse=True,
    )

    if not navigable:
        return {
            "dates": [],
            "snapshot_dates": [],
            "date_details": [],
            "recommended": None,
            "lookback_days": lookback,
            "reason": "No dates in navigation window",
        }

    date_details = [_date_counts_for_scan(d, demo=demo) for d in navigable]
    snapshot_dates = [d["date"] for d in date_details if d["has_snapshot"]]
    dates_with_data = [d["date"] for d in date_details if d["has_data"]]

    both = [d for d in date_details if d["has_uk"] and d["has_mauritius"]]
    if both:
        recommended = both[0]["date"]
        reason = "Most recent date with UK + Mauritius data"
    elif dates_with_data:
        recommended = dates_with_data[0]
        reason = "Most recent date with saved lead data"
    elif snapshot_dates:
        recommended = snapshot_dates[0]
        reason = "Most recent saved pipeline snapshot"
    else:
        recommended = navigable[0]
        reason = "Most recent day in the navigation window"

    return {
        "dates": navigable,
        "snapshot_dates": snapshot_dates,
        "date_details": date_details,
        "recommended": recommended,
        "lookback_days": lookback,
        "reason": reason,
    }
