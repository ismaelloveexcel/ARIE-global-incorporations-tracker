"""
tests/test_deduplication.py
────────────────────────────
Unit tests for deduplication/matcher.py
"""
import pytest

from deduplication.matcher import Deduplicator
from normalization.schema import CompanyRecord


class _MockDB:
    """Minimal DB stub that records canonical entity creation calls."""

    def __init__(self, next_id: int = 200):
        self._next_id = next_id
        self.created: list[dict] = []

    def upsert_canonical_entity(self, canonical_name, jurisdiction, date):
        cid = self._next_id
        self._next_id += 1
        self.created.append(
            {"id": cid, "canonical_name": canonical_name, "jurisdiction": jurisdiction}
        )
        return cid


def _existing_rows():
    return [
        {"normalized_name": "acme fintech", "canonical_entity_id": 101, "jurisdiction": "UK"},
        {"normalized_name": "beta payments", "canonical_entity_id": 102, "jurisdiction": "DIFC"},
    ]


class TestDeduplicator:
    def test_load_existing_builds_index(self):
        dedup = Deduplicator()
        dedup.load_existing(_existing_rows())
        assert len(dedup._index) == 2

    def test_exact_match_returns_existing_id(self):
        dedup = Deduplicator()
        dedup.load_existing(_existing_rows())
        match = dedup.find_match("acme fintech")
        assert match is not None
        assert match.canonical_entity_id == 101

    def test_fuzzy_match_same_normalised_name(self):
        dedup = Deduplicator(threshold=92)
        dedup.load_existing(_existing_rows())
        # "acme fintech" == "acme fintech" → score 100
        assert dedup.find_match("acme fintech") is not None

    def test_no_match_for_unrelated_name(self):
        dedup = Deduplicator()
        dedup.load_existing(_existing_rows())
        assert dedup.find_match("totally different company") is None

    def test_register_adds_to_index(self):
        dedup = Deduplicator()
        dedup.register("gamma capital", 999, "Mauritius")
        match = dedup.find_match("gamma capital")
        assert match is not None
        assert match.canonical_entity_id == 999

    def test_resolve_returns_existing_id_on_match(self):
        dedup = Deduplicator()
        dedup.load_existing(_existing_rows())
        mock_db = _MockDB()

        rec = CompanyRecord(
            company_name="Acme Fintech Ltd",
            jurisdiction="UK",
            source="test",
        )
        cid = dedup.resolve(rec, mock_db)
        assert cid == 101
        assert len(mock_db.created) == 0  # No new entity created

    def test_resolve_creates_new_canonical_entity(self):
        dedup = Deduplicator()
        dedup.load_existing(_existing_rows())
        mock_db = _MockDB(next_id=500)

        rec = CompanyRecord(
            company_name="Brand New Holdings GBC",
            jurisdiction="Mauritius",
            source="mauritius_mns",
        )
        cid = dedup.resolve(rec, mock_db)
        assert cid == 500
        assert len(mock_db.created) == 1

    def test_duplicate_rows_not_double_indexed(self):
        rows = [
            {"normalized_name": "acme", "canonical_entity_id": 101, "jurisdiction": "UK"},
            {"normalized_name": "acme", "canonical_entity_id": 101, "jurisdiction": "UK"},
        ]
        dedup = Deduplicator()
        dedup.load_existing(rows)
        assert len(dedup._index) == 1

    def test_rows_without_canonical_entity_id_skipped(self):
        rows = [
            {"normalized_name": "orphan company", "canonical_entity_id": None, "jurisdiction": "UK"},
        ]
        dedup = Deduplicator()
        dedup.load_existing(rows)
        assert dedup.find_match("orphan company") is None
