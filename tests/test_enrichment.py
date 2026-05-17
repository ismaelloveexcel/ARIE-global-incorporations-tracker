"""Tests for uk_leads.enrichment."""
from datetime import date, timedelta

from uk_leads.enrichment import (
    build_why_tags,
    classify_lead_type,
    enrich_row,
    incorporation_age,
    priority_from_score,
    probable_website_domain,
)


def test_priority_thresholds():
    assert priority_from_score(75) == "High"
    assert priority_from_score(70) == "High"
    assert priority_from_score(50) == "Medium"
    assert priority_from_score(39) == "Low"


def test_classify_direct_fintech():
    lead_type, _ = classify_lead_type("Alpha Fintech Payments Ltd")
    assert lead_type == "direct"


def test_classify_introducer_trust():
    lead_type, _ = classify_lead_type("Beta Corporate Trust Services Ltd")
    assert lead_type == "introducer"


def test_verify_url_built():
    row = enrich_row({"company_name": "Test Co Ltd", "company_number": "12345678", "score": 50})
    assert "12345678" in row["verify_url"]


def test_no_fake_contact():
    row = enrich_row({"company_name": "Test Co Ltd", "company_number": "1", "score": 10})
    assert row["contact_email"] == ""
    assert "Pending" in row["contact_email_status"]


def test_domain_guess_low_confidence():
    domain, conf = probable_website_domain("Acme Capital Holdings Ltd")
    assert domain.endswith(".co.uk")
    assert conf == "low"


def test_incorporation_age_recent():
    yesterday = (date.today() - timedelta(days=2)).isoformat()
    label, days = incorporation_age(yesterday)
    assert days == 2
    assert "2 days" in label


def test_why_tags_fintech():
    tags = build_why_tags("Alpha Fintech Payments Ltd", "", "direct", 1)
    assert any("fintech" in t.lower() or "Payments" in t for t in tags)


def test_enrich_row_has_why_summary():
    row = enrich_row(
        {
            "company_name": "Crypto Payments Ltd",
            "company_number": "999",
            "incorporation_date": date.today().isoformat(),
            "score": 80,
        }
    )
    assert row["why_summary"]
    assert isinstance(row["why_tags"], list)
    assert len(row["why_tags"]) >= 1


def test_enrich_row_has_score_breakdown():
    row = enrich_row(
        {
            "company_name": "Alpha Capital GBC Ltd",
            "jurisdiction": "Mauritius",
            "entity_type": "GLOBAL BUSINESS COMPANY",
            "source": "mauritius_mns",
            "score": 68,
        }
    )
    bd = row["score_breakdown"]
    assert bd["total"] == 68.0
    assert len(bd["components"]) == 4
    assert row["dashboard_tabs"] == ["direct_clients"]
