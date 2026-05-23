"""PR4: operational polish, provenance consistency, queue assignment presentation."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.page_html import render_index_html

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "app.js"
INDEX_HTML = ROOT / "app" / "static" / "index.html"


@pytest.fixture
def development_mode(monkeypatch):
    monkeypatch.setenv("APP_MODE", "development")


def test_loading_copy_in_index():
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "Loading operational intelligence…" in html
    assert "Retrieving incorporation records" not in html


def test_index_operational_notes(development_mode):
    html = render_index_html()
    assert "Prioritisation uses Internal heuristic rankings." in html
    assert "Verification links open Registry verified official registries." in html
    assert "internal heuristic rankings for RM" not in html


def test_introducers_roadmap_caption(development_mode):
    html = render_index_html()
    assert "Introducer Insights" in html
    assert "Partner / Introducer Intelligence" in html


def test_provenance_phrases_standardized_in_app_js():
    js = APP_JS.read_text(encoding="utf-8")
    assert 'heuristic: "Heuristic Signal"' in js
    assert "Internal heuristic / score" not in js
    assert 'registry: "Registry Verified"' in js
    assert 'ai: "AI-Assisted Classification"' in js
    assert 'unavailable: "No Data Available"' in js


def test_empty_state_copy_in_app_js():
    js = APP_JS.read_text(encoding="utf-8")
    assert "No validated operational data available" in js
    assert "Validated operational intelligence is not available for this date." in js
    assert "No candidate entities match the current filters." in js
    assert "Try clearing search or jurisdiction filters." in js


def test_queue_table_hides_rm_names_in_assign_cell():
    js = APP_JS.read_text(encoding="utf-8")
    assert "assign-picker__face" in js
    assert "assign-select--queue" in js
    assert "queueAssignFaceLabel" in js
    assert '>${escapeHtml(name)}</option>' in js
    assert 'face.textContent = assigned ? "Assigned" : "Assign"' in js


def test_detail_panel_keeps_full_assignment_dropdown():
    js = APP_JS.read_text(encoding="utf-8")
    assert 'id="detailAssignee"' in js
    assert "Internal workflow ownership only." in js


def test_no_prototype_wording_in_operator_ui():
    combined = (INDEX_HTML.read_text(encoding="utf-8") + APP_JS.read_text(encoding="utf-8")).lower()
    forbidden = [
        "demo mode",
        "ai-powered",
        "smart scoring",
        "live refresh",
        "test queue",
        "experimental",
    ]
    for phrase in forbidden:
        assert phrase not in combined
