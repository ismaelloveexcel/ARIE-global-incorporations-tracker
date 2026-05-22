"""PR2: export hygiene, snapshot freshness, read-only assignment merge."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from uk_leads.assignments import ASSIGNMENTS_FILE
from uk_leads.data_loader import merge_leads_for_date
from uk_leads.data_status import get_data_status

PIPELINE_HEADER = (
    "company_name,normalized_name,jurisdiction,entity_type,incorporation_date,"
    "score,source,company_number,file_no,sic_codes\n"
)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    exports = tmp_path / "exports"
    exports.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.chdir(tmp_path)
    return exports


@pytest.fixture
def client():
    return TestClient(app)


def _write_snapshot(exports: Path, date: str, extra_rows: str = "") -> None:
    exports.joinpath(f"{date}.csv").write_text(
        PIPELINE_HEADER
        + "UK Alpha Ltd,uk alpha,UK,ltd,2026-05-20,80,companies_house,10000001,,64209\n"
        + "UK Beta Ltd,uk beta,UK,ltd,2026-05-20,55,companies_house,10000002,,70100\n"
        + "MU GBC Co,mu gbc,Mauritius,GLOBAL BUSINESS COMPANY,2026-05-20,70,mauritius_mns,,C1,\n"
        + extra_rows,
        encoding="utf-8",
    )


def test_get_leads_does_not_mutate_assignments(workspace, client):
    _write_snapshot(workspace, "2026-05-20")
    ASSIGNMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ASSIGNMENTS_FILE.write_text(json.dumps({"leads": {}}), encoding="utf-8")

    r1 = client.get("/api/leads", params={"incorporation_date": "2026-05-20"})
    assert r1.status_code == 200
    assert all(not (x.get("assigned_to") or "").strip() for x in r1.json()["leads"])

    after_first = ASSIGNMENTS_FILE.read_text(encoding="utf-8")
    r2 = client.get("/api/leads", params={"incorporation_date": "2026-05-20"})
    assert r2.status_code == 200
    assert ASSIGNMENTS_FILE.read_text(encoding="utf-8") == after_first


def test_mauritius_payload_hygiene(workspace):
    _write_snapshot(workspace, "2026-05-20")
    rows, _ = merge_leads_for_date("2026-05-20")
    mu = next(r for r in rows if r.get("source") == "mauritius_mns")

    assert mu.get("company_number") in ("", None)
    assert mu.get("file_no") == "C1"
    assert mu.get("sic_codes") in ("", None)
    assert "—" not in json.dumps(mu)
    assert "website_domain" not in mu


def test_stale_banner_for_selected_date(workspace):
    date = "2026-05-18"
    path = workspace / f"{date}.csv"
    _write_snapshot(workspace, date)

    old = datetime.now(timezone.utc) - timedelta(hours=48)
    ts = old.timestamp()
    os.utime(path, (ts, ts))

    status = get_data_status(date)
    banner = status["banner"]
    assert banner["type"] == "amber"
    assert "stale" in banner["message"].lower()
    assert "Last successful update" in banner["message"]


def test_pr1_no_website_domain_regression(workspace, client):
    _write_snapshot(workspace, "2026-05-20")
    res = client.get("/api/leads", params={"incorporation_date": "2026-05-20"})
    assert res.status_code == 200
    for lead in res.json()["leads"]:
        assert "website_domain" not in lead
