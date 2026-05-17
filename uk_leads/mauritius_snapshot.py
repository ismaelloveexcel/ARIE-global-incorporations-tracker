"""Fetch Mauritius MNS data for one date and merge into exports/<date>.csv."""
from __future__ import annotations

import csv
import logging
import os
from pathlib import Path

import connectors.mauritius as mns_connector
import scoring.engine as scorer
from normalization.schema import CompanyRecord
from uk_leads.data_loader import mauritius_export_stats, pipeline_export_path
from uk_leads import refresh_meta

logger = logging.getLogger(__name__)

_PIPELINE_FIELDS = [
    "company_name",
    "normalized_name",
    "jurisdiction",
    "entity_type",
    "incorporation_date",
    "score",
    "source",
    "canonical_entity_id",
    "company_number",
    "file_no",
    "sic_codes",
]


def mauritius_auto_refresh_enabled() -> bool:
    return os.environ.get("MAURITIUS_AUTO_REFRESH", "true").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def pipeline_has_mauritius_rows(run_date: str) -> bool:
    path = pipeline_export_path(run_date)
    if not path.exists():
        return False
    with path.open(encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            if (raw.get("source") or "").strip().lower() == "mauritius_mns":
                return True
    return False


def should_auto_fetch_mauritius(run_date: str) -> bool:
    if not mauritius_auto_refresh_enabled():
        return False
    if pipeline_has_mauritius_rows(run_date):
        return False
    if refresh_meta.mauritius_refresh_attempted(run_date):
        return False
    return True


def _record_to_csv_row(record: CompanyRecord) -> dict:
    raw = record.raw_data or {}
    if record.source == "mauritius_mns":
        return {
            "company_name": record.company_name,
            "normalized_name": record.normalized_name or "",
            "jurisdiction": record.jurisdiction,
            "entity_type": record.entity_type or "",
            "incorporation_date": record.incorporation_date or "",
            "score": record.score if record.score is not None else "",
            "source": record.source,
            "canonical_entity_id": record.canonical_entity_id or "",
            "company_number": "",
            "file_no": raw.get("file_no", ""),
            "sic_codes": "",
        }
    return {
        "company_name": record.company_name,
        "normalized_name": record.normalized_name or "",
        "jurisdiction": record.jurisdiction,
        "entity_type": record.entity_type or "",
        "incorporation_date": record.incorporation_date or "",
        "score": record.score if record.score is not None else "",
        "source": record.source,
        "canonical_entity_id": record.canonical_entity_id or "",
        "company_number": raw.get("company_number", ""),
        "file_no": "",
        "sic_codes": "|".join(str(s) for s in (raw.get("sic_codes") or []) or []),
    }


def _read_preserved_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    preserved: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            if (raw.get("source") or "").strip().lower() == "mauritius_mns":
                continue
            preserved.append({k: raw.get(k, "") for k in _PIPELINE_FIELDS})
    return preserved


def refresh_mauritius_for_date(run_date: str) -> dict:
    """
    Scrape Mauritius GBC/AC for *run_date*, score, and merge into exports/<run_date>.csv.
    Preserves non-Mauritius rows already in that file (e.g. from a full pipeline run).
    """
    logger.info("Mauritius snapshot refresh for %s", run_date)
    outcome = "OK"
    error_message: str | None = None
    records: list[CompanyRecord] = []

    try:
        records = mns_connector.fetch_new_incorporations(
            date_from=run_date, date_to=run_date
        )
    except Exception as exc:
        outcome = "ERROR"
        error_message = str(exc)
        logger.exception("Mauritius fetch failed for %s", run_date)

    if outcome == "OK":
        for record in records:
            record.score = scorer.score(record)

    path = pipeline_export_path(run_date)
    preserved = _read_preserved_rows(path)
    mu_rows = [_record_to_csv_row(r) for r in records] if outcome == "OK" else []

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_PIPELINE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in preserved + mu_rows:
            writer.writerow({k: row.get(k, "") for k in _PIPELINE_FIELDS})

    stats = mauritius_export_stats(run_date)
    refresh_meta.record_mauritius_refresh(
        run_date,
        exported=len(mu_rows),
        outcome=outcome,
        error_message=error_message,
    )

    return {
        "date": run_date,
        "outcome": outcome,
        "error_message": error_message,
        "mauritius_fetched": len(records),
        "mauritius_exported": len(mu_rows),
        "mauritius_gbc_ac": stats.get("gbc_ac", 0),
        "path": str(path),
    }
