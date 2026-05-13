"""
scoring/engine.py
──────────────────
Scoring engine for company records.

Produces a deterministic score 0–100 based on:
  1. Entity type weight          (primary signal)
  2. Sector / SIC classification (UK only)
  3. Jurisdiction risk weight
  4. Keyword detection in company name

All weights and keyword lists are declared as module-level constants so
they can be audited and adjusted without touching logic.
"""
from __future__ import annotations

import re

from normalization.schema import CompanyRecord

# ─────────────────────────────────────────────────────────────────────────────
# Weight tables  (max contribution shown in comments)
# ─────────────────────────────────────────────────────────────────────────────

# Entity type → base score contribution  (max 40 pts)
ENTITY_TYPE_WEIGHTS: dict[str, float] = {
    # Mauritius
    "global business company": 40,
    "gbc": 40,
    "authorised company": 35,
    # DIFC
    "spv": 38,
    "company limited by shares": 30,
    "limited liability company": 30,
    "llc": 30,
    "branch": 20,
    # UK
    "private limited company": 25,
    "ltd": 25,
    "limited": 25,
    "public limited company": 20,
    "plc": 20,
    "limited liability partnership": 20,
    "llp": 20,
    "limited partnership": 15,
    "lp": 15,
    "unlimited company": 10,
}

# Jurisdiction → risk/relevance weight contribution  (max 20 pts)
JURISDICTION_WEIGHTS: dict[str, float] = {
    "Mauritius": 20,
    "DIFC": 18,
    "UK": 12,
}

# SIC code prefixes → sector contribution  (max 20 pts, UK only)
# Key = string prefix of the 5-digit SIC code
SIC_SECTOR_WEIGHTS: dict[str, float] = {
    "64": 20,   # Financial service activities
    "65": 20,   # Insurance / reinsurance
    "66": 18,   # Auxiliary financial activities
    "62": 15,   # Computer programming / IT
    "63": 15,   # Information service activities
    "70": 12,   # Head offices / management consultancy
    "74": 10,   # Other professional, scientific activities
    "69": 8,    # Legal and accounting
    "68": 6,    # Real estate
}

# Keyword → contribution  (max 20 pts total, capped)
KEYWORD_WEIGHTS: dict[str, float] = {
    r"\bfintech\b": 20,
    r"\bpayments?\b": 18,
    r"\bcrypt(?:o|currency|currencies)\b": 20,
    r"\bblockchain\b": 18,
    r"\bdigital asset\b": 18,
    r"\bdefi\b": 15,
    r"\bweb3\b": 15,
    r"\bnft\b": 12,
    r"\boffshore\b": 15,
    r"\bholdings?\b": 10,
    r"\bcapital\b": 8,
    r"\binvestment\b": 8,
    r"\bventure\b": 8,
    r"\bfund\b": 10,
    r"\binsurance\b": 8,
    r"\bremittance\b": 15,
    r"\bexchange\b": 12,
    r"\blending\b": 10,
    r"\bcustod(?:y|ian)\b": 12,
    r"\bwallet\b": 12,
    r"\bpaytech\b": 18,
    r"\bregtech\b": 15,
}

KEYWORD_MAX: float = 20.0


# ─────────────────────────────────────────────────────────────────────────────
# Scoring logic
# ─────────────────────────────────────────────────────────────────────────────

def _entity_type_score(record: CompanyRecord) -> float:
    if not record.entity_type:
        return 0.0
    key = record.entity_type.strip().lower()
    return ENTITY_TYPE_WEIGHTS.get(key, 0.0)


def _jurisdiction_score(record: CompanyRecord) -> float:
    return JURISDICTION_WEIGHTS.get(record.jurisdiction, 0.0)


def _sic_score(record: CompanyRecord) -> float:
    """Extract SIC codes from raw_data and return the highest sector weight.

    SIC codes are a UK-only classification; non-UK records always score 0.
    """
    if record.jurisdiction != "UK":
        return 0.0

    sic_codes: list[str] = []

    # Companies House API returns sic_codes as a list of strings
    raw_sic = record.raw_data.get("sic_codes") or []
    if isinstance(raw_sic, list):
        sic_codes = [str(s) for s in raw_sic]
    elif isinstance(raw_sic, str):
        sic_codes = [raw_sic]

    best = 0.0
    for sic in sic_codes:
        sic = sic.strip()
        for prefix, weight in SIC_SECTOR_WEIGHTS.items():
            if sic.startswith(prefix):
                best = max(best, weight)
    return best


def _keyword_score(record: CompanyRecord) -> float:
    text = record.company_name.lower()
    total = 0.0
    for pattern, weight in KEYWORD_WEIGHTS.items():
        if re.search(pattern, text, re.IGNORECASE):
            total += weight
    return min(total, KEYWORD_MAX)


def score(record: CompanyRecord) -> float:
    """
    Compute and return the deterministic score for *record* (0–100).

    Component breakdown:
        entity_type   0–40
        jurisdiction  0–20
        sic_sector    0–20
        keywords      0–20
        ──────────────────
        total         0–100
    """
    raw = (
        _entity_type_score(record)
        + _jurisdiction_score(record)
        + _sic_score(record)
        + _keyword_score(record)
    )
    return round(min(raw, 100.0), 2)
