"""Serve operator index.html with production-safe DOM (no engineering controls in HTML)."""
from __future__ import annotations

from pathlib import Path

from uk_leads.app_mode import is_production

_STATIC = Path(__file__).parent / "static"
_INDEX_PATH = _STATIC / "index.html"


def _strip_block(html: str, start: str, end: str) -> str:
    while True:
        i = html.find(start)
        if i < 0:
            break
        j = html.find(end, i)
        if j < 0:
            break
        html = html[:i] + html[j + len(end) :]
    return html


def render_index_html() -> str:
    html = _INDEX_PATH.read_text(encoding="utf-8")
    production = is_production()
    html = html.replace("{{ENV_BADGE}}", "LIVE SNAPSHOT" if production else "DEV MODE")
    html = html.replace(
        "{{ENV_BADGE_CLASS}}",
        "env-badge--live" if production else "env-badge--dev",
    )
    if production:
        html = _strip_block(html, "<!--@DEV_ONLY:START-->", "<!--@DEV_ONLY:END-->")
    else:
        html = html.replace("<!--@DEV_ONLY:START-->", "").replace(
            "<!--@DEV_ONLY:END-->", ""
        )
    return html
