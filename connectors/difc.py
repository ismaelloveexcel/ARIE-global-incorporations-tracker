"""
connectors/difc.py
───────────────────
DIFC (Dubai International Financial Centre) public register scraper.

The DIFC register is scraped via Playwright because the site renders
results client-side via JavaScript.

Target site: https://www.difc.ae/business/companies/

This connector navigates to the DIFC company search, filters by
recently registered entities and collects all results visible on the
page.  Full pagination is supported.

Environment variables
─────────────────────
  None required beyond Playwright being installed
  (run: playwright install chromium)

Usage
─────
    from connectors.difc import fetch_new_incorporations
    records = fetch_new_incorporations()
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from playwright.sync_api import Page, sync_playwright

from normalization.schema import CompanyRecord

logger = logging.getLogger(__name__)

_SOURCE = "difc"
_BASE_URL = "https://www.difc.ae/business/companies/"
# Selector constants – update if the DIFC site changes its markup
_COMPANY_ROW_SELECTOR = "table tbody tr, .company-list-item, [data-company-name]"
_NEXT_PAGE_SELECTOR = "a[aria-label='Next page'], .pagination-next, button[aria-label='Next']"


def _extract_rows(page: Page) -> list[dict]:
    """Extract company data from the current page state."""
    rows: list[dict] = []

    # Try structured table rows first
    table_rows = page.query_selector_all("table tbody tr")
    if table_rows:
        for tr in table_rows:
            cells = tr.query_selector_all("td")
            if not cells:
                continue
            row: dict = {"raw_text": tr.inner_text()}
            if len(cells) >= 1:
                row["company_name"] = cells[0].inner_text().strip()
            if len(cells) >= 2:
                row["entity_type"] = cells[1].inner_text().strip()
            if len(cells) >= 3:
                row["incorporation_date"] = cells[2].inner_text().strip()
            if len(cells) >= 4:
                row["status"] = cells[3].inner_text().strip()
            rows.append(row)
    else:
        # Fallback: generic item list
        items = page.query_selector_all(".company-list-item, [data-company-name]")
        for item in items:
            text = item.inner_text().strip()
            name_el = item.query_selector("[data-company-name], .company-name, h3, h4")
            rows.append(
                {
                    "company_name": name_el.inner_text().strip() if name_el else text,
                    "raw_text": text,
                }
            )

    return rows


def _parse_record(raw: dict, cutoff_date: str) -> CompanyRecord | None:
    """
    Build a CompanyRecord from a raw scraped row dict.

    Returns None if:
    - the row has no company name, or
    - the incorporation date is present but pre-dates *cutoff_date*, or
    - the incorporation date is missing or cannot be parsed.

    Records without a parseable date are **always excluded** to prevent
    the daily pipeline from emitting the entire visible register when the
    date field is absent (e.g. the fallback extractor path).  This is an
    intentional conservative choice: without a known date we cannot safely
    determine whether the company is new.
    """
    name = raw.get("company_name", "").strip()
    if not name:
        return None

    inc_date_raw = raw.get("incorporation_date", "")
    inc_date: str | None = None
    if inc_date_raw:
        try:
            from dateutil import parser as dateparser
            parsed = dateparser.parse(inc_date_raw, dayfirst=False)
            inc_date = parsed.date().isoformat()
            if inc_date < cutoff_date:
                return None
        except Exception:
            # Date is present but not parseable — skip rather than accepting
            # an undated record that could be from any point in history.
            return None
    else:
        # No date available — skip for the same reason as unparseable dates.
        return None

    return CompanyRecord(
        company_name=name,
        jurisdiction="DIFC",
        source=_SOURCE,
        entity_type=raw.get("entity_type"),
        incorporation_date=inc_date,
        raw_data=raw,
    )


def fetch_new_incorporations(
    date_from: str | None = None,
    lookback_days: int = 1,
) -> list[CompanyRecord]:
    """
    Scrape the DIFC public register for recently incorporated companies.

    Parameters
    ----------
    date_from:
        ISO-8601 date string (inclusive lower bound).  Defaults to
        ``today - lookback_days``.
    lookback_days:
        How many days back to treat as "new" when *date_from* is None.

    Returns
    -------
    list[CompanyRecord]
    """
    if date_from is None:
        cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
    else:
        cutoff = date_from

    logger.info("DIFC scraper: fetching incorporations on/after %s …", cutoff)
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

            page_num = 1
            while True:
                logger.debug("DIFC scraper: scraping page %d …", page_num)
                raw_rows = _extract_rows(page)

                stop_pagination = False
                for raw in raw_rows:
                    rec = _parse_record(raw, cutoff)
                    if rec is None:
                        # If we encounter a record older than cutoff assume
                        # results are date-sorted and stop.
                        inc_raw = raw.get("incorporation_date", "")
                        if inc_raw:
                            stop_pagination = True
                    else:
                        records.append(rec)

                if stop_pagination:
                    break

                # Attempt to navigate to next page
                next_btn = page.query_selector(_NEXT_PAGE_SELECTOR)
                if not next_btn:
                    break
                is_disabled = next_btn.get_attribute("disabled")
                if is_disabled is not None:
                    break

                next_btn.click()
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1500)
                page_num += 1

        except Exception as exc:
            logger.error("DIFC scraper error: %s", exc)
        finally:
            browser.close()

    logger.info("DIFC scraper: collected %d records.", len(records))
    return records
