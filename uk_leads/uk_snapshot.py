"""Fetch UK Companies House data for one date and merge into exports/<date>.csv."""
from __future__ import annotations

import csv
import logging

from uk_leads import refresh_meta
from uk_leads.core import fetch_uk_leads
from uk_leads.data_loader import pipeline_export_path, uk_pipeline_export_stats
from uk_leads.mauritius_snapshot import _PIPELINE_FIELDS

logger = logging.getLogger(__name__)


def _sic_to_pipeline(sic_codes: str) -> str:
    parts = [s.strip() for s in (sic_codes or "").replace("|", ",").split(",") if s.strip()]
    return "|".join(parts)


def _uk_row_to_pipeline(row: dict) -> dict:
    return {
        "company_name": (row.get("company_name") or "").strip(),
        "normalized_name": "",
        "jurisdiction": (row.get("jurisdiction") or "UK").strip(),
        "entity_type": (row.get("entity_type") or "ltd").strip(),
        "incorporation_date": (row.get("incorporation_date") or "").strip(),
        "score": row.get("score", ""),
        "source": "companies_house",
        "canonical_entity_id": (row.get("company_number") or "").strip(),
        "company_number": (row.get("company_number") or "").strip(),
        "file_no": "",
        "sic_codes": _sic_to_pipeline(row.get("sic_codes") or ""),
    }


def _read_preserved_mauritius_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    preserved: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            if (raw.get("source") or "").strip().lower() != "mauritius_mns":
                continue
            preserved.append({k: raw.get(k, "") for k in _PIPELINE_FIELDS})
    return preserved


def refresh_uk_for_date(
    run_date: str,
    *,
    min_score: float | None = None,
    top: int | None = None,
) -> dict:
    """
    Fetch UK incorporations for *run_date*, score/enrich, and merge into exports/<run_date>.csv.
    Preserves Mauritius rows already in that file.
    """
    logger.info("UK snapshot refresh for %s", run_date)
    uk_rows, total_fetched = fetch_uk_leads(
        run_date, run_date, min_score=min_score, top=top
    )
    pipeline_rows = [_uk_row_to_pipeline(r) for r in uk_rows]

    path = pipeline_export_path(run_date)
    preserved = _read_preserved_mauritius_rows(path)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_PIPELINE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in pipeline_rows + preserved:
            writer.writerow({k: row.get(k, "") for k in _PIPELINE_FIELDS})

    refreshed = refresh_meta.record_refresh(
        run_date, total_fetched=total_fetched, exported=len(pipeline_rows)
    )
    stats = uk_pipeline_export_stats(run_date)

    return {
        "date": run_date,
        "path": str(path),
        "total_fetched": total_fetched,
        "uk_exported": len(pipeline_rows),
        "uk_pipeline_rows": stats.get("row_count", 0),
        "refreshed_at": refreshed,
    }
