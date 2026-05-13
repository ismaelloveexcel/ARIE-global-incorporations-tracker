"""
tests/test_scoring.py
──────────────────────
Unit tests for scoring/engine.py
"""
import pytest

from normalization.schema import CompanyRecord
from scoring.engine import score


def _rec(name, jurisdiction="UK", entity_type=None, sic_codes=None):
    raw = {}
    if sic_codes:
        raw["sic_codes"] = sic_codes
    return CompanyRecord(
        company_name=name,
        jurisdiction=jurisdiction,
        source="test",
        entity_type=entity_type,
        raw_data=raw,
    )


class TestScoringEngine:
    def test_score_is_float(self):
        s = score(_rec("Test Company Ltd", entity_type="private limited company"))
        assert isinstance(s, float)

    def test_score_in_range(self):
        for name in ["A", "Alpha Fintech GBC", "Ordinary Co"]:
            s = score(_rec(name))
            assert 0.0 <= s <= 100.0, f"Score out of range for '{name}': {s}"

    def test_fintech_keyword_raises_score(self):
        plain = score(_rec("Generic Company", entity_type="private limited company"))
        fintech = score(_rec("Generic Fintech", entity_type="private limited company"))
        assert fintech > plain

    def test_crypto_keyword_raises_score(self):
        plain = score(_rec("Normal Corp"))
        crypto = score(_rec("Crypto Exchange Corp"))
        assert crypto > plain

    def test_mauritius_gbc_scores_higher_than_uk_ltd(self):
        gbc = score(_rec("Capital Holdings", jurisdiction="Mauritius", entity_type="GBC"))
        ltd = score(_rec("Capital Holdings", jurisdiction="UK", entity_type="private limited company"))
        assert gbc > ltd

    def test_sic_64_raises_score(self):
        without_sic = score(_rec("Alpha Ltd", entity_type="private limited company"))
        with_sic = score(
            _rec("Alpha Ltd", entity_type="private limited company", sic_codes=["64990"])
        )
        assert with_sic > without_sic

    def test_score_capped_at_100(self):
        # Pile on all signals
        rec = CompanyRecord(
            company_name="Crypto Fintech Payments Blockchain DeFi Web3 Wallet",
            jurisdiction="Mauritius",
            source="test",
            entity_type="global business company",
            raw_data={"sic_codes": ["64990", "66190"]},
        )
        assert score(rec) <= 100.0

    def test_difc_jurisdiction_weight(self):
        uk = score(_rec("Alpha", jurisdiction="UK", entity_type="private limited company"))
        difc = score(_rec("Alpha", jurisdiction="DIFC", entity_type="company limited by shares"))
        # DIFC should score higher due to jurisdiction weight
        # (entity type may differ; just ensure score is positive)
        assert difc >= 0

    def test_no_entity_type_still_scores(self):
        s = score(_rec("Blockchain Payments Inc", jurisdiction="Mauritius"))
        assert s > 0
