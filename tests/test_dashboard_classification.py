"""Dashboard classification, lead_id, and assignment tests."""
from uk_leads.assignments import assign_round_robin
from uk_leads.dashboard import (
    is_direct_client,
    is_introducer,
    is_mauritius_gbc_ac,
    is_mauritius_includable,
    lead_id,
)


def test_uk_is_direct_only():
    row = {"source": "companies_house", "company_name": "Acme Ltd", "entity_type": "ltd"}
    assert is_direct_client(row) is True
    assert is_introducer(row) is False


def test_mu_gbc_management_both():
    row = {
        "source": "mauritius_mns",
        "company_name": "Aura Corporate Management Ltd",
        "entity_type": "AUTHORISED COMPANY",
    }
    assert is_direct_client(row) is True
    assert is_introducer(row) is True


def test_mu_gbc_no_keywords_direct_only():
    row = {
        "source": "mauritius_mns",
        "company_name": "Points Africa Technologies Ltd",
        "entity_type": "GLOBAL BUSINESS COMPANY",
    }
    assert is_direct_client(row) is True
    assert is_introducer(row) is False


def test_mu_domestic_excluded():
    row = {
        "source": "mauritius_mns",
        "company_name": "Domestic Co Ltd",
        "entity_type": "DOMESTIC",
    }
    assert is_mauritius_includable(row) is False
    assert is_direct_client(row) is False
    assert is_introducer(row) is False


def test_lead_id_uk():
    row = {"source": "companies_house", "company_number": "12345678"}
    assert lead_id(row) == "12345678"


def test_lead_id_mu_file_no():
    row = {"source": "mauritius_mns", "file_no": "C123456", "company_name": "Test GBC Ltd"}
    assert lead_id(row) == "mu:C123456"


def test_lead_id_mu_name_fallback():
    row = {
        "source": "mauritius_mns",
        "company_name": "Aura Corporate Services Limited",
        "normalized_name": "aura corporate services",
    }
    assert lead_id(row).startswith("mu:")
    assert "aura" in lead_id(row)


def test_round_robin_direct_pool():
    store = {"counters": {"direct_counter": 0, "introducer_counter": 0}}
    pools = {"direct_clients": ["Ismael", "Tasneem"], "introducers": ["Aisha", "Stephen", "Rajesh"]}
    row = {"source": "companies_house", "company_name": "Foo Ltd"}
    a = assign_round_robin(row, pools, store)
    b = assign_round_robin(row, pools, store)
    assert a == "Ismael"
    assert b == "Tasneem"


def test_round_robin_mu_management_name_uses_direct_pool():
    """MU GBC/AC with introducer-like name — same Direct Clients pool (no auto introducer tab)."""
    store = {"counters": {"direct_counter": 0, "introducer_counter": 0}}
    pools = {"direct_clients": ["Ismael", "Tasneem"], "introducers": ["Aisha", "Stephen", "Rajesh"]}
    row = {
        "source": "mauritius_mns",
        "company_name": "Alpha Management GBC Ltd",
        "entity_type": "GBC",
    }
    person = assign_round_robin(row, pools, store)
    assert person == "Ismael"


def test_gbc_ac_matching():
    assert is_mauritius_gbc_ac("GLOBAL BUSINESS COMPANY") is True
    assert is_mauritius_gbc_ac("AUTHORISED COMPANY") is True
    assert is_mauritius_gbc_ac("DOMESTIC") is False
