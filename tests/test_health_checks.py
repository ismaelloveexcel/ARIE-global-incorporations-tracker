"""Health check regression tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from uk_leads.health import run_health_checks

PIPELINE_HEADER = (
    "company_name,normalized_name,jurisdiction,entity_type,incorporation_date,"
    "score,source,company_number,file_no,sic_codes\n"
)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    exports = tmp_path / "exports"
    exports.mkdir()
    (tmp_path / "data").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "test-key-not-placeholder")
    return exports


def test_health_total_leads_uses_uk_snapshot(workspace, monkeypatch):
    """Regression: total_leads must not reference undefined uk_file."""
    date = "2026-05-21"
    workspace.joinpath(f"{date}.csv").write_text(
        PIPELINE_HEADER
        + "UK Co,uk co,UK,ltd,2026-05-21,50,companies_house,10000001,,64209\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "uk_leads.health.requests.get",
        lambda *a, **k: type("R", (), {"status_code": 200})(),
    )
    result = run_health_checks(date)
    total = next(c for c in result["checks"] if c["id"] == "total_leads")
    assert total["message"] == "1"
