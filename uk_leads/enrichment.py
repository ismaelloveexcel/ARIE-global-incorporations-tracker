"""
Lead enrichment and classification — transparent, no fake data.

Future outreach fields are defined here so they can be populated later
without restructuring the app.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from normalization.schema import CompanyRecord
from scoring.engine import score as compute_fit_score

# Columns reserved for future enrichment (left blank unless sourced)
OUTREACH_EXTENSION_FIELDS = [
    "company_description",
    "industry_focus",
    "founders_directors",
    "country_of_operation",
    "payment_fintech_indicator",
    "regulated_activity_indicator",
    "introducer_relevance",
    "banking_need_signal",
    "cross_border_indicator",
]

ENRICHMENT_PLACEHOLDER = "Pending enrichment"

CH_PROFILE_BASE = "https://find-and-update.company-information.service.gov.uk/company/"

_DIRECT_PATTERNS = [
    r"\bfintech\b",
    r"\bpayments?\b",
    r"\bcrypt(?:o|currency)?\b",
    r"\bblockchain\b",
    r"\bdigital asset\b",
    r"\bdefi\b",
    r"\bweb3\b",
    r"\bremittance\b",
    r"\bexchange\b",
    r"\bwallet\b",
    r"\bpaytech\b",
    r"\bregtech\b",
    r"\bcapital\b",
    r"\bfund\b",
    r"\bventure\b",
    r"\binvestment\b",
]

_INTRODUCER_PATTERNS = [
    r"\btrust\b",
    r"\bfiduciary\b",
    r"\bmanagement\b",
    r"\bcorporate services\b",
    r"\baccounting\b",
    r"\baudit\b",
    r"\blegal\b",
    r"\bsolicitors?\b",
    r"\bconsulting\b",
    r"\badvisory\b",
    r"\bsecretarial\b",
    r"\badministration\b",
    r"\bnominee\b",
]

_FINTECH_PAYMENT_PATTERNS = _DIRECT_PATTERNS

_CROSS_BORDER_PATTERNS = [
    r"\bglobal\b",
    r"\binternational\b",
    r"\bworldwide\b",
    r"\boffshore\b",
    r"\bholding\b",
    r"\bholdings\b",
    r"\boverseas\b",
]

_CAPITAL_PATTERNS = [r"\bcapital\b", r"\binvestment\b", r"\bventure\b", r"\bfund\b", r"\basset\b"]

_FINANCIAL_SIC_PREFIXES = ("64", "65", "66", "62", "63")


def format_sic_codes(raw: dict[str, Any] | None) -> str:
    if not raw:
        return ""
    sic = raw.get("sic_codes") or []
    if isinstance(sic, str):
        return sic.strip()
    return ", ".join(str(s).strip() for s in sic if s)


def priority_from_score(score: float | None) -> str:
    s = float(score or 0)
    if s >= 70:
        return "High"
    if s >= 40:
        return "Medium"
    return "Low"


def classify_lead_type(company_name: str) -> tuple[str, str]:
    """
    Returns (lead_type, lead_type_reason).
    Introducer patterns checked first (more specific for service firms).
    """
    text = (company_name or "").lower()
    for pat in _INTRODUCER_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            label = pat.replace(r"\b", "").replace("\\", "")
            return "introducer", f"Name suggests professional / fiduciary services ({label.strip()})"

    for pat in _DIRECT_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            label = pat.replace(r"\b", "").replace("\\", "")
            return "direct", f"Name suggests financial / fintech activity ({label.strip()})"

    return "direct", "Default: newly incorporated UK company (registration review)"


def is_fintech_payment_lead(company_name: str, sic_codes: str) -> bool:
    text = (company_name or "").lower()
    for pat in _FINTECH_PAYMENT_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True
    for prefix in ("64", "65", "66", "62"):
        for part in (sic_codes or "").replace(" ", "").split(","):
            if part.strip().startswith(prefix):
                return True
    return False


def incorporation_age(incorporation_date: str | None, reference: date | None = None) -> tuple[str, int | None]:
    """Return (human label, days since incorporation)."""
    if not incorporation_date:
        return "", None
    ref = reference or date.today()
    try:
        inc = date.fromisoformat(str(incorporation_date)[:10])
    except ValueError:
        return "", None
    days = (ref - inc).days
    if days < 0:
        return "Incorporated today", 0
    if days == 0:
        return "Incorporated today", 0
    if days == 1:
        return "Incorporated 1 day ago", 1
    if days < 7:
        return f"Incorporated {days} days ago", days
    if days < 14:
        return "New this week", days
    if days < 31:
        weeks = days // 7
        return f"New · {weeks} week{'s' if weeks != 1 else ''} ago", days
    return f"Incorporated {days} days ago", days


def _sic_financial(sic_codes: str) -> bool:
    for part in (sic_codes or "").replace(" ", "").split(","):
        p = part.strip()
        if any(p.startswith(prefix) for prefix in _FINANCIAL_SIC_PREFIXES):
            return True
    return False


def row_to_record(row: dict[str, Any]) -> CompanyRecord:
    raw: dict[str, Any] = {}
    jurisdiction = (row.get("jurisdiction") or "UK").strip()
    sic = row.get("sic_codes") or ""
    if jurisdiction == "UK" and sic and sic != "—":
        raw["sic_codes"] = [s.strip() for s in str(sic).split(",") if s.strip()]

    return CompanyRecord(
        company_name=row.get("company_name") or "",
        jurisdiction=jurisdiction,
        source=row.get("source") or "",
        entity_type=row.get("entity_type"),
        incorporation_date=row.get("incorporation_date"),
        raw_data=raw,
    )


def build_why_tags(
    company_name: str,
    sic_codes: str,
    lead_type: str,
    incorporation_age_days: int | None,
    jurisdiction: str = "",
) -> list[str]:
    """Short explainable tags — no speculation beyond name/SIC/age."""
    tags: list[str] = []
    text = (company_name or "").lower()

    if incorporation_age_days is not None and incorporation_age_days <= 7:
        tags.append("Recently incorporated")
    elif incorporation_age_days is not None and incorporation_age_days <= 14:
        tags.append("New this week")

    if _sic_financial(sic_codes):
        tags.append("Financial SIC classification")

    for pat in _FINTECH_PAYMENT_PATTERNS[:12]:
        if re.search(pat, text, re.IGNORECASE):
            tags.append("Payments / fintech keywords")
            break

    for pat in _CROSS_BORDER_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            tags.append("Cross-border terminology")
            break

    for pat in _CAPITAL_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            tags.append("Capital / investment indicators")
            break

    if lead_type == "introducer":
        tags.append("Management / corporate services profile")

    if (jurisdiction or "").strip() == "Mauritius":
        tags.append("Mauritius GBC/AC")

    if not tags:
        tags.append("New incorporation")

    # De-duplicate preserving order
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def format_entity_label(entity_type: str, jurisdiction: str = "") -> str:
    """Human-readable entity type for operators (not raw registry codes)."""
    raw = (entity_type or "").strip()
    if not raw:
        return "Company"
    key = raw.upper().replace(".", "")
    labels = {
        "LTD": "Private Limited Company",
        "PLC": "Public Limited Company",
        "LLP": "Limited Liability Partnership",
        "GLOBAL BUSINESS COMPANY": "Global Business Company",
        "GBC": "Global Business Company",
        "AUTHORISED COMPANY": "Authorised Company",
        "AC": "Authorised Company",
        "PRIVATE LIMITED COMPANY": "Private Limited Company",
        "LIMITED": "Limited Company",
    }
    if key in labels:
        return labels[key]
    if raw.isupper() and len(raw) > 3:
        return raw.title()
    return raw[0].upper() + raw[1:] if raw else "Company"


def _registry_source_label(row: dict[str, Any]) -> str:
    source = (row.get("source") or "").strip().lower()
    jurisdiction = (row.get("jurisdiction") or "").strip()
    if source == "companies_house" or jurisdiction == "UK":
        return "Companies House"
    if source == "mauritius_mns" or jurisdiction == "Mauritius":
        return "Mauritius MNS registry"
    return ""


def _format_incorporation_fact(row: dict[str, Any]) -> str:
    label = (row.get("incorporation_age_label") or "").strip()
    raw = (row.get("incorporation_date") or "").strip()
    if label:
        return f"Incorporated {label} (registry date)"
    if raw:
        return f"Incorporation date on registry: {raw}"
    return ""


def build_registry_facts(row: dict[str, Any]) -> list[str]:
    """High-confidence facts from registry fields only."""
    facts: list[str] = []
    jurisdiction = (row.get("jurisdiction") or "UK").strip()
    entity = format_entity_label(row.get("entity_type") or "", jurisdiction)
    if jurisdiction:
        facts.append(f"{jurisdiction}: {entity}")

    inc = _format_incorporation_fact(row)
    if inc:
        facts.append(inc)

    sic = (row.get("sic_codes") or "").strip()
    if sic and sic != "—":
        facts.append(f"SIC / activity codes on registry: {sic}")

    status = (row.get("status") or "").strip()
    if status:
        facts.append(f"Internal workflow status: {status}")

    source = _registry_source_label(row)
    if source:
        facts.append(f"Source register: {source}")

    return facts


def build_intelligence_signals(row: dict[str, Any]) -> list[str]:
    """Medium-confidence indicators derived from observable registry/name/SIC heuristics."""
    signals: list[str] = []
    tags = row.get("why_tags") or []
    tag_l = " ".join(t.lower() for t in tags)

    if "financial sic" in tag_l:
        signals.append("SIC classification aligns with financial-services activity (UK registry)")
    if "payments / fintech" in tag_l or row.get("is_fintech_payment"):
        signals.append("Company name contains payments or fintech-related terms")
    if "cross-border" in tag_l:
        signals.append("Company name contains cross-border or international terms")
    if "capital / investment" in tag_l:
        signals.append("Company name contains capital or investment-related terms")
    if "management / corporate" in tag_l:
        signals.append("Company name suggests a corporate services / management profile")
    if "mauritius gbc" in tag_l:
        signals.append("Mauritius GBC or authorised company entity type on registry")

    age_days = row.get("incorporation_age_days")
    if isinstance(age_days, int) and age_days <= 14 and not any(
        s.startswith("Incorporated") for s in signals
    ):
        signals.insert(0, f"Incorporated within the last 14 days ({age_days} days on registry)")

    return signals[:6]


def build_arie_relevance(row: dict[str, Any]) -> list[str]:
    """Low-confidence commercial interpretation — hedged, never stated as fact."""
    points: list[str] = []
    tags = row.get("why_tags") or []
    tag_l = " ".join(t.lower() for t in tags)
    jurisdiction = (row.get("jurisdiction") or "").strip()

    if row.get("is_fintech_payment") or "payments / fintech" in tag_l:
        points.append(
            "Structure and classification may indicate future cross-border payment requirements."
        )
    if "financial sic" in tag_l:
        points.append(
            "Financial-services classification may align with operational banking onboarding review."
        )
    if "cross-border" in tag_l or "capital / investment" in tag_l:
        points.append(
            "Naming patterns may suggest international trading or investment-related activity."
        )
    if jurisdiction == "Mauritius" and (
        "mauritius gbc" in tag_l or (row.get("entity_type") or "").strip()
    ):
        if not any("mauritius" in p.lower() for p in points):
            points.append(
                "Mauritius entity profile may involve cross-border corporate servicing needs."
            )
    if "management / corporate" in tag_l:
        points.append(
            "Profile may reflect corporate services activity — confirm direct client vs introducer."
        )

    return points[:3]


def build_strategic_hint(row: dict[str, Any]) -> str:
    """Single table-line interpretation; empty when nothing substantive to say."""
    relevance = build_arie_relevance(row)
    return relevance[0] if relevance else ""


def build_intelligence_summary(row: dict[str, Any]) -> str:
    """Concise factual summary for the queue table (registry layer only)."""
    facts = build_registry_facts(row)
    if not facts:
        return "Registry profile available — verify on source register."
    primary = facts[0]
    inc = next((f for f in facts if f.startswith("Incorporated") or "Incorporation date" in f), "")
    if inc and inc != primary:
        return f"{primary}. {inc}."
    if len(facts) > 1 and facts[1] != inc:
        return f"{primary}. {facts[1]}."
    return f"{primary}."


def build_why_summary(tags: list[str], company_name: str, lead_type: str) -> str:
    """Legacy summary field — aligned with intelligence narrative."""
    if lead_type == "introducer":
        return "Corporate services profile — confirm direct client vs introducer."
    row = {
        "why_tags": tags,
        "jurisdiction": "UK",
        "entity_type": "",
        "company_name": company_name,
        "incorporation_age_days": "",
    }
    return build_intelligence_summary(row)


def build_prospect_reason(row: dict[str, Any]) -> str:
    """Operator-facing pursuit narrative (alias of intelligence summary)."""
    return build_intelligence_summary(row)


def _short_signal_for_table(signal: str) -> str:
    mapping = {
        "SIC classification aligns with financial-services activity (UK registry)": (
            "Financial-services SIC on registry"
        ),
        "Company name contains payments or fintech-related terms": (
            "Payments/fintech terms in company name"
        ),
        "Company name contains cross-border or international terms": (
            "Cross-border terms in company name"
        ),
        "Company name contains capital or investment-related terms": (
            "Investment-related terms in company name"
        ),
        "Company name suggests a corporate services / management profile": (
            "Corporate services naming pattern"
        ),
        "Mauritius GBC or authorised company entity type on registry": (
            "Mauritius GBC/AC entity type on registry"
        ),
    }
    for long, short in mapping.items():
        if signal == long:
            return short
    if signal.startswith("Incorporated within the last"):
        return signal.replace(" days on registry)", " on registry)")
    return signal


def build_table_intelligence_bullets(row: dict[str, Any], max_items: int = 3) -> list[str]:
    """Compact factual bullets for the table column."""
    bullets: list[str] = []
    jurisdiction = (row.get("jurisdiction") or "").strip()
    entity = (row.get("entity_type") or "").strip()
    if jurisdiction and entity:
        bullets.append(f"{jurisdiction} · {format_entity_label(entity, jurisdiction)}")
    sic = (row.get("sic_codes") or "").strip()
    if sic and sic != "—" and jurisdiction == "UK":
        code = sic.split(",")[0].strip()
        bullets.append(f"SIC {code} on registry")
    for signal in row.get("intelligence_signals") or []:
        if len(bullets) >= max_items:
            break
        short = _short_signal_for_table(signal)
        if short and short not in bullets:
            bullets.append(short)
    if len(bullets) < max_items:
        for fact in row.get("registry_facts") or []:
            if len(bullets) >= max_items:
                break
            if fact.startswith("Incorporated"):
                bullets.append(fact.replace(" (registry date)", ""))
                break
    return bullets[:max_items]


def ensure_verify_url(row: dict[str, Any]) -> str:
    url = (row.get("verify_url") or "").strip()
    num = (row.get("company_number") or "").strip()
    if url:
        return url
    if num:
        return f"{CH_PROFILE_BASE}{num}"
    return ""


def enrich_row(row: dict[str, Any], raw_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Add computed intelligence fields to a lead row. Never invents contact data."""
    raw = raw_data or {}
    if not raw and row.get("sic_codes"):
        raw = {"sic_codes": [s.strip() for s in str(row["sic_codes"]).split(",") if s.strip()]}

    record = row_to_record(row)
    score_f = float(compute_fit_score(record))
    row["score"] = score_f

    sic = row.get("sic_codes") or format_sic_codes(raw)
    row["sic_codes"] = sic

    lead_type, reason = classify_lead_type(row.get("company_name", ""))
    row["lead_type"] = lead_type
    row["lead_type_reason"] = reason

    row["priority"] = priority_from_score(score_f)
    row["verify_url"] = ensure_verify_url(row)

    row["contact_email"] = row.get("contact_email") or ""
    row["linkedin_company"] = row.get("linkedin_company") or ""
    row["phone_number"] = row.get("phone_number") or ""

    if not row["contact_email"]:
        row["contact_email_status"] = ENRICHMENT_PLACEHOLDER
    else:
        row["contact_email_status"] = ""

    if not row["linkedin_company"]:
        row["linkedin_company_status"] = ENRICHMENT_PLACEHOLDER
    else:
        row["linkedin_company_status"] = ""

    row["is_fintech_payment"] = is_fintech_payment_lead(
        row.get("company_name", ""), sic
    )

    age_label, age_days = incorporation_age(row.get("incorporation_date"))
    row["incorporation_age_label"] = age_label
    row["incorporation_age_days"] = age_days if age_days is not None else ""

    tags = build_why_tags(
        row.get("company_name", ""),
        sic,
        lead_type,
        age_days if isinstance(age_days, int) else None,
        jurisdiction=row.get("jurisdiction") or "",
    )
    row["why_tags"] = tags
    row["why_summary"] = build_why_summary(tags, row.get("company_name", ""), lead_type)
    row["registry_facts"] = build_registry_facts(row)
    row["intelligence_signals"] = build_intelligence_signals(row)
    row["arie_relevance"] = build_arie_relevance(row)
    row["strategic_hint"] = build_strategic_hint(row)
    row["intelligence_summary"] = build_intelligence_summary(row)
    row["prospect_reason"] = row["intelligence_summary"]

    row["table_intelligence_bullets"] = build_table_intelligence_bullets(row)

    from uk_leads.dashboard import dashboard_tabs_for_lead
    from uk_leads.score_explain import build_score_breakdown
    from uk_leads.signals import compute_signals

    sig = compute_signals(row)
    row["strengths"] = sig["strengths"]
    row["cautions"] = sig["cautions"]
    row["score_breakdown"] = build_score_breakdown(row)
    row["dashboard_tabs"] = dashboard_tabs_for_lead(row)

    # Future fields — explicit placeholders
    for field in OUTREACH_EXTENSION_FIELDS:
        row.setdefault(field, "")

    return row


def enrich_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [enrich_row(dict(r)) for r in rows]


def compute_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    high = sum(1 for r in rows if r.get("priority") == "High")
    fintech = sum(1 for r in rows if r.get("is_fintech_payment"))
    assigned = sum(1 for r in rows if (r.get("assigned_to") or "").strip())
    return {
        "total_companies": total,
        "high_priority": high,
        "fintech_payment_leads": fintech,
        "assigned_leads": assigned,
    }
