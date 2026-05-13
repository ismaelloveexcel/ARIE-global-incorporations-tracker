"""
connectors/mauritius.py
────────────────────────
Mauritius Registrar of Companies (MNS) online search scraper.

Uses Playwright to interact with:
  https://companies.mns.mu/

Supports:
  - Full pagination through all result pages
  - Snapshot diffing: persists a JSON snapshot of last-seen company names
    to ``snapshots/mauritius_snapshot.json`` and only emits records that
    are new since the previous run.

Environment variables
─────────────────────
  None required beyond Playwright being installed.

Usage
─────
    from connectors.mauritius import fetch_new_incorporations
    records = fetch_new_incorporations()
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from normalization.schema import CompanyRecord

logger = logging.getLogger(__name__)

_SOURCE = "mauritius_mns"
_BASE_URL = "https://companies.mns.mu/"
_SNAPSHOT_DIR = Path("snapshots")
_SNAPSHOT_FILE = _SNAPSHOT_DIR / "mauritius_snapshot.json"

# Selectors (update if site markup changes)
_COMPANY_ROW_SELECTOR = "table tbody tr"
_NEXT_PAGE_SELECTOR = "a[aria-label='Next'], .next-page, [data-page='next']"
_SEARCH_INPUT_SELECTOR = "input[type='text'], input[name='search'], #searchInput"
_SEARCH_BUTTON_SELECTOR = "button[type='submit'], #searchBtn, .search-button"


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_snapshot() -> dict[str, str]:
    """Return the previous snapshot {name_hash: company_name} or empty dict."""
    if _SNAPSHOT_FILE.exists():
        try:
            with _SNAPSHOT_FILE.open() as fh:
                return json.load(fh)
        except Exception as exc:
            logger.warning("Could not load snapshot: %s", exc)
    return {}


def _save_snapshot(snapshot: dict[str, str]) -> None:
    _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with _SNAPSHOT_FILE.open("w") as fh:
        json.dump(snapshot, fh, indent=2)
    logger.debug("Snapshot saved (%d entries).", len(snapshot))


def _name_hash(name: str) -> str:
    """Stable hash key for a company name."""
    return hashlib.sha256(name.strip().lower().encode()).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# Scraping helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_rows(page: Page) -> list[dict]:
    """Extract company rows from the current Mauritius MNS page."""
    rows: list[dict] = []

    table_rows = page.query_selector_all(_COMPANY_ROW_SELECTOR)
    for tr in table_rows:
        cells = tr.query_selector_all("td")
        if not cells:
            continue
        row: dict = {"raw_text": tr.inner_text()}
        if len(cells) >= 1:
            row["company_name"] = cells[0].inner_text().strip()
        if len(cells) >= 2:
            row["registration_number"] = cells[1].inner_text().strip()
        if len(cells) >= 3:
            row["entity_type"] = cells[2].inner_text().strip()
        if len(cells) >= 4:
            row["incorporation_date"] = cells[3].inner_text().strip()
        if len(cells) >= 5:
            row["status"] = cells[4].inner_text().strip()
        rows.append(row)

    return rows


def _parse_record(raw: dict) -> CompanyRecord | None:
    name = raw.get("company_name", "").strip()
    if not name:
        return None

    inc_date: str | None = None
    inc_date_raw = raw.get("incorporation_date", "")
    if inc_date_raw:
        try:
            from dateutil import parser as dateparser
            inc_date = dateparser.parse(inc_date_raw, dayfirst=False).date().isoformat()
        except Exception:
            inc_date = None

    return CompanyRecord(
        company_name=name,
        jurisdiction="Mauritius",
        source=_SOURCE,
        entity_type=raw.get("entity_type"),
        incorporation_date=inc_date,
        raw_data=raw,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_new_incorporations(
    date_from: str | None = None,
    lookback_days: int = 1,
    use_snapshot_diff: bool = True,
) -> list[CompanyRecord]:
    """
    Scrape the Mauritius MNS register for recently incorporated companies.

    Parameters
    ----------
    date_from:
        ISO-8601 date string. Used as a filter hint where the site supports it.
    lookback_days:
        Days back to treat as "new" when *date_from* is None.
    use_snapshot_diff:
        When True (default) the scraper compares scraped names against a
        persisted JSON snapshot and only returns *new* entries.

    Returns
    -------
    list[CompanyRecord]
    """
    if date_from is None:
        cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    else:
        cutoff = date_from

    logger.info("Mauritius MNS scraper: fetching incorporations on/after %s …", cutoff)

    previous_snapshot = _load_snapshot() if use_snapshot_diff else {}
    current_snapshot: dict[str, str] = {}
    records: list[CompanyRecord] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        )
        page = context.new_page()

        try:
            page.goto(_BASE_URL, wait_until="networkidle", timeout=60_000)
            page.wait_for_timeout(2000)

            # Attempt to trigger a search for recently incorporated companies
            search_input = page.query_selector(_SEARCH_INPUT_SELECTOR)
            if search_input:
                search_input.fill(cutoff)
                search_btn = page.query_selector(_SEARCH_BUTTON_SELECTOR)
                if search_btn:
                    search_btn.click()
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(2000)

            page_num = 1
            while True:
                logger.debug("Mauritius scraper: scraping page %d …", page_num)
                raw_rows = _extract_rows(page)

                for raw in raw_rows:
                    name = raw.get("company_name", "").strip()
                    if not name:
                        continue

                    key = _name_hash(name)
                    current_snapshot[key] = name

                    if use_snapshot_diff and key in previous_snapshot:
                        continue  # Already seen

                    rec = _parse_record(raw)
                    if rec:
                        records.append(rec)

                # Pagination
                next_btn = page.query_selector(_NEXT_PAGE_SELECTOR)
                if not next_btn:
                    break
                disabled = next_btn.get_attribute("disabled")
                if disabled is not None:
                    break

                next_btn.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1500)
                page_num += 1

        except Exception as exc:
            logger.error("Mauritius MNS scraper error: %s", exc)
        finally:
            browser.close()

    if use_snapshot_diff:
        merged = {**previous_snapshot, **current_snapshot}
        _save_snapshot(merged)

    logger.info("Mauritius MNS scraper: collected %d new records.", len(records))
    return records
