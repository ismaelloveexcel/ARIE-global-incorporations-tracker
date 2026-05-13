"""
tests/test_normalization.py
────────────────────────────
Unit tests for normalization/schema.py
"""
import pytest

from normalization.schema import CompanyRecord, normalize_name


class TestNormalizeName:
    def test_strips_ltd(self):
        assert normalize_name("Acme Ltd") == "acme"

    def test_strips_limited(self):
        assert normalize_name("Alpha Holdings Limited") == "alpha holdings"

    def test_strips_llc(self):
        assert normalize_name("GLOBAL FINTECH LLC") == "global fintech"

    def test_strips_gbc(self):
        assert normalize_name("Beta Capital GBC") == "beta capital"

    def test_strips_inc_with_period(self):
        assert normalize_name("Delta Payments Inc.") == "delta payments"

    def test_strips_trust(self):
        assert normalize_name("Gamma Trust") == "gamma"

    def test_unicode_normalisation(self):
        # Accented characters should be folded to ASCII
        result = normalize_name("Société Générale Ltd")
        assert "socit" in result or "societe" in result or "sociale" in result

    def test_collapses_whitespace(self):
        assert normalize_name("  Alpha   Beta  Ltd  ") == "alpha beta"

    def test_lowercase(self):
        result = normalize_name("UPPER CASE LTD")
        assert result == result.lower()

    def test_empty_string(self):
        assert normalize_name("") == ""

    def test_iterative_stripping(self):
        # "Ltd" stripped first, then "limited" suffix if still present
        result = normalize_name("Omega Limited Ltd")
        assert result == "omega"


class TestCompanyRecord:
    def test_normalized_name_populated_on_init(self):
        rec = CompanyRecord(
            company_name="Acme Fintech Ltd.",
            jurisdiction="UK",
            source="companies_house",
        )
        assert rec.normalized_name == "acme fintech"

    def test_to_db_dict_contains_required_keys(self):
        rec = CompanyRecord(
            company_name="Test Co Ltd",
            jurisdiction="UK",
            source="companies_house",
            entity_type="private limited company",
            incorporation_date="2024-01-01",
            raw_data={"sic_codes": ["64990"]},
        )
        d = rec.to_db_dict()
        for key in [
            "company_name",
            "normalized_name",
            "jurisdiction",
            "entity_type",
            "incorporation_date",
            "score",
            "source",
            "raw_data",
            "canonical_entity_id",
        ]:
            assert key in d, f"Missing key: {key}"

    def test_score_defaults_to_none(self):
        rec = CompanyRecord(
            company_name="Test Co",
            jurisdiction="UK",
            source="companies_house",
        )
        assert rec.score is None

    def test_canonical_entity_id_defaults_to_none(self):
        rec = CompanyRecord(
            company_name="Test Co",
            jurisdiction="UK",
            source="companies_house",
        )
        assert rec.canonical_entity_id is None
