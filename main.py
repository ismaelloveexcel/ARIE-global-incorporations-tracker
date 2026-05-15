"""
main.py  —  Incorporation Intelligence Engine: core pipeline runner
════════════════════════════════════════════════════════════════════

Execution flow
──────────────
1. Ingest records from all connectors (Companies House, DIFC, Mauritius)
2. Score each record using the scoring engine
3. Run deduplication: resolve/create canonical entity ids
4. Write all records + canonical entities to Supabase
5. Export a CSV snapshot to exports/YYYY-MM-DD.csv

CLI usage
─────────
    python main.py                          # runs for yesterday (lookback=1)
    python main.py --date 2024-06-01        # single specific date
    python main.py --lookback 7             # last 7 days
    python main.py --skip-difc              # skip DIFC scraper
    python main.py --skip-mauritius         # skip Mauritius scraper
    python main.py --dry-run               # parse + score, no DB writes
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ─── logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("pipeline")

# ─── internal modules ─────────────────────────────────────────────────────────
import connectors.companies_house as ch_connector
import connectors.difc as difc_connector
import connectors.mauritius as mns_connector
import db.supabase_client as db
import scoring.engine as scorer
from deduplication.matcher import Deduplicator
from normalization.schema import CompanyRecord

# ─────────────────────────────────────────────────────────────────────────────
# Ingest
# ─────────────────────────────────────────────────────────────────────────────

def ingest(
    date_from: str,
    date_to: str,
    skip_difc: bool = False,
    skip_mauritius: bool = False,
) -> list[CompanyRecord]:
    """Run all connectors and return the combined list of records."""
    records: list[CompanyRecord] = []

    # 1. Companies House (UK)
    logger.info("── Companies House connector ──────────────────────────")
    try:
        ch_records = ch_connector.fetch_new_incorporations(
            date_from=date_from,
            date_to=date_to,
        )
        logger.info("Companies House: %d records ingested.", len(ch_records))
        records.extend(ch_records)
    except Exception as exc:
        logger.error("Companies House connector failed: %s", exc)

    # 2. DIFC (Playwright)
    if not skip_difc:
        logger.info("── DIFC connector ─────────────────────────────────────")
        try:
            difc_records = difc_connector.fetch_new_incorporations(date_from=date_from)
            logger.info("DIFC: %d records ingested.", len(difc_records))
            records.extend(difc_records)
        except Exception as exc:
            logger.error("DIFC connector failed: %s", exc)
    else:
        logger.info("DIFC connector skipped.")

    # 3. Mauritius MNS (Playwright, date range on onlinesearch.mns.mu)
    if not skip_mauritius:
        logger.info("── Mauritius MNS connector ────────────────────────────")
        try:
            mns_records = mns_connector.fetch_new_incorporations(
                date_from=date_from,
                date_to=date_to,
            )
            logger.info("Mauritius MNS: %d records ingested.", len(mns_records))
            records.extend(mns_records)
        except Exception as exc:
            logger.error("Mauritius MNS connector failed: %s", exc)
    else:
        logger.info("Mauritius MNS connector skipped.")

    return records


# ─────────────────────────────────────────────────────────────────────────────
# Score
# ─────────────────────────────────────────────────────────────────────────────

def score_records(records: list[CompanyRecord]) -> None:
    """Mutate each record in-place by computing its score."""
    for record in records:
        record.score = scorer.score(record)


# ─────────────────────────────────────────────────────────────────────────────
# Deduplicate
# ─────────────────────────────────────────────────────────────────────────────

def deduplicate(records: list[CompanyRecord]) -> None:
    """
    Resolve each record to a canonical entity id.

    Loads existing companies from Supabase, then for each new record
    either finds a fuzzy match or creates a new canonical entity.
    Mutates records in-place.
    """
    dedup = Deduplicator()
    existing = db.fetch_all_companies()
    dedup.load_existing(existing)

    for record in records:
        record.canonical_entity_id = dedup.resolve(record, db)


# ─────────────────────────────────────────────────────────────────────────────
# Persist
# ─────────────────────────────────────────────────────────────────────────────

def persist(records: list[CompanyRecord]) -> list[dict]:
    """
    Write records to Supabase.
    Returns the list of inserted DB rows (with auto-generated ids).
    """
    inserted: list[dict] = []
    for record in records:
        try:
            row = db.insert_company(record.to_db_dict())
            inserted.append(row)
        except Exception as exc:
            logger.error(
                "Failed to insert company '%s': %s", record.company_name, exc
            )
    logger.info("Persisted %d / %d records to Supabase.", len(inserted), len(records))
    return inserted


# ─────────────────────────────────────────────────────────────────────────────
# CSV export
# ─────────────────────────────────────────────────────────────────────────────

_CSV_FIELDS = [
    "company_name",
    "normalized_name",
    "jurisdiction",
    "entity_type",
    "incorporation_date",
    "score",
    "source",
    "canonical_entity_id",
]


def export_csv(records: list[CompanyRecord], run_date: str) -> Path:
    """
    Write a CSV snapshot to exports/<run_date>.csv.
    Returns the path to the created file.
    """
    exports_dir = Path("exports")
    exports_dir.mkdir(parents=True, exist_ok=True)
    filepath = exports_dir / f"{run_date}.csv"

    with filepath.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_db_dict())

    logger.info("CSV snapshot written to %s (%d rows).", filepath, len(records))
    return filepath


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline orchestrator
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(
    date_from: str,
    date_to: str,
    skip_difc: bool = False,
    skip_mauritius: bool = False,
    dry_run: bool = False,
) -> list[CompanyRecord]:
    """
    Full pipeline: ingest → score → deduplicate → persist → export.

    Returns the list of processed CompanyRecord objects.
    """
    logger.info(
        "Pipeline started  [%s → %s] dry_run=%s", date_from, date_to, dry_run
    )

    # 1. Ingest
    records = ingest(
        date_from=date_from,
        date_to=date_to,
        skip_difc=skip_difc,
        skip_mauritius=skip_mauritius,
    )
    logger.info("Total records ingested: %d", len(records))

    if not records:
        logger.info("No records to process.  Pipeline complete.")
        return records

    # 2. Score
    score_records(records)
    scored = [r for r in records if r.score is not None]
    if scored:
        logger.info(
            "Scoring complete.  Score range: %.1f – %.1f",
            min(r.score for r in scored),
            max(r.score for r in scored),
        )

    if not dry_run:
        # 3. Deduplicate (requires DB access)
        deduplicate(records)

        # 4. Persist
        persist(records)

    # 5. Export CSV (always, even in dry-run mode)
    export_csv(records, run_date=date_to)

    logger.info("Pipeline complete.  %d records processed.", len(records))
    return records


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Incorporation Intelligence Engine – daily pipeline runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help=(
            "Specific date to process (sets both date_from and date_to). "
            "Overrides --lookback."
        ),
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=int(os.environ.get("LOOKBACK_DAYS", 1)),
        help="Number of days back to fetch (used when --date is not set).",
    )
    parser.add_argument(
        "--skip-difc",
        action="store_true",
        help="Skip the DIFC Playwright scraper.",
    )
    parser.add_argument(
        "--skip-mauritius",
        action="store_true",
        help="Skip the Mauritius MNS Playwright scraper.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Ingest and score only; skip DB writes.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.date:
        date_from = args.date
        date_to = args.date
    else:
        today = date.today()
        date_to = (today - timedelta(days=1)).isoformat()
        date_from = (today - timedelta(days=args.lookback)).isoformat()

    run_pipeline(
        date_from=date_from,
        date_to=date_to,
        skip_difc=args.skip_difc,
        skip_mauritius=args.skip_mauritius,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
