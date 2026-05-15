"""Tests for rule-based commercial signals."""
from uk_leads.signals import compute_signals


def test_fintech_strength():
    row = {
        "company_name": "London Payments Ltd",
        "sic_codes": "64191",
        "lead_type": "direct",
        "score": 75,
        "incorporation_age_days": 3,
        "website_domain": "example.com",
    }
    sig = compute_signals(row)
    assert any("fintech" in s.lower() or "payments" in s.lower() for s in sig["strengths"])


def test_no_website_caution():
    row = {
        "company_name": "ABC Holdings Ltd",
        "sic_codes": "99999",
        "lead_type": "direct",
        "score": 40,
        "website_domain": "",
    }
    sig = compute_signals(row)
    assert any("website" in c.lower() for c in sig["cautions"])


def test_officer_count_caution():
    row = {
        "company_name": "Big Board Ltd",
        "sic_codes": "",
        "lead_type": "direct",
        "score": 50,
        "website_domain": "bigboard.com",
    }
    sig = compute_signals(row, officer_count=7)
    assert any("officers" in c.lower() for c in sig["cautions"])
