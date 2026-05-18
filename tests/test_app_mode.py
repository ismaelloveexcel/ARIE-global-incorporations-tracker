"""PR2: APP_MODE operational boundaries."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from uk_leads import app_mode


@pytest.fixture
def exports_dir(tmp_path, monkeypatch):
    exports = tmp_path / "exports"
    exports.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.chdir(tmp_path)
    return exports


def test_mode_config_production(monkeypatch):
    monkeypatch.setenv("APP_MODE", "production")
    cfg = app_mode.mode_config()
    assert cfg["is_production"] is True
    assert cfg["operator_refresh_allowed"] is False
    assert cfg["show_dev_link"] is False
    assert cfg["default_demo_cap"] is False


def test_mode_config_development(monkeypatch):
    monkeypatch.setenv("APP_MODE", "development")
    cfg = app_mode.mode_config()
    assert cfg["is_production"] is False
    assert cfg["operator_refresh_allowed"] is True
    assert cfg["show_dev_link"] is True


def test_operator_refresh_blocked_in_production(exports_dir, monkeypatch):
    monkeypatch.setenv("APP_MODE", "production")
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "test-key")
    client = TestClient(app)
    res = client.post("/api/refresh", params={"incorporation_date": "2026-05-20"})
    assert res.status_code == 403
    assert "/dev" not in res.json()["detail"].lower()


def test_operator_refresh_allowed_in_development(exports_dir, monkeypatch):
    monkeypatch.setenv("APP_MODE", "development")
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "test-key")
    client = TestClient(app)
    res = client.post("/api/refresh", params={"incorporation_date": "2099-01-01"})
    assert res.status_code != 403


def test_meta_includes_mode(monkeypatch):
    monkeypatch.setenv("APP_MODE", "production")
    client = TestClient(app)
    data = client.get("/api/meta").json()
    assert data["app_mode"] == "production"
    assert data["is_production"] is True
