"""Rule-based strengths and caution points (not compliance decisions)."""
from __future__ import annotations

import re
from typing import Any

from uk_leads.enrichment import (
    _CAPITAL_PATTERNS,
    _CROSS_BORDER_PATTERNS,
    _FINTECH_PAYMENT_PATTERNS,
    _INTRODUCER_PATTERNS,
    _sic_financial,
    build_why_tags,
    is_fintech_payment_lead,
)

_CRYPTO_CAUTION = [r"\bcrypt", r"\bblockchain\b", r"\bdefi\b", r"\bnft\b"]


def compute_signals(
    row: dict[str, Any],
    officer_count: int | None = None,
    director_signals: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    name = row.get("company_name", "")
    sic = row.get("sic_codes", "")
    lead_type = row.get("lead_type", "direct")
    text = name.lower()
    strengths: list[str] = []
    cautions: list[str] = []

    age_days = row.get("incorporation_age_days")
    if isinstance(age_days, str) and age_days.isdigit():
        age_days = int(age_days)
    if isinstance(age_days, int) and age_days <= 7:
        strengths.append(f"Incorporated within 7 days ({age_days} days on registry)")

    if is_fintech_payment_lead(name, sic):
        strengths.append("Payments/fintech terms or financial-sector SIC present (name/SIC heuristic)")

    if _sic_financial(sic):
        strengths.append("Financial-services SIC recorded on UK registry")

    for pat in _CAPITAL_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            strengths.append("Capital or investment terms present in company name")
            break

    for pat in _CROSS_BORDER_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            strengths.append("Cross-border or international terms present in company name")
            break

    if lead_type == "introducer":
        strengths.append("Name pattern matches corporate services / management profile")

    if float(row.get("score") or 0) >= 70:
        strengths.append("Rule-based fit score ≥70 (deterministic scoring model)")

    cautions.append("No verified website on file — digital footprint not confirmed")

    for pat in _CRYPTO_CAUTION:
        if re.search(pat, text, re.IGNORECASE):
            cautions.append("Crypto / digital-asset wording — extra onboarding review suggested")
            break

    if officer_count is not None and officer_count >= 6:
        cautions.append(
            f"{officer_count} officers listed — unusually large board for a new company; confirm structure"
        )

    if not strengths and float(row.get("score") or 0) < 40:
        cautions.append("Lower fit score — confirm business activity before outreach")

    if director_signals:
        strengths.extend(director_signals.get("strengths") or [])
        cautions.extend(director_signals.get("cautions") or [])

    # de-dupe
    def _uniq(xs: list[str]) -> list[str]:
        seen: set[str] = set()
        out = []
        for x in xs:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    return {"strengths": _uniq(strengths)[:8], "cautions": _uniq(cautions)[:8]}
