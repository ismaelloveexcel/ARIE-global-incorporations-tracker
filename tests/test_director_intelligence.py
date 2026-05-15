"""Tests for director appointment summaries and network signals."""
from uk_leads.director_intelligence import (
    compute_director_network_signals,
    summarize_appointments,
)


def _appt(company_number: str, status: str = "active", resigned: str = "", year: str = "2020-01-01"):
    return {
        "appointed_on": year,
        "resigned_on": resigned,
        "appointed_to": {
            "company_number": company_number,
            "company_name": f"Co {company_number}",
            "company_status": status,
        },
    }


def test_summarize_active_and_dissolved():
    items = [
        _appt("111", "active", "", "2022-03-01"),
        _appt("444", "active", "", "2021-01-01"),
        _appt("222", "dissolved", "", "2019-01-01"),
        _appt("333", "active", "2021-06-01", "2018-01-01"),
    ]
    profile = summarize_appointments(items)
    assert profile["active_appointments"] == 2
    assert profile["dissolved_appointments"] == 2
    assert profile["first_appointment_year"] == 2018
    assert profile["multiple_current_companies"] is True


def test_high_dissolved_ratio_caution():
    officers = [
        {
            "name": "Jane Smith",
            "director_profile": {
                "active_appointments": 1,
                "dissolved_appointments": 4,
                "active_dissolved_ratio": 0.2,
                "first_appointment_year": 2015,
                "multiple_current_companies": False,
                "active_company_numbers": ["999"],
            },
        }
    ]
    sig = compute_director_network_signals(officers, "100", {"200", "300"})
    assert any("dissolved" in c.lower() for c in sig["cautions"])


def test_repeat_director_across_leads():
    officers = [
        {
            "name": "John Doe",
            "director_profile": {
                "active_appointments": 2,
                "dissolved_appointments": 0,
                "active_dissolved_ratio": 1.0,
                "first_appointment_year": 2020,
                "multiple_current_companies": True,
                "active_company_numbers": ["100", "200"],
            },
        }
    ]
    sig = compute_director_network_signals(officers, "100", {"200", "300"})
    assert any("other lead" in c.lower() for c in sig["cautions"])


def test_finance_heavy_strength():
    officers = [
        {
            "name": "Alex Lee",
            "director_profile": {
                "active_appointments": 3,
                "dissolved_appointments": 0,
                "finance_heavy_portfolio": True,
                "multiple_current_companies": True,
                "active_company_numbers": ["1", "2", "3"],
            },
        }
    ]
    sig = compute_director_network_signals(officers, "1", set())
    assert any("financial" in s.lower() for s in sig["strengths"])
