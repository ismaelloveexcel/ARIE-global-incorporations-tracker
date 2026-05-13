"""
tests/test_deduplication.py
────────────────────────────
Unit tests for deduplication/matcher.py
"""
import pytest

from deduplication.matcher import Deduplicator
from normalization.schema import CompanyRecord


class _MockDB:
    """Minimal DB stub that records canonical entity upsert calls."""

    def __init__(self, next_id: int = 200):
        self._next_id = next_id
        self.upserted: list[dict] = []

    def upsert_canonical_entity(self, canonical_name, jurisdiction, date):
        cid = self._next_id
        self._next_id += 1
        self.upserted.append(
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
        # upsert_canonical_entity is called once to update metadata (jurisdictions/dates)
        assert len(mock_db.upserted) == 1
        assert mock_db.upserted[0]["canonical_name"] == "acme fintech"

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
        assert len(mock_db.upserted) == 1

    def test_duplicate_rows_not_double_indexed(self):
        rows = [
            {"normalized_name": "acme", "canonical_entity_id": 101, "jurisdiction": "UK"},
            {"normalized_name": "acme", "canonical_entity_id": 101, "jurisdiction": "UK"},
        ]
        dedup = Deduplicator()
        dedup.load_existing(rows)
        assert len(dedup._index) == 1

    def test_resolve_updates_jurisdiction_on_cross_jurisdiction_match(self):
        """A match in a different jurisdiction should update the canonical entity metadata."""
        dedup = Deduplicator()
        dedup.load_existing(_existing_rows())
        mock_db = _MockDB()

        rec = CompanyRecord(
            company_name="Acme Fintech Ltd",
            jurisdiction="DIFC",   # different jurisdiction from the existing UK entry
            source="difc",
        )
        cid = dedup.resolve(rec, mock_db)
        assert cid == 101
        # upsert_canonical_entity called to merge DIFC jurisdiction into existing entity
        assert len(mock_db.upserted) == 1
        assert mock_db.upserted[0]["jurisdiction"] == "DIFC"
        # In-memory index updated too
        assert "DIFC" in dedup._index["acme fintech"].jurisdictions

    def test_rows_without_canonical_entity_id_skipped(self):
        rows = [
            {"normalized_name": "orphan company", "canonical_entity_id": None, "jurisdiction": "UK"},
        ]
        dedup = Deduplicator()
        dedup.load_existing(rows)
        assert dedup.find_match("orphan company") is None
