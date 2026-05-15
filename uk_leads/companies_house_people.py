"""Companies House officers and PSC (verified)."""
from __future__ import annotations

import os
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_BASE = "https://api.company-information.service.gov.uk"


def _session() -> requests.Session:
    session = requests.Session()
    session.auth = (os.environ.get("COMPANIES_HOUSE_API_KEY", ""), "")
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def officer_id_from_item(item: dict[str, Any]) -> str:
    links = item.get("links") or {}
    appt_path = (links.get("officer") or {}).get("appointments") or ""
    parts = appt_path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "officers":
        return parts[1]
    return ""


def _officer_name(item: dict[str, Any]) -> str:
    if item.get("name"):
        return str(item["name"])
    if item.get("officer_role"):
        pass
    for key in ("name", "title", "forename", "surname"):
        if item.get(key):
            continue
    ident = item.get("identification") or {}
    reg = ident.get("registration_number") or ident.get("place_registered")
    parts = []
    if item.get("title"):
        parts.append(str(item["title"]))
    if item.get("forename"):
        parts.append(str(item["forename"]))
    if item.get("surname"):
        parts.append(str(item["surname"]))
    name = " ".join(parts).strip()
    if name:
        return name
    return item.get("officer_role", "Officer") or "Unknown"


def fetch_officers(company_number: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (officer rows, raw API items for appointment links)."""
    url = f"{_BASE}/company/{company_number}/officers"
    r = _session().get(url, params={"items_per_page": 100}, timeout=30)
    r.raise_for_status()
    items = r.json().get("items") or []
    out = []
    for item in items:
        out.append(
            {
                "name": _officer_name(item),
                "role": item.get("officer_role", ""),
                "appointed_on": item.get("appointed_on", ""),
                "nationality": item.get("nationality", ""),
                "country_of_residence": item.get("country_of_residence", ""),
                "officer_id": officer_id_from_item(item),
                "source": "companies_house",
            }
        )
    return out, items


def _psc_name(item: dict[str, Any]) -> str:
    if item.get("name"):
        return str(item["name"])
    parts = []
    if item.get("name_elements"):
        ne = item["name_elements"]
        for k in ("title", "forename", "surname"):
            if ne.get(k):
                parts.append(str(ne[k]))
    return " ".join(parts).strip() or "PSC holder"


def fetch_psc(company_number: str) -> list[dict[str, Any]]:
    url = f"{_BASE}/company/{company_number}/persons-with-significant-control"
    r = _session().get(url, params={"items_per_page": 100}, timeout=30)
    r.raise_for_status()
    items = r.json().get("items") or []
    out = []
    for item in items:
        natures = item.get("natures_of_control") or []
        if isinstance(natures, list):
            natures_str = ", ".join(str(n) for n in natures)
        else:
            natures_str = str(natures)
        out.append(
            {
                "name": _psc_name(item),
                "natures_of_control": natures_str,
                "notified_on": item.get("notified_on", ""),
                "nationality": item.get("nationality", ""),
                "country_of_residence": item.get("country_of_residence", ""),
                "source": "companies_house",
            }
        )
    return out


def fetch_people(
    company_number: str,
    lead_company_numbers: set[str] | None = None,
    include_director_intel: bool = True,
) -> dict[str, Any]:
    officers, raw_items = fetch_officers(company_number)
    psc = fetch_psc(company_number)
    director_signals: dict[str, list[str]] = {"strengths": [], "cautions": []}

    if include_director_intel and officers:
        from uk_leads.director_intelligence import (
            compute_director_network_signals,
            enrich_officer_profiles,
        )

        officers = enrich_officer_profiles(officers, raw_items=raw_items)
        director_signals = compute_director_network_signals(
            officers, company_number, lead_company_numbers
        )

    return {
        "company_number": company_number,
        "officers": officers,
        "psc": psc,
        "director_signals": director_signals,
        "source": "companies_house",
    }
