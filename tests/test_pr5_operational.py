"""PR5: stabilization audit — no dead paths, consistent operational wording."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from app.page_html import render_index_html

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "app.js"


@pytest.fixture
def production_mode(monkeypatch):
    monkeypatch.setenv("APP_MODE", "production")


def test_assignment_pool_for_lead_removed():
    dashboard = importlib.import_module("uk_leads.dashboard")
    assert not hasattr(dashboard, "assignment_pool_for_lead")


def test_no_distribute_endpoint_in_main():
    main = importlib.import_module("app.main")
    paths = {getattr(r, "path", None) for r in main.app.routes}
    assert "/api/distribute" not in paths


def test_production_badge_wording(production_mode):
    html = render_index_html()
    assert "PRODUCTION" in html
    assert "LIVE SNAPSHOT" not in html


def test_readme_operational_sections():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for heading in (
        "## Operational model",
        "## Snapshot lifecycle",
        "## Development vs production",
        "## Manual assignment workflow",
        "## Provenance model",
        "## Recovery when a snapshot is missing",
        "## What this system intentionally does NOT do",
    ):
        assert heading in readme
    assert "no live registry refresh in production" in readme.lower() or "no live registry access in production" in readme.lower()


def test_export_columns_stable_crm_order():
    js = APP_JS.read_text(encoding="utf-8")
    assert '"snapshot_date"' in js
    assert '"verify_url"' in js
    assert "EXPORT_PLACEHOLDERS" in js
    assert '"company_name"' in js
    idx_snapshot = js.index('"snapshot_date"')
    idx_company = js.index('"company_name"')
    assert idx_snapshot < idx_company


def test_operational_audit_no_forbidden_wording():
    ui = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8") + APP_JS.read_text(
        encoding="utf-8"
    )
    lower = ui.lower()
    assert "distributebtn" not in lower
    assert "distribute queue" not in lower
    assert "demo mode" not in lower
    assert "round-robin" not in lower
    assert "live snapshot" not in lower
    assert "live refresh" not in lower
    assert "ai-powered" not in lower
