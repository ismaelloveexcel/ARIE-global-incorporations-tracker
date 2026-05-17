"""Prospect quality: scoring, reasons, and client-focused copy."""
from uk_leads.enrichment import build_prospect_reason, enrich_row


def test_enrich_recomputes_score_not_stale_csv():
    row = enrich_row(
        {
            "company_name": "Global Fintech Payments Ltd",
            "jurisdiction": "UK",
            "entity_type": "private limited company",
            "source": "companies_house",
            "score": 1,
            "sic_codes": "64999",
        }
    )
    assert float(row["score"]) >= 40


def test_prospect_reason_is_client_focused():
    row = enrich_row(
        {
            "company_name": "Atlas International Holdings GBC Ltd",
            "jurisdiction": "Mauritius",
            "entity_type": "GLOBAL BUSINESS COMPANY",
            "source": "mauritius_mns",
            "score": 50,
        }
    )
    reason = row.get("prospect_reason") or ""
    assert "introducer" not in reason.lower()
    assert len(reason) > 10


def test_management_company_scores_as_prospect():
    row = enrich_row(
        {
            "company_name": "Harbour Corporate Management Ltd",
            "jurisdiction": "Mauritius",
            "entity_type": "AUTHORISED COMPANY",
            "source": "mauritius_mns",
        }
    )
    assert float(row["score"]) >= 40
    assert row.get("prospect_reason")
