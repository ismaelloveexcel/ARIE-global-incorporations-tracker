"""
deduplication/matcher.py
─────────────────────────
Fuzzy deduplication using RapidFuzz.

The deduplicator maintains an in-memory index of already-seen
normalised names and uses token-sort-ratio to decide whether an
incoming record matches an existing canonical entity.

Usage
-----
    dedup = Deduplicator(threshold=92)
    dedup.load_existing(db.fetch_all_companies())

    for record in new_records:
        canonical_id = dedup.match_or_create(record, db)
        record.canonical_entity_id = canonical_id
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

from normalization.schema import CompanyRecord

logger = logging.getLogger(__name__)

# Default similarity threshold (0–100).
DEFAULT_THRESHOLD = 92


@dataclass
class _CanonicalEntry:
    """In-memory representation of a canonical entity."""

    canonical_entity_id: int
    canonical_name: str          # normalised name used for matching
    jurisdictions: set[str] = field(default_factory=set)


class Deduplicator:
    """
    Fuzzy deduplication engine.

    Parameters
    ----------
    threshold:
        Minimum RapidFuzz ``token_sort_ratio`` score (0–100) to consider
        two normalised names a match.  Defaults to 92.
    """

    def __init__(self, threshold: int = DEFAULT_THRESHOLD) -> None:
        self.threshold = threshold
        # Maps normalised_name → _CanonicalEntry for fast lookup
        self._index: dict[str, _CanonicalEntry] = {}

    # ─────────────────────────────────────────────────────────────────────────
    # Bootstrap from existing DB rows
    # ─────────────────────────────────────────────────────────────────────────

    def load_existing(self, rows: list[dict[str, Any]]) -> None:
        """
        Populate the in-memory index from previously stored company rows.

        Each *row* dict must contain at least:
        ``normalized_name``, ``canonical_entity_id``, ``jurisdiction``.
        """
        for row in rows:
            if not row.get("canonical_entity_id"):
                continue
            norm = row["normalized_name"]
            cid = row["canonical_entity_id"]
            if norm not in self._index:
                self._index[norm] = _CanonicalEntry(
                    canonical_entity_id=cid,
                    canonical_name=norm,
                    jurisdictions={row.get("jurisdiction", "")},
                )
            else:
                self._index[norm].jurisdictions.add(row.get("jurisdiction", ""))

        logger.info("Deduplicator index loaded with %d entries.", len(self._index))

    # ─────────────────────────────────────────────────────────────────────────
    # Core matching logic
    # ─────────────────────────────────────────────────────────────────────────

    def find_match(self, normalized_name: str) -> _CanonicalEntry | None:
        """
        Return the best-matching canonical entry for *normalized_name*, or
        ``None`` if no entry exceeds the similarity threshold.
        """
        best_score = 0
        best_entry: _CanonicalEntry | None = None

        for key, entry in self._index.items():
            score = fuzz.token_sort_ratio(normalized_name, key)
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_score >= self.threshold:
            logger.debug(
                "Match found: '%s' ↔ '%s' (score=%d)",
                normalized_name,
                best_entry.canonical_name,
                best_score,
            )
            return best_entry

        return None

    def register(self, normalized_name: str, canonical_entity_id: int, jurisdiction: str) -> None:
        """Add a new entry to the in-memory index."""
        if normalized_name in self._index:
            self._index[normalized_name].jurisdictions.add(jurisdiction)
        else:
            self._index[normalized_name] = _CanonicalEntry(
                canonical_entity_id=canonical_entity_id,
                canonical_name=normalized_name,
                jurisdictions={jurisdiction},
            )

    # ─────────────────────────────────────────────────────────────────────────
    # High-level pipeline helper
    # ─────────────────────────────────────────────────────────────────────────

    def resolve(self, record: CompanyRecord, db_module: Any) -> int:
        """
        Resolve *record* to a canonical entity id.

        If a fuzzy match is found in the index the existing id is returned.
        Otherwise a new canonical_entity row is created in the database and
        the index is updated.

        Parameters
        ----------
        record:
            The incoming company record.
        db_module:
            The ``db.supabase_client`` module (or any object that exposes
            ``upsert_canonical_entity``).  Passed as a parameter to keep
            this module easy to unit-test.

        Returns
        -------
        int
            The canonical_entity_id assigned to *record*.
        """
        match = self.find_match(record.normalized_name)
        if match:
            # Update the canonical entity in the DB with the new jurisdiction
            # and sighting date so cross-jurisdiction matches are fully tracked.
            db_module.upsert_canonical_entity(
                canonical_name=match.canonical_name,
                jurisdiction=record.jurisdiction,
                date=record.incorporation_date,
            )
            # Keep the in-memory index consistent.
            match.jurisdictions.add(record.jurisdiction)
            return match.canonical_entity_id

        # Create a new canonical entity
        canonical_id = db_module.upsert_canonical_entity(
            canonical_name=record.normalized_name,
            jurisdiction=record.jurisdiction,
            date=record.incorporation_date,
        )
        self.register(record.normalized_name, canonical_id, record.jurisdiction)
        logger.info(
            "New canonical entity created: '%s' (id=%d)", record.normalized_name, canonical_id
        )
        return canonical_id
