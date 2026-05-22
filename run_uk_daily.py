"""
run_uk_daily.py — UK leads CLI (engineering helper).

Writes to the canonical pipeline snapshot: exports/YYYY-MM-DD.csv (UK rows only;
run main.py for full UK + Mauritius pipeline).

For the operator dashboard: python -m app.main
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from uk_leads.core import fetch_uk_leads
from uk_leads.data_loader import pipeline_export_path
from uk_leads.mauritius_snapshot import _PIPELINE_FIELDS
from uk_leads.uk_snapshot import _read_preserved_mauritius_rows, _uk_row_to_pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("uk_daily")


def run(
    date_from: str,
    date_to: str,
    min_score: float | None,
    top: int | None,
    output: Path | None,
) -> int:
    if not os.environ.get("COMPANIES_HOUSE_API_KEY"):
        logger.error("COMPANIES_HOUSE_API_KEY is not set. Copy .env.example to .env.")
        sys.exit(1)

    logger.info("Fetching UK incorporations %s to %s …", date_from, date_to)
    rows, total = fetch_uk_leads(date_from, date_to, min_score=min_score, top=top)
    logger.info("Fetched %d companies; exporting %d.", total, len(rows))

    out_path = output or pipeline_export_path(date_to)
    pipeline_rows = [_uk_row_to_pipeline(r) for r in rows]
    preserved = _read_preserved_mauritius_rows(out_path) if output is None else []

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_PIPELINE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in pipeline_rows + preserved:
            writer.writerow({k: row.get(k, "") for k in _PIPELINE_FIELDS})

    logger.info("Wrote %s", out_path.resolve())
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export UK incorporation leads into exports/YYYY-MM-DD.csv"
    )
    parser.add_argument("--date", metavar="YYYY-MM-DD")
    parser.add_argument("--lookback", type=int, default=1)
    parser.add_argument("--min-score", type=float, default=None)
    parser.add_argument("--top", type=int, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Override output path (default: exports/<date>.csv)",
    )
    args = parser.parse_args()

    if args.date:
        date_from = date_to = args.date
    else:
        today = date.today()
        date_to = (today - timedelta(days=1)).isoformat()
        date_from = (
            date_to
            if args.lookback <= 1
            else (today - timedelta(days=args.lookback)).isoformat()
        )

    run(date_from, date_to, args.min_score, args.top, args.output)


if __name__ == "__main__":
    main()
