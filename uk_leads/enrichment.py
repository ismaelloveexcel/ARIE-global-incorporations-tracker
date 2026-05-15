"""
Lead enrichment and classification — transparent, no fake data.

Future outreach fields are defined here so they can be populated later
without restructuring the app.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

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

    return "direct", "Default: newly incorporated UK company (direct outreach)"


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


def probable_website_domain(company_name: str) -> tuple[str, str]:
    """
    Returns (domain_guess, domain_confidence).
    Heuristic only — not verified. Empty if too uncertain.
    """
    name = company_name or ""
    # Strip legal suffixes
    cleaned = re.sub(
        r"\b(ltd|limited|llp|plc|inc|corp|co|uk)\b\.?",
        "",
        name,
        flags=re.IGNORECASE,
    )
    slug = re.sub(r"[^a-z0-9]+", "", cleaned.lower())
    if len(slug) < 4 or len(slug) > 40:
        return "", "low"
    domain = f"{slug}.co.uk"
    return domain, "low"


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


def build_why_tags(
    company_name: str,
    sic_codes: str,
    lead_type: str,
    incorporation_age_days: int | None,
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
        tags.append("Potential introducer profile")

    if not tags:
        tags.append("New UK incorporation")

    # De-duplicate preserving order
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def build_why_summary(tags: list[str], company_name: str, lead_type: str) -> str:
    """One-line business relevance for stakeholders."""
    if not tags:
        return f"Newly incorporated UK company ({company_name})."
    focus = "introducer / professional services" if lead_type == "introducer" else "direct onboarding"
    joined = "; ".join(tags[:4]).lower()
    return f"Flagged for {focus}: {joined}."


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

    score = row.get("score")
    try:
        score_f = float(score) if score is not None and score != "" else 0.0
    except (TypeError, ValueError):
        score_f = 0.0
    row["score"] = score_f

    sic = row.get("sic_codes") or format_sic_codes(raw)
    row["sic_codes"] = sic

    lead_type, reason = classify_lead_type(row.get("company_name", ""))
    row["lead_type"] = lead_type
    row["lead_type_reason"] = reason

    row["priority"] = priority_from_score(score_f)
    row["verify_url"] = ensure_verify_url(row)

    domain, conf = probable_website_domain(row.get("company_name", ""))
    row["website_domain"] = domain
    row["website_domain_confidence"] = conf if domain else ""

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
    )
    row["why_tags"] = tags
    row["why_summary"] = build_why_summary(tags, row.get("company_name", ""), lead_type)

    from uk_leads.signals import compute_signals

    sig = compute_signals(row)
    row["strengths"] = sig["strengths"]
    row["cautions"] = sig["cautions"]

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
