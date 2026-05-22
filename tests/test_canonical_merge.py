"""PR1: operator queue must reflect exports/{date}.csv only."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from uk_leads.data_loader import (
    merge_leads_for_date,
    scan_available_dates,
    uk_pipeline_export_stats,
)


@pytest.fixture
def exports_dir(tmp_path, monkeypatch):
    exports = tmp_path / "exports"
    exports.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.chdir(tmp_path)
    return exports


PIPELINE_HEADER = (
    "company_name,normalized_name,jurisdiction,entity_type,incorporation_date,"
    "score,source,company_number,file_no,sic_codes\n"
)


def test_merge_uk_and_mauritius_from_pipeline_only(exports_dir):
    path = exports_dir / "2026-05-20.csv"
    path.write_text(
        PIPELINE_HEADER
        + "UK Alpha Ltd,uk alpha,UK,ltd,2026-05-20,80,companies_house,10000001,,64209\n"
        + "UK Beta Ltd,uk beta,UK,ltd,2026-05-20,55,companies_house,10000002,,70100\n"
        + "MU GBC Co,mu gbc,Mauritius,GLOBAL BUSINESS COMPANY,2026-05-20,70,mauritius_mns,,C1,\n"
        + "MU Domestic Ltd,mu domestic,Mauritius,DOMESTIC COMPANY,2026-05-20,30,mauritius_mns,,C2,\n",
        encoding="utf-8",
    )

    rows, meta = merge_leads_for_date("2026-05-20")

    assert meta["uk_count"] == 2
    assert meta["mauritius_count"] == 1
    assert len(rows) == 3
    jurisdictions = {r["jurisdiction"] for r in rows}
    assert jurisdictions == {"UK", "Mauritius"}
    assert meta["uk_path"] == meta["mauritius_path"]
    assert path.samefile(meta["pipeline_path"])
    assert "uk-leads" not in meta["uk_path"]


def test_merge_empty_when_pipeline_missing(exports_dir):
    rows, meta = merge_leads_for_date("2099-01-01")
    assert rows == []
    assert meta["uk_count"] == 0
    assert meta["mauritius_count"] == 0
    assert meta["pipeline_export_missing"] is True


def test_uk_stats_from_pipeline(exports_dir):
    exports_dir.joinpath("2026-05-21.csv").write_text(
        PIPELINE_HEADER
        + "Only UK,only uk,UK,ltd,2026-05-21,50,companies_house,99,,\n",
        encoding="utf-8",
    )
    stats = uk_pipeline_export_stats("2026-05-21")
    assert stats["exists"] is True
    assert stats["row_count"] == 1


def test_date_scan_counts_match_pipeline(exports_dir):
    exports_dir.joinpath("2026-05-15.csv").write_text(
        PIPELINE_HEADER
        + "UK Co,uk co,UK,ltd,2026-05-15,80,companies_house,1,,\n"
        + "MU Co,mu co,Mauritius,GLOBAL BUSINESS COMPANY,2026-05-15,60,mauritius_mns,,F1,\n",
        encoding="utf-8",
    )
    result = scan_available_dates(lookback_days=7)
    by_date = {d["date"]: d for d in result["date_details"]}
    detail = by_date["2026-05-15"]
    assert detail["uk_count"] == 1
    assert detail["mauritius_count"] == 1
    assert detail["has_uk"] is True
    assert detail["has_mauritius"] is True
    assert detail["has_snapshot"] is True


def test_api_leads_404_without_pipeline_export(exports_dir):
    client = TestClient(app)
    response = client.get("/api/leads", params={"incorporation_date": "2099-12-31"})
    assert response.status_code == 404
    detail = response.json()["detail"].lower()
    assert "snapshot" in detail or "pipeline" in detail


def test_api_leads_returns_uk_from_pipeline(exports_dir, monkeypatch):
    exports_dir.joinpath("2026-05-22.csv").write_text(
        PIPELINE_HEADER
        + "CH Lead,ch lead,UK,ltd,2026-05-22,75,companies_house,17221824,,64209\n",
        encoding="utf-8",
    )
    client = TestClient(app)
    response = client.get(
        "/api/leads",
        params={"incorporation_date": "2026-05-22", "tab": "direct_clients"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["metrics"]["uk_count"] == 1
    assert payload["count"] == 1
    assert payload["leads"][0]["company_number"] == "17221824"


def test_refresh_writes_canonical_export_and_queue_reads_it(exports_dir, monkeypatch):
    """Dev UK refresh must write exports/{date}.csv and the queue must read the same rows."""
    from uk_leads.uk_snapshot import refresh_uk_for_date

    fake_uk = [
        {
            "company_name": "Refresh Co Ltd",
            "company_number": "88888888",
            "incorporation_date": "2026-05-24",
            "jurisdiction": "UK",
            "entity_type": "ltd",
            "sic_codes": "64209",
            "score": 72,
            "source": "companies_house",
        }
    ]

    def _fake_fetch(_from, _to, min_score=None, top=None):
        return fake_uk, 1

    monkeypatch.setattr(
        "uk_leads.uk_snapshot.fetch_uk_leads",
        _fake_fetch,
    )

    result = refresh_uk_for_date("2026-05-24")
    path = exports_dir / "2026-05-24.csv"
    assert path.exists()
    assert Path(result["path"]).name == path.name

    rows, meta = merge_leads_for_date("2026-05-24")
    assert meta["uk_count"] == 1
    assert rows[0]["company_name"] == "Refresh Co Ltd"
    assert rows[0]["company_number"] == "88888888"
    assert "website_domain" not in rows[0]

    client = TestClient(app)
    response = client.get(
        "/api/leads",
        params={"incorporation_date": "2026-05-24", "tab": "direct_clients"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["leads"][0]["company_number"] == "88888888"


def test_uk_leads_snapshot_files_ignored(exports_dir):
    """uk-leads-demo must not populate the operator queue when pipeline lacks UK."""
    exports_dir.joinpath("2026-05-23.csv").write_text(
        PIPELINE_HEADER
        + "MU Only,mu only,Mauritius,GLOBAL BUSINESS COMPANY,2026-05-23,65,mauritius_mns,,F9,\n",
        encoding="utf-8",
    )
    exports_dir.joinpath("uk-leads-demo-2026-05-23.csv").write_text(
        "run_date,company_name,company_number,verify_url,incorporation_date,jurisdiction,"
        "entity_type,sic_codes,score,priority,lead_type,lead_type_reason,assigned_to,"
        "source,website_domain,website_domain_confidence,contact_email,linkedin_company,"
        "phone_number,notes\n"
        "2026-05-23,Phantom UK Ltd,99999999,,2026-05-23,UK,ltd,,99,High,direct,,,"
        "companies_house,,,,,,\n",
        encoding="utf-8",
    )

    rows, meta = merge_leads_for_date("2026-05-23")
    assert meta["uk_count"] == 0
    assert meta["mauritius_count"] == 1
    assert all(r.get("jurisdiction") != "UK" or r.get("source") != "companies_house" for r in rows)
    assert not any(r.get("company_name") == "Phantom UK Ltd" for r in rows)
