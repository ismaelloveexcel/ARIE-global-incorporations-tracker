"""PR6: pilot runbook, footer, release consistency."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.page_html import render_index_html

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "app" / "static" / "index.html"
APP_JS = ROOT / "app" / "static" / "app.js"
RUNBOOK = ROOT / "docs" / "PILOT_RUNBOOK.md"


@pytest.fixture
def production_mode(monkeypatch):
    monkeypatch.setenv("APP_MODE", "production")


def test_pilot_runbook_exists():
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "## 1. Morning workflow" in text
    assert "Registry verified" in text
    assert "Internal heuristic" in text
    assert "AI-generated" in text
    assert "## 11. What NOT to assume" in text


def test_footer_in_index():
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="opsFooter"' in html
    assert "Prepared operational snapshot" in html
    assert "Operational Queue v1" in html
    assert "snapshot-first queue" in html


def test_empty_state_wording_in_app_js():
    js = APP_JS.read_text(encoding="utf-8")
    assert "No prepared snapshots available" in js
    assert "No candidate entities match the current filters." in js
    assert "operatorSafeErrorMessage" in js
    assert "try again later" not in js.lower()


def test_release_consistency_production_badge(production_mode):
    html = render_index_html()
    assert "PRODUCTION" in html
    assert "LIVE SNAPSHOT" not in html
    assert "demoMode" not in html


def test_readme_links_runbook_and_port():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "PILOT_RUNBOOK.md" in readme
    assert "8080" in readme
    assert "python -m app.main" in readme


def test_served_ui_forbidden_wording():
    ui = INDEX.read_text(encoding="utf-8") + APP_JS.read_text(encoding="utf-8")
    lower = ui.lower()
    for phrase in ("demo mode", "live snapshot", "live refresh", "ai-powered", "try again later"):
        assert phrase not in lower
