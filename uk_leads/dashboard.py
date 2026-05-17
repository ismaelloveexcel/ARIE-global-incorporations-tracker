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


def _mu_gbc_or_ac(entity_type: str | None) -> bool:
    entity = (entity_type or "").lower()
    return any(
        t in entity
        for t in (
            "global business",
            "gbc",
            "authorised company",
            "authorized company",
        )
    )


def is_mauritius_gbc_ac(entity_type: str | None) -> bool:
    """Backward-compatible alias for pipeline filtering."""
    return _mu_gbc_or_ac(entity_type)


def is_mauritius_includable(row: dict) -> bool:
    """MU domestic and other non-GBC/AC types are excluded from both tabs."""
    source = (row.get("source") or "").strip().lower()
    if source != "mauritius_mns":
        return True
    return _mu_gbc_or_ac(row.get("entity_type"))


def is_direct_client(row: dict) -> bool:
    source = row.get("source", "")
    entity = (row.get("entity_type") or "").lower()

    if source == "companies_house":
        return True

    if source == "mauritius_mns":
        return _mu_gbc_or_ac(entity)

    return False


def is_introducer(row: dict) -> bool:
    source = row.get("source", "")
    entity = (row.get("entity_type") or "").lower()
    name = (row.get("company_name") or "").lower()

    if source == "companies_house":
        return False

    if source == "mauritius_mns":
        is_gbc_or_ac = _mu_gbc_or_ac(entity)
        if not is_gbc_or_ac:
            return False
        return any(kw in name for kw in _INTRODUCER_KEYWORDS)

    return False


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
        # Introducer relationships are maintained manually — not auto-split from pipeline.
        return []
    return rows


def dashboard_tabs_for_lead(row: dict) -> list[str]:
    """Which dashboard tabs include this lead (operator UI uses direct_clients only)."""
    if is_direct_client(row):
        return ["direct_clients"]
    return []


def assignment_pool_for_lead(row: dict, pools: dict[str, list[str]]) -> list[str] | None:
    """Which round-robin pool applies when lead has no saved assignment."""
    if is_direct_client(row):
        return pools.get("direct_clients")
    return None
