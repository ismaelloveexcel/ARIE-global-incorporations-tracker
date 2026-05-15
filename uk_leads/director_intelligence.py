"""Lightweight director intelligence from Companies House appointments (verified only)."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from uk_leads.companies_house_people import _session, officer_id_from_item

_APPOINTMENTS_BASE = "https://api.company-information.service.gov.uk"
_CACHE_DIR = Path("data") / "ch_appointments"
_MAX_OFFICERS = 5
_FETCH_DELAY = 0.35

_FINANCE_NAME_PATTERNS = [
    r"\bfintech\b",
    r"\bpayments?\b",
    r"\bfinance\b",
    r"\bfinancial\b",
    r"\bcapital\b",
    r"\bfund\b",
    r"\binvestment\b",
    r"\basset\b",
    r"\bbank\b",
    r"\btrust\b",
    r"\bwealth\b",
]

_DISSOLVED_STATUS_MARKERS = ("dissolved", "liquidation", "closed", "receiver", "insolvency")


def _cache_path(officer_id: str) -> Path:
    safe = re.sub(r"[^\w\-]", "_", officer_id)
    return _CACHE_DIR / f"{safe}.json"


def _load_cached_appointments(officer_id: str) -> list[dict[str, Any]] | None:
    path = _cache_path(officer_id)
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("items") or []
    except (json.JSONDecodeError, OSError):
        return None


def _save_cached_appointments(officer_id: str, items: list[dict[str, Any]]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with _cache_path(officer_id).open("w", encoding="utf-8") as fh:
        json.dump({"items": items, "source": "companies_house"}, fh)


def fetch_appointment_items(officer_id: str) -> list[dict[str, Any]]:
    if not officer_id:
        return []
    cached = _load_cached_appointments(officer_id)
    if cached is not None:
        return cached

    url = f"{_APPOINTMENTS_BASE}/officers/{officer_id}/appointments"
    r = _session().get(url, params={"items_per_page": 100}, timeout=30)
    r.raise_for_status()
    items = r.json().get("items") or []
    _save_cached_appointments(officer_id, items)
    time.sleep(_FETCH_DELAY)
    return items


def _appointment_year(appointed_on: str) -> int | None:
    if not appointed_on or len(appointed_on) < 4:
        return None
    try:
        return int(appointed_on[:4])
    except ValueError:
        return None


def _is_active_appointment(item: dict[str, Any]) -> bool:
    if item.get("resigned_on"):
        return False
    status = ((item.get("appointed_to") or {}).get("company_status") or "").lower()
    return not any(m in status for m in _DISSOLVED_STATUS_MARKERS)


def _is_dissolved_appointment(item: dict[str, Any]) -> bool:
    if item.get("resigned_on"):
        return True
    status = ((item.get("appointed_to") or {}).get("company_status") or "").lower()
    return any(m in status for m in _DISSOLVED_STATUS_MARKERS)


def _company_name_financial(company_name: str) -> bool:
    text = (company_name or "").lower()
    return any(re.search(p, text, re.IGNORECASE) for p in _FINANCE_NAME_PATTERNS)


def summarize_appointments(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Build verified director profile stats from appointment items."""
    active = 0
    dissolved = 0
    years: list[int] = []
    active_companies: list[str] = []
    finance_active = 0

    for item in items:
        year = _appointment_year(item.get("appointed_on") or "")
        if year:
            years.append(year)

        appointed_to = item.get("appointed_to") or {}
        cname = appointed_to.get("company_name") or ""
        cnum = appointed_to.get("company_number") or ""

        if _is_active_appointment(item):
            active += 1
            if cnum:
                active_companies.append(cnum)
            if _company_name_financial(cname):
                finance_active += 1
        elif _is_dissolved_appointment(item):
            dissolved += 1

    total = active + dissolved
    ratio_active = round(active / total, 2) if total else None
    first_year = min(years) if years else None

    return {
        "active_appointments": active,
        "dissolved_appointments": dissolved,
        "active_dissolved_ratio": ratio_active,
        "first_appointment_year": first_year,
        "multiple_current_companies": active >= 2,
        "finance_active_count": finance_active,
        "finance_heavy_portfolio": active >= 2 and finance_active >= max(2, active // 2),
        "active_company_numbers": active_companies,
        "source": "companies_house",
    }


def enrich_officer_profiles(
    officers: list[dict[str, Any]],
    raw_items: list[dict[str, Any]] | None = None,
    max_officers: int = _MAX_OFFICERS,
) -> list[dict[str, Any]]:
    """
    Attach director_profile to each officer. raw_items are CH officer list items
  with links; if omitted, officers must include officer_id.
    """
    link_by_name: dict[str, str] = {}
    if raw_items:
        for item in raw_items:
            oid = officer_id_from_item(item)
            if oid:
                link_by_name[_officer_name_key(item)] = oid

    enriched: list[dict[str, Any]] = []
    fetched = 0
    for off in officers:
        row = dict(off)
        if fetched >= max_officers:
            row["director_profile"] = None
            row["director_profile_skipped"] = True
            enriched.append(row)
            continue

        role = (row.get("role") or "").lower()
        if "corporate" in role:
            row["director_profile"] = None
            enriched.append(row)
            continue

        oid = row.get("officer_id") or link_by_name.get(_officer_name_key_from_officer(row), "")
        if not oid:
            row["director_profile"] = None
            enriched.append(row)
            continue

        try:
            items = fetch_appointment_items(oid)
            row["director_profile"] = summarize_appointments(items)
            fetched += 1
        except Exception:
            row["director_profile"] = None
            row["director_profile_error"] = True
        enriched.append(row)
    return enriched


def _officer_name_key(item: dict[str, Any]) -> str:
    name = item.get("name") or ""
    if not name and item.get("name_elements"):
        ne = item["name_elements"]
        name = " ".join(
            str(ne.get(k) or "") for k in ("title", "forename", "surname") if ne.get(k)
        )
    return re.sub(r"\s+", " ", name.strip().lower())


def _officer_name_key_from_officer(off: dict[str, Any]) -> str:
    return re.sub(r"\s+", " ", (off.get("name") or "").strip().lower())


def compute_director_network_signals(
    officers: list[dict[str, Any]],
    current_company_number: str,
    lead_company_numbers: set[str] | None = None,
) -> dict[str, list[str]]:
    """Derive lead-level strengths/cautions from verified director profiles."""
    strengths: list[str] = []
    cautions: list[str] = []
    leads = lead_company_numbers or set()
    leads = {c for c in leads if c and c != current_company_number}

    for off in officers:
        profile = off.get("director_profile")
        if not profile:
            continue
        name = off.get("name") or "Director"
        active = profile.get("active_appointments") or 0
        dissolved = profile.get("dissolved_appointments") or 0
        total = active + dissolved

        if profile.get("multiple_current_companies"):
            strengths.append(f"{name}: holds multiple active company appointments ({active} active)")

        if profile.get("finance_heavy_portfolio"):
            strengths.append(f"{name}: financial-services-heavy appointment portfolio (verified names)")

        if active >= 3:
            strengths.append(f"{name}: serial operator — {active} active appointments")

        if total >= 3:
            ratio = profile.get("active_dissolved_ratio")
            if ratio is not None and ratio < 0.4:
                cautions.append(
                    f"{name}: high dissolved ratio ({dissolved} dissolved vs {active} active)"
                )

        if leads:
            overlap = set(profile.get("active_company_numbers") or []) & leads
            if overlap:
                cautions.append(
                    f"{name}: also appointed at {len(overlap)} other lead(s) in this list"
                )

    def _uniq(xs: list[str]) -> list[str]:
        seen: set[str] = set()
        out = []
        for x in xs:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    return {"strengths": _uniq(strengths)[:6], "cautions": _uniq(cautions)[:6]}


def merge_signal_lists(*groups: dict[str, list[str]]) -> dict[str, list[str]]:
    strengths: list[str] = []
    cautions: list[str] = []
    for g in groups:
        strengths.extend(g.get("strengths") or [])
        cautions.extend(g.get("cautions") or [])

    def _uniq(xs: list[str]) -> list[str]:
        seen: set[str] = set()
        out = []
        for x in xs:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    return {"strengths": _uniq(strengths)[:10], "cautions": _uniq(cautions)[:10]}
