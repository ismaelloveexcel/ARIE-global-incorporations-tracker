"""Tests for on-demand Mauritius snapshot merge."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from normalization.schema import CompanyRecord
from uk_leads.mauritius_snapshot import (
    pipeline_has_mauritius_rows,
    refresh_mauritius_for_date,
    should_auto_fetch_mauritius,
)


@pytest.fixture
def exports_dir(tmp_path, monkeypatch):
    exports = tmp_path / "exports"
    exports.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.chdir(tmp_path)
    return exports


def test_should_auto_fetch_when_no_mauritius_rows(exports_dir):
    assert should_auto_fetch_mauritius("2026-05-16") is True


def test_should_not_auto_fetch_when_rows_present(exports_dir):
    path = exports_dir / "2026-05-16.csv"
    path.write_text(
        "source,company_name,score\nmauritius_mns,Test GBC,55\n",
        encoding="utf-8",
    )
    assert pipeline_has_mauritius_rows("2026-05-16") is True
    assert should_auto_fetch_mauritius("2026-05-16") is False


@patch("uk_leads.mauritius_snapshot.mns_connector.fetch_new_incorporations")
def test_refresh_merges_mauritius_preserves_uk(mock_fetch, exports_dir):
    path = exports_dir / "2026-05-16.csv"
    path.write_text(
        "source,company_name,score,jurisdiction\n"
        "companies_house,UK Co,80,UK\n",
        encoding="utf-8",
    )

    record = CompanyRecord(
        company_name="MU Co",
        jurisdiction="Mauritius",
        entity_type="GBC",
        incorporation_date="2026-05-16",
        source="mauritius_mns",
        raw_data={"file_no": "MU1"},
    )
    mock_fetch.return_value = [record]

    with patch("uk_leads.mauritius_snapshot.scorer.score", return_value=60.0):
        result = refresh_mauritius_for_date("2026-05-16")

    assert result["outcome"] == "OK"
    assert result["mauritius_exported"] == 1
    text = path.read_text(encoding="utf-8")
    assert "companies_house" in text
    assert "mauritius_mns" in text
    assert should_auto_fetch_mauritius("2026-05-16") is False
