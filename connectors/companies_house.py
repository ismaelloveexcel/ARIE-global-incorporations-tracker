"""
connectors/companies_house.py
──────────────────────────────
UK Companies House API connector.

Fetches companies incorporated within a date window using the
advanced-search endpoint:
  GET https://api.company-information.service.gov.uk/advanced-search/companies

API docs: https://developer.company-information.service.gov.uk/

Environment variables required
───────────────────────────────
  COMPANIES_HOUSE_API_KEY   Basic-auth username (password is empty)

Usage (standalone)
──────────────────
    from connectors.companies_house import fetch_new_incorporations
    records = fetch_new_incorporations(date_from="2024-01-15", date_to="2024-01-15")
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, timedelta
from typing import Generator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from normalization.schema import CompanyRecord

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.company-information.service.gov.uk"
_SEARCH_PATH = "/advanced-search/companies"
_PAGE_SIZE = 100          # max items per page (API cap)
_RATE_LIMIT_DELAY = 0.5   # seconds between requests (600 req/min limit)
_SOURCE = "companies_house"


def _build_session() -> requests.Session:
    api_key = os.environ.get("COMPANIES_HOUSE_API_KEY", "")
    session = requests.Session()
    session.auth = (api_key, "")

    retry = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    return session


def _fetch_page(
    session: requests.Session,
    date_from: str,
    date_to: str,
    start_index: int,
) -> dict:
    params = {
        "incorporatedFrom": date_from,
        "incorporatedTo": date_to,
        "size": _PAGE_SIZE,
        "start_index": start_index,
    }
    url = f"{_BASE_URL}{_SEARCH_PATH}"
    response = session.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def _parse_record(item: dict) -> CompanyRecord:
    """Convert a single Companies House search result item to a CompanyRecord."""
    name = item.get("company_name") or item.get("title") or ""
    entity_type = item.get("company_type", "")
    inc_date = item.get("date_of_creation") or item.get("incorporation_date")

    return CompanyRecord(
        company_name=name,
        jurisdiction="UK",
        source=_SOURCE,
        entity_type=entity_type,
        incorporation_date=inc_date,
        raw_data=item,
    )


def fetch_new_incorporations(
    date_from: str | None = None,
    date_to: str | None = None,
    lookback_days: int = 1,
) -> list[CompanyRecord]:
    """
    Fetch all UK companies incorporated between *date_from* and *date_to*.

    If *date_from* / *date_to* are omitted the last *lookback_days* days
    are used (default 1 = yesterday).

    Returns a list of ``CompanyRecord`` objects.
    """
    if date_from is None or date_to is None:
        today = date.today()
        start = today - timedelta(days=lookback_days)
        date_from = date_from or start.isoformat()
        date_to = date_to or (today - timedelta(days=1)).isoformat()

    logger.info(
        "Fetching Companies House incorporations from %s to %s …", date_from, date_to
    )

    session = _build_session()
    records: list[CompanyRecord] = []
    start_index = 0

    while True:
        try:
            data = _fetch_page(session, date_from, date_to, start_index)
        except requests.HTTPError as exc:
            logger.error("Companies House API error: %s", exc)
            break

        items = data.get("items") or []
        total_results = data.get("hits") or data.get("total_results") or len(items)

        for item in items:
            records.append(_parse_record(item))

        fetched_so_far = start_index + len(items)
        logger.debug(
            "Fetched %d / %d companies (page start=%d)",
            fetched_so_far,
            total_results,
            start_index,
        )

        if fetched_so_far >= total_results or not items:
            break

        start_index += _PAGE_SIZE
        time.sleep(_RATE_LIMIT_DELAY)

    logger.info("Companies House: fetched %d records.", len(records))
    return records
