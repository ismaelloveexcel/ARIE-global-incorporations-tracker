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
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from dotenv import load_dotenv

load_dotenv()

# ─── logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("pipeline")

CONNECTOR_TIMEOUT_SECONDS = 120
RUN_SUMMARY_PATH = Path("exports") / "run_summary.json"
_CH_PROBE_URL = (
    "https://api.company-information.service.gov.uk/advanced-search/companies"
)

# ─── internal modules ─────────────────────────────────────────────────────────
import connectors.companies_house as ch_connector
import connectors.difc as difc_connector
import connectors.mauritius as mns_connector
import db.supabase_client as db
import scoring.engine as scorer
from deduplication.matcher import Deduplicator
from normalization.schema import CompanyRecord

# ─────────────────────────────────────────────────────────────────────────────
# Connector classification (Fix 2)
# ─────────────────────────────────────────────────────────────────────────────

def classify_connector_result(
    source: str,
    records: list[Any] | None,
    exception: BaseException | None,
    http_status: int | None,
    duration_seconds: float,
    run_date: str,
) -> tuple[str, str | None]:
    """
    Classify a connector run as ERROR, EMPTY, or OK.

    Returns (outcome, error_message).
    """
    _ = source, run_date

    if duration_seconds > CONNECTOR_TIMEOUT_SECONDS:
        return "ERROR", f"Connector timed out after {CONNECTOR_TIMEOUT_SECONDS}s"

    if exception is not None:
        if http_status is None and isinstance(exception, requests.HTTPError):
            resp = exception.response
            http_status = resp.status_code if resp is not None else None
        return "ERROR", str(exception)

    if records is None:
        return "ERROR", "Connector returned no result (internal failure)"

    if http_status == 401:
        return "ERROR", "API key invalid or expired"
    if http_status == 429:
        return "ERROR", "Rate limit hit"
    if http_status is not None and http_status >= 500:
        return "ERROR", f"Server error (HTTP {http_status})"

    if http_status is not None and http_status not in (200, None):
        if http_status >= 400:
            return "ERROR", f"HTTP {http_status}"

    if len(records) == 0:
        return "EMPTY", None

    return "OK", None


def _http_status_message(status: int) -> str:
    if status == 401:
        return "API key invalid or expired"
    if status == 429:
        return "Rate limit hit"
    if status >= 500:
        return f"Server error (HTTP {status})"
    return f"HTTP {status}"


def _probe_companies_house_http_status(date_from: str, date_to: str) -> int | None:
    """Single-page probe when CH returns zero rows (connector may swallow HTTP errors)."""
    api_key = os.environ.get("COMPANIES_HOUSE_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        resp = requests.get(
            _CH_PROBE_URL,
            auth=(api_key, ""),
            params={
                "incorporated_from": date_from,
                "incorporated_to": date_to,
                "size": 1,
                "start_index": 0,
            },
            timeout=30,
        )
        return resp.status_code
    except requests.RequestException:
        return None


def _run_connector_timed(fn, *args, **kwargs):
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn, *args, **kwargs)
        return future.result(timeout=CONNECTOR_TIMEOUT_SECONDS)


def _connector_entry(
    outcome: str,
    records: list[Any] | None,
    error_message: str | None,
    http_status: int | None,
    duration_seconds: float,
) -> dict:
    count = len(records) if records is not None else 0
    return {
        "outcome": outcome,
        "record_count": count,
        "error_message": error_message,
        "http_status": http_status,
        "duration_seconds": round(duration_seconds, 1),
    }


def _log_connector_outcome(
    source: str,
    outcome: str,
    error_message: str | None,
    record_count: int,
    run_date: str,
) -> None:
    if outcome == "ERROR":
        logger.error(
            "CONNECTOR ERROR [%s]: %s — this is NOT a quiet day, "
            "the connector failed. Check API key / site availability.",
            source,
            error_message or "unknown error",
        )
    elif outcome == "EMPTY":
        logger.info(
            "CONNECTOR EMPTY [%s]: 0 records — connector ran "
            "successfully, no GBC/AC incorporated on %s.",
            source,
            run_date,
        )
    else:
        logger.info("CONNECTOR OK [%s]: %d records returned.", source, record_count)


def compute_pipeline_outcome(connectors: dict[str, dict]) -> tuple[str, str]:
    if not connectors:
        return "FAILED", "No connectors ran."

    outcomes = [c["outcome"] for c in connectors.values()]
    has_ok = "OK" in outcomes
    has_empty = "EMPTY" in outcomes
    has_error = "ERROR" in outcomes

    if all(o == "ERROR" for o in outcomes):
        return "FAILED", "All connectors failed — check API keys and site availability."

    if has_error and (has_ok or has_empty):
        parts = []
        for name, c in connectors.items():
            label = "Companies House" if name == "companies_house" else "Mauritius MNS"
            if c["outcome"] == "OK":
                parts.append(f"{label}: OK ({c['record_count']} records)")
            elif c["outcome"] == "EMPTY":
                parts.append(f"{label}: quiet day (0 records)")
            elif c["outcome"] == "ERROR":
                parts.append(f"{label}: ERROR — {c.get('error_message') or 'failed'}")
        return "PARTIAL", "; ".join(parts)

    if all(o == "EMPTY" for o in outcomes):
        return (
            "ALL_EMPTY",
            "Both connectors ran successfully. UK: 0 · MU: 0 — genuine quiet day.",
        )

    notes_parts = []
    ch = connectors.get("companies_house")
    mu = connectors.get("mauritius_mns")
    if mu and mu.get("outcome") == "EMPTY":
        notes_parts.append("Mauritius returned 0 — genuine quiet day, no error")
    if ch and ch.get("outcome") == "EMPTY":
        notes_parts.append("Companies House returned 0 — genuine quiet day, no error")
    return "OK", notes_parts[0] if len(notes_parts) == 1 else "Pipeline completed successfully."


def write_run_summary(
    run_date: str,
    connectors: dict[str, dict],
    pipeline_outcome: str,
    notes: str,
    total_records: int,
) -> Path:
    RUN_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_date": run_date,
        "run_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "connectors": connectors,
        "total_records": total_records,
        "pipeline_outcome": pipeline_outcome,
        "notes": notes,
    }
    with RUN_SUMMARY_PATH.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    logger.info("Run summary written to %s", RUN_SUMMARY_PATH)
    return RUN_SUMMARY_PATH


def _ingest_companies_house(date_from: str, date_to: str, run_date: str) -> tuple[list[CompanyRecord], dict]:
    logger.info("── Companies House connector ──────────────────────────")
    exc: BaseException | None = None
    http_status: int | None = None
    records: list[CompanyRecord] | None = None
    started = time.perf_counter()

    try:
        records = _run_connector_timed(
            ch_connector.fetch_new_incorporations,
            date_from=date_from,
            date_to=date_to,
        )
    except FuturesTimeoutError:
        exc = TimeoutError(f"Timed out after {CONNECTOR_TIMEOUT_SECONDS}s")
    except requests.HTTPError as err:
        exc = err
        http_status = err.response.status_code if err.response is not None else None
    except Exception as err:
        exc = err

    duration = time.perf_counter() - started

    if records is not None and len(records) == 0 and exc is None:
        if not os.environ.get("COMPANIES_HOUSE_API_KEY", "").strip():
            http_status = http_status or 401
            exc = exc or RuntimeError("COMPANIES_HOUSE_API_KEY not set")
        else:
            probed = _probe_companies_house_http_status(date_from, date_to)
            if probed is not None:
                http_status = probed
                if probed != 200:
                    exc = RuntimeError(_http_status_message(probed))

    outcome, error_message = classify_connector_result(
        "companies_house",
        records,
        exc,
        http_status,
        duration,
        run_date,
    )
    _log_connector_outcome(
        "companies_house",
        outcome,
        error_message,
        len(records) if records is not None else 0,
        run_date,
    )
    entry = _connector_entry(outcome, records, error_message, http_status, duration)
    return records or [], entry


def _ingest_mauritius(date_from: str, date_to: str, run_date: str) -> tuple[list[CompanyRecord], dict]:
    logger.info("── Mauritius MNS connector ────────────────────────────")
    exc: BaseException | None = None
    records: list[CompanyRecord] | None = None
    started = time.perf_counter()

    try:
        records = _run_connector_timed(
            mns_connector.fetch_new_incorporations,
            date_from=date_from,
            date_to=date_to,
        )
    except FuturesTimeoutError:
        exc = TimeoutError(f"Timed out after {CONNECTOR_TIMEOUT_SECONDS}s")
    except Exception as err:
        exc = err

    duration = time.perf_counter() - started
    outcome, error_message = classify_connector_result(
        "mauritius_mns",
        records,
        exc,
        None,
        duration,
        run_date,
    )
    _log_connector_outcome(
        "mauritius_mns",
        outcome,
        error_message,
        len(records) if records is not None else 0,
        run_date,
    )
    entry = _connector_entry(outcome, records, error_message, None, duration)
    return records or [], entry


def ingest(
    date_from: str,
    date_to: str,
    skip_difc: bool = False,
    skip_mauritius: bool = False,
) -> tuple[list[CompanyRecord], dict[str, dict]]:
    """Run connectors and return combined records plus per-connector summary entries."""
    records: list[CompanyRecord] = []
    connectors: dict[str, dict] = {}
    run_date = date_to

    ch_records, ch_entry = _ingest_companies_house(date_from, date_to, run_date)
    records.extend(ch_records)
    connectors["companies_house"] = ch_entry

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

    if not skip_mauritius:
        mns_records, mns_entry = _ingest_mauritius(date_from, date_to, run_date)
        records.extend(mns_records)
        connectors["mauritius_mns"] = mns_entry
    else:
        logger.info("Mauritius MNS connector skipped.")

    return records, connectors


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
    "company_number",
    "file_no",
    "sic_codes",
]


def _record_to_csv_row(record: CompanyRecord) -> dict:
    raw = record.raw_data or {}

    if record.source == "companies_house":
        company_number = raw.get("company_number", "")
        file_no = ""
        sic_list = raw.get("sic_codes", []) or []
        sic_codes = "|".join(str(s) for s in sic_list)
    elif record.source == "mauritius_mns":
        company_number = ""
        file_no = raw.get("file_no", "")
        sic_codes = ""
    else:
        company_number = ""
        file_no = ""
        sic_codes = ""

    return {
        "company_name": record.company_name,
        "normalized_name": record.normalized_name or "",
        "jurisdiction": record.jurisdiction,
        "entity_type": record.entity_type or "",
        "incorporation_date": record.incorporation_date or "",
        "score": record.score if record.score is not None else "",
        "source": record.source,
        "canonical_entity_id": record.canonical_entity_id or "",
        "company_number": company_number,
        "file_no": file_no,
        "sic_codes": sic_codes,
    }


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
            writer.writerow(_record_to_csv_row(record))

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
) -> int:
    """
    Full pipeline: ingest → score → deduplicate → persist → export.

    Returns process exit code (0 success, 1 failed connectors).
    """
    logger.info(
        "Pipeline started  [%s → %s] dry_run=%s", date_from, date_to, dry_run
    )

    # 1. Ingest
    records, connector_entries = ingest(
        date_from=date_from,
        date_to=date_to,
        skip_difc=skip_difc,
        skip_mauritius=skip_mauritius,
    )
    logger.info("Total records ingested: %d", len(records))

    pipeline_outcome, notes = compute_pipeline_outcome(connector_entries)
    write_run_summary(
        run_date=date_to,
        connectors=connector_entries,
        pipeline_outcome=pipeline_outcome,
        notes=notes,
        total_records=len(records),
    )

    if pipeline_outcome == "FAILED":
        logger.error("Pipeline outcome: FAILED — %s", notes)
        return 1

    if pipeline_outcome == "PARTIAL":
        logger.warning(
            "WARNING: pipeline completed with partial data — "
            "one or more connectors failed. Check exports/run_summary.json. %s",
            notes,
        )
    elif pipeline_outcome == "ALL_EMPTY":
        logger.info("Pipeline outcome: ALL_EMPTY — %s", notes)
    else:
        logger.info("Pipeline outcome: OK — %s", notes)

    if not records:
        logger.info("No records to process after ingest.")
        export_csv(records, run_date=date_to)
        return 0

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
    return 0


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

    exit_code = run_pipeline(
        date_from=date_from,
        date_to=date_to,
        skip_difc=args.skip_difc,
        skip_mauritius=args.skip_mauritius,
        dry_run=args.dry_run,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
