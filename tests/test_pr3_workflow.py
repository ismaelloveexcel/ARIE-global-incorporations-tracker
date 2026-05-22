"""PR3: manual assignment, introducers placeholder, no distribute endpoint."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.page_html import render_index_html
from uk_leads.assignments import ASSIGNMENTS_FILE

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
    return exports


@pytest.fixture
def client():
    return TestClient(app)


def _write_snapshot(exports: Path, date: str) -> None:
    exports.joinpath(f"{date}.csv").write_text(
        PIPELINE_HEADER
        + "Fintech Payments Ltd,fintech payments,UK,ltd,2026-05-20,80,companies_house,10000001,,64999\n"
        + "UK Beta Ltd,uk beta,UK,ltd,2026-05-20,55,companies_house,10000002,,70100\n",
        encoding="utf-8",
    )


def test_distribute_endpoint_removed(client):
    res = client.post("/api/distribute", params={"incorporation_date": "2026-05-20"})
    assert res.status_code == 404


def test_manual_assignment_persists(workspace, client):
    _write_snapshot(workspace, "2026-05-20")
    ASSIGNMENTS_FILE.write_text(json.dumps({"leads": {}}), encoding="utf-8")

    patch = client.patch("/api/leads/10000001", json={"assigned_to": "Tasneem"})
    assert patch.status_code == 200

    loaded = client.get("/api/leads", params={"incorporation_date": "2026-05-20"})
    assert loaded.status_code == 200
    by_num = {x["company_number"]: x for x in loaded.json()["leads"]}
    assert by_num["10000001"]["assigned_to"] == "Tasneem"
    assert not (by_num["10000002"].get("assigned_to") or "").strip()

    store = json.loads(ASSIGNMENTS_FILE.read_text(encoding="utf-8"))
    assert store["leads"]["10000001"]["assigned_to"] == "Tasneem"


def test_get_leads_does_not_auto_assign(workspace, client):
    _write_snapshot(workspace, "2026-05-20")
    ASSIGNMENTS_FILE.write_text(json.dumps({"leads": {}}), encoding="utf-8")

    res = client.get("/api/leads", params={"incorporation_date": "2026-05-20"})
    assert res.status_code == 200
    assert all(not (x.get("assigned_to") or "").strip() for x in res.json()["leads"])


def test_queue_metrics_in_api_response(workspace, client):
    _write_snapshot(workspace, "2026-05-20")
    res = client.get("/api/leads", params={"incorporation_date": "2026-05-20"})
    metrics = res.json()["metrics"]
    assert metrics["total_leads"] == 2
    assert metrics["uk_count"] == 2
    assert metrics["high_priority"] >= 1


def test_index_includes_introducers_tab(monkeypatch):
    monkeypatch.setenv("APP_MODE", "development")
    html = render_index_html()
    assert 'id="tabIntroducers"' in html
    assert "Introducer Intelligence Channel" in html
    assert "Introducer Insights" in html
    assert "Partner / Introducer Intelligence" in html
    assert "distributeBtn" not in html
    assert "Distribute queue" not in html


def test_index_includes_queue_summary_and_operational_notes(monkeypatch):
    monkeypatch.setenv("APP_MODE", "development")
    html = render_index_html()
    assert "queue-summary" in html or "queueHeroStats" in html
    assert "Internal heuristic rankings" in html
    assert "Registry verified official registries" in html
