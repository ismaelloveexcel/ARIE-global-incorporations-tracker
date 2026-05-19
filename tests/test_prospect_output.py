"""Prospect quality: scoring, reasons, and client-focused copy."""
from uk_leads.enrichment import build_intelligence_summary, build_prospect_reason, enrich_row


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
            "incorporation_date": "2026-05-15",
        }
    )
    reason = row.get("prospect_reason") or ""
    assert "introducer" not in reason.lower()
    assert len(reason) > 10
    assert " · " not in reason
    assert "priority outreach" not in reason.lower()
    assert row.get("registry_facts")
    assert row.get("intelligence_signals") is not None
    assert "Mauritius" in reason or "mauritius" in reason.lower()
    hint = row.get("strategic_hint") or ""
    if hint:
        assert "may" in hint.lower()


def test_intelligence_summary_reads_as_narrative():
    row = enrich_row(
        {
            "company_name": "Harbour Fintech Payments Ltd",
            "jurisdiction": "UK",
            "entity_type": "ltd",
            "source": "companies_house",
            "sic_codes": "64999",
            "incorporation_date": "2026-05-16",
            "score": 75,
        }
    )
    summary = build_intelligence_summary(row)
    assert " · " not in summary
    assert "UK" in summary
    assert "Private Limited Company" in summary or "private limited" in summary.lower()


def test_weak_lead_has_no_speculative_hint():
    row = enrich_row(
        {
            "company_name": "Plain Trading Co Ltd",
            "jurisdiction": "UK",
            "entity_type": "ltd",
            "source": "companies_house",
            "incorporation_date": "2020-01-01",
            "score": 15,
        }
    )
    assert not (row.get("strategic_hint") or "").strip()
    assert not (row.get("arie_relevance") or [])


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
