"""Dashboard classification, lead identity, and default assignment."""
from __future__ import annotations

import re

MU_VERIFY_URL = "https://onlinesearch.mns.mu/"

_INTRODUCER_KEYWORDS = (
    "management",
    "advisory",
    "services",
    "consulting",
    "corporate",
    "fiduciary",
    "trustees",
    "partners",
    "associates",
    "secretarial",
    "administration",
    "capital",
    "fund",
    "holdings",
    "investment",
    "group",
    "international",
    "global",
    "wealth",
    "family office",
)


def is_mauritius_gbc_ac(entity_type: str | None) -> bool:
    text = (entity_type or "").lower()
    if not text:
        return False
    if "global business" in text or re.search(r"\bgbc\b", text):
        return True
    if "authorised company" in text or "authorized company" in text:
        return True
    if re.search(r"\bac\b", text):
        return True
    return False


def is_mauritius_includable(row: dict) -> bool:
    """MU domestic and other non-GBC/AC types are excluded from both tabs."""
    source = (row.get("source") or "").strip().lower()
    if source != "mauritius_mns":
        return True
    return is_mauritius_gbc_ac(row.get("entity_type"))


def is_direct_client(row: dict) -> bool:
    source = (row.get("source") or "").strip().lower()
    if source == "companies_house":
        return True
    if source == "mauritius_mns":
        return is_mauritius_gbc_ac(row.get("entity_type"))
    return False


def _name_has_introducer_keyword(name: str) -> bool:
    text = (name or "").lower()
    return any(kw in text for kw in _INTRODUCER_KEYWORDS)


def is_introducer(row: dict) -> bool:
    source = (row.get("source") or "").strip().lower()
    if source != "mauritius_mns":
        return False
    if not is_mauritius_gbc_ac(row.get("entity_type")):
        return False
    return _name_has_introducer_keyword(row.get("company_name", ""))


def lead_id(row: dict) -> str:
    source = (row.get("source") or "").strip().lower()
    if source == "mauritius_mns":
        file_no = (row.get("file_no") or "").strip()
        if not file_no:
            raw = row.get("raw_data") or {}
            if isinstance(raw, dict):
                file_no = str(raw.get("file_no") or "").strip()
        if file_no:
            return f"mu:{file_no}"
        name = (row.get("normalized_name") or row.get("company_name") or "").strip().lower()
        slug = re.sub(r"[^a-z0-9]+", "_", name).strip("_")[:40]
        return f"mu:{slug or 'unknown'}"

    num = (row.get("company_number") or "").strip()
    if num:
        return num
    name = (row.get("normalized_name") or row.get("company_name") or "").strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", name).strip("_")[:40]
    return slug or "unknown"


def filter_tab_leads(rows: list[dict], tab: str) -> list[dict]:
    if tab == "direct_clients":
        return [r for r in rows if is_direct_client(r)]
    if tab == "introducers":
        return [r for r in rows if is_introducer(r)]
    return rows


def assignment_pool_for_lead(row: dict, pools: dict[str, list[str]]) -> list[str] | None:
    """Which round-robin pool applies when lead has no saved assignment."""
    direct = is_direct_client(row)
    intro = is_introducer(row)
    if direct and intro:
        return pools.get("direct_clients")
    if direct:
        return pools.get("direct_clients")
    if intro:
        return pools.get("introducers")
    return None
