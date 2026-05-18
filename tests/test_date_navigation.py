"""Date arrows must follow prepared snapshots only."""
from __future__ import annotations

from uk_leads.data_loader import scan_available_dates


def test_operator_dates_are_snapshot_files_only(tmp_path, monkeypatch):
    exports = tmp_path / "exports"
    exports.mkdir()
    monkeypatch.chdir(tmp_path)

    exports.joinpath("2026-05-10.csv").write_text(
        "source,company_name,score\ncompanies_house,Co A,80\n",
        encoding="utf-8",
    )
    exports.joinpath("2026-05-15.csv").write_text(
        "source,company_name,score\ncompanies_house,Co B,70\n",
        encoding="utf-8",
    )

    result = scan_available_dates(demo=False, lookback_days=14)
    assert result["dates"] == ["2026-05-15", "2026-05-10"]
    assert len(result["calendar_dates"]) >= 14
    assert "2026-05-12" in result["calendar_dates"]
    assert "2026-05-12" not in result["dates"]
