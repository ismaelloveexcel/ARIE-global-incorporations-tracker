"""
normalization/schema.py
────────────────────────
Unified company record dataclass and name-normalisation utilities.

All connectors produce a ``CompanyRecord`` before the record is handed
to the scoring engine or written to the database.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

# Suffixes to strip when building normalised_name for deduplication.
# Order matters: longer multi-word variants must appear first.
_SUFFIX_PATTERN = re.compile(
    r"\b("
    r"public limited company|limited liability partnership|limited liability company"
    r"|limited partnership|private limited company"
    r"|authorised company"
    r"|incorporated|corporation|company"
    r"|plc|llp|llc|ltd|limited|inc|corp|co"
    r"|gbc|spv|holdings|foundation|trust"
    r")\b\.?$",
    re.IGNORECASE,
)

# Characters that are not alphanumeric or whitespace.
_PUNCT_PATTERN = re.compile(r"[^\w\s]")


def normalize_name(name: str) -> str:
    """
    Return a canonical representation of *name* for deduplication:

    1. Unicode NFKD normalisation → ASCII fold
    2. Lower-case
    3. Remove punctuation
    4. Collapse internal whitespace
    5. Strip legal-entity suffixes (iteratively until stable)
    """
    # 1. Unicode → ASCII
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = nfkd.encode("ascii", "ignore").decode("ascii")

    # 2. Lower-case
    lower = ascii_name.lower()

    # 3. Remove punctuation (replace with space to avoid concatenating words)
    no_punct = _PUNCT_PATTERN.sub(" ", lower)

    # 4. Collapse whitespace (before suffix loop for clean boundary matching)
    cleaned = re.sub(r"\s+", " ", no_punct).strip()

    # 5. Strip suffixes iteratively until the name stabilises
    prev = None
    while cleaned != prev:
        prev = cleaned
        cleaned = _SUFFIX_PATTERN.sub("", cleaned).strip().rstrip(",").strip()
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned


@dataclass
class CompanyRecord:
    """
    Unified schema for a company record from any jurisdiction.

    All fields map 1-to-1 to the ``companies`` table columns.
    ``raw_data`` must hold the original API/scraper payload verbatim so
    the pipeline remains fully auditable.
    """

    company_name: str
    jurisdiction: str                     # 'UK', 'DIFC', 'Mauritius'
    source: str                           # connector identifier string
    raw_data: dict[str, Any] = field(default_factory=dict)

    entity_type: str | None = None        # 'Ltd', 'GBC', 'Authorised Company', …
    incorporation_date: str | None = None  # ISO-8601 date string or None
    sector: str | None = None             # human-readable sector / SIC description
    assigned_to: str | None = None        # downstream CRM assignee (optional)

    # Populated by normalize()
    normalized_name: str = field(init=False, default="")

    # Populated by scoring engine
    score: float | None = None

    # Populated by deduplication pass
    canonical_entity_id: int | None = None

    def __post_init__(self) -> None:
        self.normalized_name = normalize_name(self.company_name)

    def to_db_dict(self) -> dict[str, Any]:
        """Return a dict suitable for direct insertion into the ``companies`` table."""
        return {
            "company_name": self.company_name,
            "normalized_name": self.normalized_name,
            "jurisdiction": self.jurisdiction,
            "entity_type": self.entity_type,
            "incorporation_date": self.incorporation_date,
            "sector": self.sector,
            "assigned_to": self.assigned_to,
            "score": self.score,
            "source": self.source,
            "raw_data": self.raw_data,
            "canonical_entity_id": self.canonical_entity_id,
        }
