"""
connectors/mauritius.py
────────────────────────
Mauritius CBRD online search scraper (Playwright).

Site: https://onlinesearch.mns.mu/
Filters by incorporation/registration date range and returns
GBC and Authorised Company rows only.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, sync_playwright

from normalization.schema import CompanyRecord

logger = logging.getLogger(__name__)

_SOURCE = "mauritius_mns"
_BASE_URL = "https://onlinesearch.mns.mu/"
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 10
ATTEMPT_TIMEOUT_MS = 90_000
DEBUG_DIR = Path("exports") / "debug"

_HEADER_MAP = {
    "name": "company_name",
    "fileno.": "file_no",
    "fileno": "file_no",
    "category": "entity_type",
    "incorporation/registrationdate": "incorporation_date",
    "nature": "nature",
    "status": "company_status",
}


def _iso_to_dmy(iso_date: str) -> str:
    """YYYY-MM-DD → dd/mm/yyyy for the site date fields."""
    dt = datetime.strptime(iso_date.strip(), "%Y-%m-%d")
    return dt.strftime("%d/%m/%Y")


def _dmy_to_iso(dmy: str) -> str | None:
    """dd/mm/yyyy → YYYY-MM-DD."""
    text = (dmy or "").strip()
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    logger.debug("Could not parse Mauritius date: %s", dmy)
    return None


def _category_matches(category: str) -> bool:
    """Keep GBC and Authorised Company rows only (case-insensitive)."""
    text = (category or "").strip().lower()
    if not text:
        return False
    if "global business company" in text or "gbc" in text:
        return True
    if "authorised company" in text or "authorized company" in text:
        return True
    if re.search(r"\bac\b", text):
        return True
    return False


def _normalise_header(label: str) -> str:
    """Collapse whitespace so 'Incorporation/ Registration Date' matches map keys."""
    return label.strip().replace(" ", "").lower()


def _header_to_field(key: str) -> str | None:
    if key == "#" or key.startswith("#"):
        return None
    if key in _HEADER_MAP:
        return _HEADER_MAP[key]
    if "incorporation" in key and "date" in key:
        return "incorporation_date"
    return None


def _column_index_by_header(headers: list[str]) -> dict[str, int]:
    """Map logical field names to column indices using header text."""
    indices: dict[str, int] = {}
    for idx, raw in enumerate(headers):
        field = _header_to_field(_normalise_header(raw))
        if field:
            indices[field] = idx
    return indices


def _accept_cookies_if_present(page: Page) -> None:
    for label in ("Accept All", "Accept all", "Accept"):
        try:
            btn = page.get_by_role("button", name=label)
            if btn.count() and btn.first.is_visible():
                btn.first.click(timeout=3000)
                page.wait_for_timeout(500)
                return
        except PlaywrightTimeout:
            continue
        except Exception:
            continue


def _fill_input(el, iso_date: str) -> str:
    """Fill date control — HTML date inputs need YYYY-MM-DD; text inputs use dd/mm/yyyy."""
    input_type = (el.get_attribute("type") or "").lower()
    value = iso_date if input_type == "date" else _iso_to_dmy(iso_date)
    el.fill(value)
    try:
        return el.input_value()
    except Exception:
        return el.get_attribute("value") or value


def _input_blob(el) -> str:
    parts = [
        el.get_attribute("id") or "",
        el.get_attribute("placeholder") or "",
        el.get_attribute("formcontrolname") or "",
        el.get_attribute("aria-label") or "",
    ]
    return " ".join(parts).lower()


def _find_date_field(page: Page, kind: str, prefer_incorporation: bool = True):
    """Find From or To date input; prefer incorporation/registration fields."""
    inputs = page.locator("input[type='date'], input[type='text']")
    candidates: list[tuple[int, object]] = []

    for i in range(min(inputs.count(), 24)):
        el = inputs.nth(i)
        try:
            if not el.is_visible():
                continue
            blob = _input_blob(el)
            if "date" not in blob and "from" not in blob and "to" not in blob:
                continue
            is_from = "from" in blob
            is_to = "to" in blob and not is_from
            if kind == "from" and not is_from:
                continue
            if kind == "to" and not is_to:
                continue
            score = 0
            if prefer_incorporation and ("incorporation" in blob or "registration" in blob):
                score += 10
            if "partnership" in blob or "company" in blob:
                score -= 2
            candidates.append((score, el))
        except Exception:
            continue

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _fill_date_range(page: Page, date_from: str, date_to: str) -> tuple[str, str]:
    from_el = _find_date_field(page, "from")
    to_el = _find_date_field(page, "to")

    if from_el is None or to_el is None:
        raise RuntimeError("Could not locate incorporation date From/To fields")

    entered_from = _fill_input(from_el, date_from)
    page.wait_for_timeout(500)
    entered_to = _fill_input(to_el, date_to)
    page.wait_for_timeout(500)

    logger.info(
        "Mauritius date fields set — From: %s (requested %s), To: %s (requested %s)",
        entered_from,
        date_from,
        entered_to,
        date_to,
    )
    return entered_from, entered_to


def _click_search(page: Page) -> None:
    for locator in (
        page.get_by_role("button", name=re.compile(r"^search$", re.I)),
        page.locator("button:has-text('Search')"),
        page.locator("input[type='submit'][value*='Search' i]"),
    ):
        try:
            if locator.count():
                locator.first.click(timeout=10_000)
                return
        except Exception:
            continue
    raise RuntimeError("Could not locate Search button")


def _parse_results_table(page: Page) -> list[dict[str, str]]:
    table = page.locator("table").filter(has=page.locator("th")).first
    table.wait_for(state="visible", timeout=30_000)

    raw_headers = [th.inner_text() for th in table.locator("th").all()]
    headers = [_normalise_header(h) for h in raw_headers]
    col = _column_index_by_header(raw_headers)
    if "company_name" not in col:
        raise RuntimeError(
            f"Results table missing Name column; headers={raw_headers!r} normalised={headers!r}"
        )
    if "incorporation_date" not in col:
        logger.warning(
            "Incorporation date column not matched; headers=%r normalised=%r",
            raw_headers,
            headers,
        )

    rows: list[dict[str, str]] = []
    for tr in table.locator("tbody tr").all():
        cells = tr.locator("td").all()
        if not cells:
            continue
        values = [c.inner_text().strip() for c in cells]

        row: dict[str, str] = {}
        for field, idx in col.items():
            if idx < len(values):
                row[field] = values[idx]
        if row.get("company_name"):
            rows.append(row)
    return rows


def _has_next_page(page: Page) -> bool:
    for locator in (
        page.get_by_role("link", name=re.compile(r"next", re.I)),
        page.get_by_role("button", name=re.compile(r"next", re.I)),
        page.locator("a:has-text('Next')"),
        page.locator("button:has-text('Next')"),
    ):
        try:
            if not locator.count():
                continue
            el = locator.first
            if not el.is_visible():
                continue
            disabled = el.get_attribute("disabled")
            aria_disabled = el.get_attribute("aria-disabled")
            classes = el.get_attribute("class") or ""
            if disabled is not None or aria_disabled == "true" or "disabled" in classes.lower():
                continue
            return True
        except Exception:
            continue
    return False


def _click_next_page(page: Page) -> None:
    for locator in (
        page.get_by_role("link", name=re.compile(r"next", re.I)),
        page.get_by_role("button", name=re.compile(r"next", re.I)),
        page.locator("a:has-text('Next')"),
        page.locator("button:has-text('Next')"),
    ):
        try:
            if locator.count() and locator.first.is_visible():
                locator.first.click(timeout=10_000)
                page.wait_for_load_state("networkidle", timeout=60_000)
                page.wait_for_timeout(1000)
                return
        except Exception:
            continue
    raise RuntimeError("Next page control not clickable")


def _parse_incorporation_date(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    iso = _dmy_to_iso(text)
    if iso:
        return iso
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        pass
    logger.debug("Could not parse incorporation date cell: %r", raw)
    return ""


def _row_to_record(row: dict[str, str]) -> CompanyRecord | None:
    name = (row.get("company_name") or "").strip()
    category = (row.get("entity_type") or "").strip()
    if not name or not _category_matches(category):
        return None

    inc_iso = _parse_incorporation_date(row.get("incorporation_date", ""))
    status = (row.get("company_status") or "").strip()

    return CompanyRecord(
        company_name=name,
        jurisdiction="Mauritius",
        source=_SOURCE,
        entity_type=category,
        incorporation_date=inc_iso or "",
        raw_data={
            "file_no": (row.get("file_no") or "").strip(),
            "nature": (row.get("nature") or "").strip(),
            "company_status": status,
            "email": "",
            "phone": "",
        },
    )


def _scrape_date_range(page: Page, date_from: str, date_to: str) -> list[CompanyRecord]:
    page.goto(_BASE_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(1500)
    _accept_cookies_if_present(page)
    _fill_date_range(page, date_from, date_to)
    _click_search(page)
    page.wait_for_load_state("networkidle", timeout=60_000)
    page.wait_for_timeout(2000)

    records: list[CompanyRecord] = []
    seen: set[str] = set()
    page_num = 1

    while True:
        logger.debug("Mauritius scraper: parsing results page %d", page_num)
        try:
            raw_rows = _parse_results_table(page)
        except Exception as exc:
            if page_num == 1:
                raise
            logger.warning("Mauritius results table parse failed on page %d: %s", page_num, exc)
            break

        for raw in raw_rows:
            rec = _row_to_record(raw)
            if rec is None:
                continue
            key = f"{rec.company_name}|{rec.raw_data.get('file_no', '')}"
            if key in seen:
                continue
            seen.add(key)
            records.append(rec)

        if not _has_next_page(page):
            break
        try:
            _click_next_page(page)
        except Exception as exc:
            logger.warning("Mauritius pagination stopped: %s", exc)
            break
        page_num += 1

    return records


def _debug_artifact_paths() -> tuple[Path, Path]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base = DEBUG_DIR / f"mauritius_fail_{timestamp}"
    return base.with_suffix(".png"), base.with_suffix(".html")


def _save_failure_artifacts(
    page: Page | None,
    screenshot_path: Path,
    html_path: Path,
) -> tuple[str | None, str | None]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    saved_screenshot: str | None = None
    saved_html: str | None = None
    if page is None:
        return None, None
    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
        saved_screenshot = str(screenshot_path)
        logger.error(
            "Mauritius scraper failed — screenshot saved: %s",
            saved_screenshot,
        )
    except Exception as exc:
        logger.warning("Could not save Mauritius failure screenshot: %s", exc)
    try:
        html_path.write_text(page.content(), encoding="utf-8")
        saved_html = str(html_path)
        logger.error(
            "Mauritius scraper failed — HTML saved: %s",
            saved_html,
        )
    except Exception as exc:
        logger.warning("Could not save Mauritius failure HTML: %s", exc)
    return saved_screenshot, saved_html


def _run_single_attempt(
    date_from: str,
    date_to: str,
    screenshot_path: Path,
    html_path: Path,
) -> list[CompanyRecord]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        )
        page = context.new_page()
        page.set_default_timeout(ATTEMPT_TIMEOUT_MS)
        try:
            return _scrape_date_range(page, date_from, date_to)
        except Exception:
            _save_failure_artifacts(page, screenshot_path, html_path)
            raise
        finally:
            browser.close()


def fetch_new_incorporations(
    date_from: str,
    date_to: str | None = None,
) -> list[CompanyRecord]:
    """
    Scrape Mauritius CBRD for companies incorporated between date_from and date_to.

    Parameters
    ----------
    date_from, date_to:
        ISO dates (YYYY-MM-DD). If date_to is None, uses date_from (single day).
    """
    end = date_to or date_from
    logger.info("Mauritius scraper: %s → %s", date_from, end)

    last_exception: Exception | None = None
    last_screenshot: str | None = None
    last_html: str | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        logger.info("Mauritius scraper attempt %d of %d", attempt, MAX_RETRIES)
        screenshot_path, html_path = _debug_artifact_paths()
        try:
            records = _run_single_attempt(date_from, end, screenshot_path, html_path)
            if records:
                logger.info("Mauritius scraper: collected %d records.", len(records))
            else:
                logger.info(
                    "Mauritius scraper: confirmed empty — 0 GBC/Authorised Company "
                    "rows for %s → %s (search completed successfully)",
                    date_from,
                    end,
                )
            return records
        except Exception as exc:
            last_exception = exc
            if screenshot_path.exists():
                last_screenshot = str(screenshot_path)
            if html_path.exists():
                last_html = str(html_path)
            logger.error(
                "Mauritius scraper attempt %d failed: %s",
                attempt,
                exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS)

    logger.error(
        "Mauritius scraper FAILED after %d attempts | "
        "date: %s | last_error: %s | "
        "screenshot: %s | html: %s",
        MAX_RETRIES,
        date_from,
        str(last_exception),
        last_screenshot or "not saved",
        last_html or "not saved",
    )
    if last_exception is not None:
        raise last_exception
    raise RuntimeError("Mauritius scraper failed with no exception recorded")
