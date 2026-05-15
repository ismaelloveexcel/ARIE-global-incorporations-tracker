"""Unit tests for Mauritius connector helpers (no Playwright)."""
from connectors.mauritius import _category_matches, _column_index_by_header, _dmy_to_iso, _iso_to_dmy
from connectors.mauritius import _row_to_record


def test_iso_to_dmy():
    assert _iso_to_dmy("2026-05-14") == "14/05/2026"


def test_dmy_to_iso():
    assert _dmy_to_iso("14/05/2026") == "2026-05-14"


def test_category_gbc():
    assert _category_matches("Global Business Company")
    assert _category_matches("GBC")


def test_category_authorised():
    assert _category_matches("Authorised Company")
    assert _category_matches("AC")


def test_category_rejects_ltd():
    assert not _category_matches("Domestic Company")


def test_header_mapping():
    headers = ["#", "Name", "File No.", "Category", "Incorporation/ Registration Date", "Nature", "Status"]
    col = _column_index_by_header(headers)
    assert col["company_name"] == 1
    assert col["file_no"] == 2
    assert col["incorporation_date"] == 4


def test_row_to_record():
    rec = _row_to_record(
        {
            "company_name": "Alpha Holdings GBC Ltd",
            "file_no": "C123456",
            "entity_type": "Global Business Company",
            "incorporation_date": "14/05/2026",
            "nature": "Trading",
            "company_status": "Active",
        }
    )
    assert rec is not None
    assert rec.jurisdiction == "Mauritius"
    assert rec.source == "mauritius_mns"
    assert rec.incorporation_date == "2026-05-14"
    assert rec.raw_data["file_no"] == "C123456"
