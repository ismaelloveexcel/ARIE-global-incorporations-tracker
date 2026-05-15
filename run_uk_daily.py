"""
run_uk_daily.py — UK leads CLI (CSV export).

For the stakeholder demo app, use: python -m app.main
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from uk_leads.core import DEMO_MIN_SCORE, DEMO_TOP, csv_path_for_date, export_csv, fetch_uk_leads

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
    demo: bool = False,
) -> int:
    if not os.environ.get("COMPANIES_HOUSE_API_KEY"):
        logger.error("COMPANIES_HOUSE_API_KEY is not set. Copy .env.example to .env.")
        sys.exit(1)

    logger.info("Fetching UK incorporations %s to %s …", date_from, date_to)
    rows, total = fetch_uk_leads(date_from, date_to, min_score=min_score, top=top)
    logger.info("Fetched %d companies; exporting %d.", total, len(rows))

    out_path = output or csv_path_for_date(date_to, demo=demo)

    export_csv(rows, out_path)
    logger.info("Wrote %s", out_path.resolve())
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export UK incorporation leads to CSV")
    parser.add_argument("--date", metavar="YYYY-MM-DD")
    parser.add_argument("--lookback", type=int, default=1)
    parser.add_argument("--min-score", type=float, default=None)
    parser.add_argument("--top", type=int, default=None)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    min_score, top = args.min_score, args.top
    if args.demo:
        min_score = DEMO_MIN_SCORE if min_score is None else min_score
        top = DEMO_TOP if top is None else top

    if args.date:
        date_from = date_to = args.date
    else:
        today = date.today()
        date_to = (today - timedelta(days=1)).isoformat()
        date_from = date_to if args.lookback <= 1 else (today - timedelta(days=args.lookback)).isoformat()

    output = args.output
    if args.demo and output is None:
        output = csv_path_for_date(date_to, demo=True)

    run(date_from, date_to, min_score, top, output, demo=args.demo)


if __name__ == "__main__":
    main()
