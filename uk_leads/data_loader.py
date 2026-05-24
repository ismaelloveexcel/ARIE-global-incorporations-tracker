"""Load and merge UK + Mauritius rows from the canonical pipeline export."""
from __future__ import annotations

import csv
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from uk_leads import refresh_meta
from uk_leads.dashboard import MU_VERIFY_URL, is_mauritius_includable, lead_id
from uk_leads.enrichment import enrich_row
from uk_leads.freshness import evaluate_freshness
from uk_leads.run_summary import load_run_summary
from uk_leads.snapshot_registry import resolve_snapshot_path

logger = logging.getLogger(__name__)

PIPELINE_EXPORT = Path("exports") / "{date}.csv"
EXTERNAL_INTRODUCERS_PATH = Path("uk_leads") / "sources" / "external_introducers.csv"
_EXTERNAL_INTRODUCERS_FALLBACK_PATH = Path("data") / "introducers" / "external_introducers.csv"
CH_PROFILE_BASE = "https://find-and-update.company-information.service.gov.uk/company/"


def pipeline_export_path(date: str) -> Path:
    return resolve_snapshot_path(date)


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


def _db_source_enabled() -> bool:
    return os.environ.get("LEAD_SOURCE", "csv").strip().lower() == "db"


def _db_row_to_lead(row: dict) -> dict:
    """Map a DB company row to the lead shape expected by the frontend."""
    source = (row.get("source") or "").strip().lower()
    raw = row.get("raw_data") or {}
    if not isinstance(raw, dict):
        raw = {}

    sic_codes = raw.get("sic_codes") or []
    if isinstance(sic_codes, str):
        sic_codes_value = sic_codes.replace("|", ", ")
    else:
        sic_codes_value = ", ".join(str(code) for code in sic_codes if str(code).strip())

    incorporation_date = row.get("incorporation_date")
    run_date = str(incorporation_date or "")
    company_number = str(raw.get("company_number") or "").strip()
    file_no = str(raw.get("file_no") or "").strip()

    lead = {
        "run_date": run_date,
        "company_name": str(row.get("company_name") or "").strip(),
        "normalized_name": str(row.get("normalized_name") or "").strip(),
        "jurisdiction": str(row.get("jurisdiction") or "").strip(),
        "entity_type": str(row.get("entity_type") or "").strip(),
        "incorporation_date": run_date,
        "score": _parse_score(row.get("score")),
        "source": source,
        "assigned_to": "",
        "notes": "",
        "status": "Not contacted",
        "company_number": company_number,
        "file_no": file_no,
        "sic_codes": sic_codes_value,
        "verify_url": "",
        "lead_id": "",
    }

    if source == "companies_house" and company_number:
        lead["verify_url"] = f"{CH_PROFILE_BASE}{company_number}"
    elif source == "mauritius_mns":
        lead["verify_url"] = MU_VERIFY_URL

    lead["lead_id"] = lead_id(lead)
    return lead


def _fetch_db_leads_for_date(incorporation_date: str) -> list[dict]:
    from db.postgres_client import _with_pg_cursor

    with _with_pg_cursor() as cur:
        cur.execute(
            """
            SELECT
                company_name,
                normalized_name,
                jurisdiction,
                entity_type,
                incorporation_date,
                score,
                source,
                raw_data
            FROM companies
            WHERE incorporation_date = %s
            ORDER BY score DESC NULLS LAST, created_at DESC
            """,
            (incorporation_date,),
        )
        return [dict(row) for row in cur.fetchall()]


def _fetch_db_available_dates() -> list[str]:
    from db.postgres_client import _with_pg_cursor

    with _with_pg_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT incorporation_date
            FROM companies
            WHERE incorporation_date IS NOT NULL
            ORDER BY incorporation_date DESC
            """
        )
        rows = cur.fetchall()
    return [str(row.get("incorporation_date")) for row in rows if row.get("incorporation_date")]


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


def _normalize_name(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def load_external_introducers() -> list[dict]:
    """Load curated external introducer rows from tracked source CSV."""
    path = EXTERNAL_INTRODUCERS_PATH
    if not path.exists() and _EXTERNAL_INTRODUCERS_FALLBACK_PATH.exists():
        path = _EXTERNAL_INTRODUCERS_FALLBACK_PATH
    if not path.exists():
        return []

    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            name = (raw.get("company_name") or "").strip()
            if not name:
                continue

            source = (raw.get("source") or "external_introducer").strip().lower()
            row = {
                "run_date": "",
                "company_name": name,
                "normalized_name": (raw.get("normalized_name") or _normalize_name(name)).strip(),
                "jurisdiction": (raw.get("jurisdiction") or "").strip(),
                "entity_type": (raw.get("entity_type") or "").strip(),
                "incorporation_date": (raw.get("incorporation_date") or "").strip(),
                "score": _parse_score(raw.get("score")),
                "source": source,
                "assigned_to": "",
                "notes": (raw.get("notes") or "").strip(),
                "sic_codes": (raw.get("sic_codes") or "").strip(),
                "company_number": (raw.get("company_number") or "").strip(),
                "file_no": (raw.get("file_no") or "").strip(),
                "verify_url": (raw.get("verify_url") or "").strip(),
                "contact_email": (raw.get("contact_email") or "").strip(),
                "phone_number": (raw.get("phone_number") or "").strip(),
                "contact_name": (raw.get("contact_name") or "").strip(),
            }
            rows.append(row)

    logger.info("Loaded %d external introducer rows from %s", len(rows), path)
    return rows


def merge_leads_for_date(incorporation_date: str) -> tuple[list[dict], dict]:
    """Load and merge leads for the given date using DB or CSV based on LEAD_SOURCE."""
    if _db_source_enabled():
        return _merge_leads_from_db(incorporation_date)
    return _merge_leads_from_csv(incorporation_date)


def _merge_leads_from_db(incorporation_date: str) -> tuple[list[dict], dict]:
    rows = _fetch_db_leads_for_date(incorporation_date)
    leads = [_db_row_to_lead(row) for row in rows]

    merged: list[dict] = []
    by_lead_id: dict[str, dict] = {}
    duplicate_counts: dict[str, int] = {}

    for row in leads:
        enriched = enrich_row(dict(row))
        if enriched.get("source") == "mauritius_mns":
            enriched["verify_url"] = MU_VERIFY_URL
            if not (enriched.get("company_number") or "").strip():
                enriched["company_number"] = ""
        lid = lead_id(enriched)
        enriched["lead_id"] = lid
        if lid in by_lead_id:
            duplicate_counts[lid] = duplicate_counts.get(lid, 1) + 1
            continue
        by_lead_id[lid] = enriched
        merged.append(enriched)

    for row in merged:
        lid = row.get("lead_id") or ""
        group_size = max(1, duplicate_counts.get(lid, 1))
        row["duplicate_group_size"] = group_size
        row["duplicate_suppressed_count"] = max(0, group_size - 1)

    meta = {
        "source": "db",
        "date": incorporation_date,
        "count": len(merged),
        "pipeline_export_missing": False,
        "mauritius_export_missing": False,
        "warnings": [],
        "duplicates_suppressed": sum(max(0, c - 1) for c in duplicate_counts.values()),
    }
    return merged, meta


def _merge_leads_from_csv(date: str) -> tuple[list[dict], dict]:
    """Merge UK + Mauritius rows from exports/{date}.csv (canonical pipeline snapshot)."""
    pipeline_path = pipeline_export_path(date)
    meta: dict = {
        "pipeline_path": str(pipeline_path),
        "uk_path": str(pipeline_path),
        "mauritius_path": str(pipeline_path),
        "uk_count": 0,
        "mauritius_count": 0,
        "external_introducer_count": 0,
        "external_introducer_path": str(EXTERNAL_INTRODUCERS_PATH),
        "warnings": [],
        "duplicates_suppressed": 0,
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

    external_rows = load_external_introducers()
    meta["external_introducer_count"] = len(external_rows)
    meta["external_introducer_exists"] = (
        EXTERNAL_INTRODUCERS_PATH.exists() or _EXTERNAL_INTRODUCERS_FALLBACK_PATH.exists()
    )
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
    by_lead_id: dict[str, dict] = {}
    duplicate_counts: dict[str, int] = {}

    for row in uk_rows + mu_rows + external_rows:
        base = dict(row)
        enriched = enrich_row(base)
        if enriched.get("source") == "mauritius_mns":
            enriched["verify_url"] = MU_VERIFY_URL
            if not (enriched.get("company_number") or "").strip():
                enriched["company_number"] = ""
        lid = lead_id(enriched)
        enriched["lead_id"] = lid
        if lid in by_lead_id:
            duplicate_counts[lid] = duplicate_counts.get(lid, 1) + 1
            meta["duplicates_suppressed"] += 1
            continue
        by_lead_id[lid] = enriched
        merged.append(enriched)

    for row in merged:
        lid = row.get("lead_id") or ""
        group_size = max(1, duplicate_counts.get(lid, 1))
        row["duplicate_group_size"] = group_size
        row["duplicate_suppressed_count"] = max(0, group_size - 1)

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


def _has_snapshot_files(date: str) -> bool:
    return pipeline_export_path(date).exists()


def _mtime_iso(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _summary_for_scan(target_date: str) -> dict | None:
    summary = load_run_summary()
    if not summary:
        return None
    if summary.get("run_date") != target_date:
        return None
    return {
        "pipeline_outcome": summary.get("pipeline_outcome"),
        "notes": summary.get("notes"),
        "run_date": summary.get("run_date"),
        "matches_selected_date": True,
        "connectors": summary.get("connectors") or {},
        "run_timestamp": summary.get("run_timestamp"),
    }


def _has_archived_history(target_date: str) -> bool:
    archive_dir = Path("exports") / "archive" / target_date
    if not archive_dir.exists():
        return False
    return any(archive_dir.glob("archived-*.csv"))


def _date_counts_for_scan(target_date: str) -> dict:
    path = pipeline_export_path(target_date)
    uk_stats = uk_pipeline_export_stats(target_date)
    uk_count = uk_stats.get("row_count", 0)
    mu_stats = mauritius_export_stats(target_date)
    has_snapshot = path.exists()
    has_uk = uk_count > 0
    has_mauritius = mu_stats.get("gbc_ac", 0) > 0
    summary = _summary_for_scan(target_date)
    publication_timestamp = _mtime_iso(path)
    freshness = evaluate_freshness(
        target=target_date,
        is_today=target_date == date.today().isoformat(),
        uk={
            # If snapshot file exists, we still treat timeline coverage as available even on quiet days.
            "exists": has_snapshot,
            "file_modified": publication_timestamp,
        },
        mauritius={
            "exists": has_mauritius,
            "file_modified": publication_timestamp if has_mauritius else None,
        },
        summary=summary,
        now=datetime.now(timezone.utc),
    )
    confidence = freshness.get("operational_confidence") or {}
    return {
        "date": target_date,
        "uk_count": uk_count,
        "mauritius_count": mu_stats.get("gbc_ac", 0),
        "has_uk": has_uk,
        "has_mauritius": has_mauritius,
        "has_data": has_uk or has_mauritius,
        "has_snapshot": has_snapshot,
        "quiet_day": has_snapshot and not (has_uk or has_mauritius),
        "publication_timestamp": publication_timestamp,
        "freshness_state": freshness.get("state"),
        "confidence_level": confidence.get("level"),
        "fallback_active": bool(confidence.get("fallback_active")),
        "archive_available": _has_archived_history(target_date),
        "mauritius_export_exists": mu_stats.get("exists", False),
    }


def scan_available_dates(lookback_days: int | None = None) -> dict:
    """Return available dates. Uses DB or filesystem based on LEAD_SOURCE env var."""
    import os

    if os.environ.get("LEAD_SOURCE", "csv").strip().lower() == "db":
        from db.postgres_client import fetch_available_dates

        dates = fetch_available_dates()
        today = date.today()
        lookback = 30
        calendar = [
            (today - timedelta(days=i)).isoformat()
            for i in range(lookback)
        ]
        date_details = []
        for d in calendar:
            has = d in dates
            date_details.append({
                "date": d,
                "uk_count": 0,
                "mauritius_count": 0,
                "has_uk": has,
                "has_mauritius": False,
                "has_data": has,
                "has_snapshot": has,
                "quiet_day": False,
                "publication_timestamp": None,
                "freshness_state": "ok" if has else "missing",
                "confidence_level": "high" if has else "low",
                "fallback_active": False,
                "archive_available": False,
                "mauritius_export_exists": False,
            })
        recommended = dates[0] if dates else (today - timedelta(days=1)).isoformat()
        return {
            "dates": dates,
            "calendar_dates": calendar,
            "snapshot_dates": dates,
            "date_details": date_details,
            "recommended": recommended,
            "lookback_days": lookback,
            "reason": "Most recent day with DB data",
            "can_fetch_uk": bool(os.environ.get("COMPANIES_HOUSE_API_KEY")),
            "can_fetch_mauritius": bool(os.environ.get("MAURITIUS_AUTO_REFRESH", "")),
        }

    lookback = lookback_days if lookback_days is not None else default_nav_lookback_days()
    discovered = _discover_export_dates()
    refreshed = set(refresh_meta.list_refreshed_dates())
    navigable = sorted(
        set(_calendar_nav_dates(lookback)) | discovered | refreshed,
        reverse=True,
    )

    if not navigable:
        return {
            "dates": [],
            "calendar_dates": [],
            "snapshot_dates": [],
            "date_details": [],
            "recommended": None,
            "lookback_days": lookback,
            "reason": "No dates in navigation window",
        }

    date_details = [_date_counts_for_scan(d) for d in navigable]
    snapshot_dates = [d["date"] for d in date_details if d["has_snapshot"]]
    dates_with_data = [d["date"] for d in date_details if d["has_data"]]
    # Operator UI: only days with a pipeline export — not the full calendar padding.
    operator_dates = snapshot_dates if snapshot_dates else dates_with_data

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
        "dates": operator_dates,
        "calendar_dates": navigable,
        "snapshot_dates": snapshot_dates,
        "date_details": [d for d in date_details if d["date"] in set(operator_dates)]
        if operator_dates
        else date_details,
        "recommended": recommended,
        "lookback_days": lookback,
        "reason": reason,
    }
