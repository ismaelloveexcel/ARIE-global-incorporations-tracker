"""Production index HTML must not expose engineering controls."""
from __future__ import annotations

import pytest

from app.page_html import render_index_html


@pytest.fixture
def production_mode(monkeypatch):
    monkeypatch.setenv("APP_MODE", "production")


@pytest.fixture
def development_mode(monkeypatch):
    monkeypatch.setenv("APP_MODE", "development")


def test_production_index_omits_engineering_controls(production_mode):
    html = render_index_html()
    assert "LIVE SNAPSHOT" in html
    assert "{{ENV_BADGE}}" not in html
    assert 'id="refreshBtn"' not in html
    assert 'id="devOpsLink"' not in html
    assert 'id="demoMode"' not in html
    assert "muPipelineCmd" not in html
    assert "<!--@DEV_ONLY:" not in html


def test_development_index_includes_engineering_controls(development_mode):
    html = render_index_html()
    assert "DEV MODE" in html
    assert 'id="refreshBtn"' in html
    assert 'id="devOpsLink"' in html


def test_production_index_served_over_http(production_mode):
    from fastapi.testclient import TestClient

    from app.main import app

    html = TestClient(app).get("/").text
    assert "LIVE SNAPSHOT" in html
    assert "{{ENV_BADGE}}" not in html
    assert "DEV_ONLY" not in html
    assert "refreshBtn" not in html
    assert "devOpsLink" not in html
    assert "demoMode" not in html
    assert "muPipelineCmd" not in html
    assert "Previous prepared snapshot" in html
    assert "Export current view" in html
    assert "Corporate Leads Intelligence" in html


def test_production_blocks_dev_routes(production_mode):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.get("/dev").status_code == 404
    assert client.get("/api/dev/health").status_code == 404
    assert client.post("/api/dev/refresh/uk").status_code == 404
