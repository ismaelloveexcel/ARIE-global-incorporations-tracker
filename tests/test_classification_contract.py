"""Enforce operator queue vs introducer metadata contract (see docs/CLASSIFICATION.md)."""
from uk_leads.dashboard import (
    dashboard_tabs_for_lead,
    filter_tab_leads,
    is_direct_client,
    is_introducer,
)


def _mu_management_row():
    return {
        "source": "mauritius_mns",
        "company_name": "Aura Corporate Management Ltd",
        "entity_type": "AUTHORISED COMPANY",
    }


def test_introducer_tab_filter_returns_introducers():
    rows = [
        _mu_management_row(),
        {"source": "companies_house", "company_name": "Acme Ltd", "entity_type": "ltd"},
    ]
    intro_rows = filter_tab_leads(rows, "introducers")
    assert len(intro_rows) == 1
    assert intro_rows[0]["company_name"] == "Aura Corporate Management Ltd"


def test_direct_tab_includes_mu_management_name_once():
    rows = [_mu_management_row()]
    assert len(filter_tab_leads(rows, "direct_clients")) == 1
    assert is_introducer(rows[0]) is True
    assert is_direct_client(rows[0]) is True


def test_dashboard_tabs_include_introducers_for_introducer_rows():
    assert dashboard_tabs_for_lead(_mu_management_row()) == ["direct_clients", "introducers"]


def test_uk_lead_single_tab():
    row = {"source": "companies_house", "company_name": "Acme Ltd"}
    assert dashboard_tabs_for_lead(row) == ["direct_clients"]
    assert filter_tab_leads([row], "introducers") == []
