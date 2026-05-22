"""Tests for snapshot date navigation."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from uk_leads.data_loader import scan_available_dates


@pytest.fixture
def exports_dir(tmp_path, monkeypatch):
    exports = tmp_path / "exports"
    exports.mkdir()
    monkeypatch.chdir(tmp_path)
    return exports


def test_scan_includes_lookback_window(exports_dir):
    (exports_dir / "2026-05-15.csv").write_text(
        "source,company_name,score\ncompanies_house,Acme Ltd,80\n",
        encoding="utf-8",
    )
    result = scan_available_dates(lookback_days=7)
    assert "2026-05-15" in result["dates"]
    assert "2026-05-15" in result["snapshot_dates"]
    assert result["dates"] == ["2026-05-15"]
    assert len(result["calendar_dates"]) >= 7
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert yesterday in result["calendar_dates"]
    assert yesterday not in result["dates"]


def test_scan_marks_unloaded_days(exports_dir):
    result = scan_available_dates(lookback_days=3)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert yesterday not in result["dates"]
    assert yesterday in result["calendar_dates"]
