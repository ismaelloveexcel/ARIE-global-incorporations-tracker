"""Developer / ops configuration persisted in data/dev_config.json."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

CONFIG_PATH = Path("data") / "dev_config.json"

DEFAULT_CONFIG: dict = {
    "assignment_pools": {
        "direct_clients": ["Ismael", "Tasneem"],
        "introducers": ["Aisha", "Stephen", "Rajesh"],
    },
    "roadmap": [
        {
            "jurisdiction": "United Kingdom",
            "type": "Direct Clients",
            "status": "Live",
            "status_icon": "✅",
            "source": "Companies House API",
            "notes": "Daily automated",
        },
        {
            "jurisdiction": "Mauritius GBC/AC",
            "type": "Direct Clients",
            "status": "Live",
            "status_icon": "✅",
            "source": "CBRD onlinesearch.mns.mu",
            "notes": "Daily automated",
        },
        {
            "jurisdiction": "Mauritius GBC/AC",
            "type": "Introducers",
            "status": "Live",
            "status_icon": "✅",
            "source": "CBRD onlinesearch.mns.mu",
            "notes": "Daily automated",
        },
        {
            "jurisdiction": "UAE / DIFC",
            "type": "Introducers",
            "status": "Pending",
            "status_icon": "🔄",
            "source": "Access method TBC",
            "notes": "—",
        },
        {
            "jurisdiction": "Gibraltar",
            "type": "Introducers",
            "status": "Pending",
            "status_icon": "🔄",
            "source": "e-Registry (paid sub)",
            "notes": "—",
        },
        {
            "jurisdiction": "United Kingdom",
            "type": "Introducers",
            "status": "Planned",
            "status_icon": "📋",
            "source": "Companies House API",
            "notes": "To be implemented",
        },
    ],
    "implementation_log": {
        "phase_1": [
            {"item": "UK direct client daily feed", "status": "Live", "status_icon": "✅"},
            {"item": "Mauritius GBC/AC direct client daily feed", "status": "Live", "status_icon": "✅"},
            {"item": "Mauritius GBC/AC introducer feed", "status": "Live", "status_icon": "✅"},
            {"item": "UAE/DIFC introducer feed", "status": "Pending", "status_icon": "🔄"},
            {"item": "Gibraltar introducer feed", "status": "Pending", "status_icon": "🔄"},
            {"item": "UK introducer feed", "status": "Planned", "status_icon": "📋"},
        ],
        "phase_2": [
            {"item": "AI calling agent", "status": "Planned", "status_icon": "📋"},
            {"item": "Appointment booking", "status": "Planned", "status_icon": "📋"},
        ],
        "phase_3": [
            {"item": "Automated email outreach", "status": "Planned", "status_icon": "📋"},
            {"item": "Additional jurisdictions", "status": "Planned", "status_icon": "📋"},
        ],
        "phase_4": [
            {"item": "Daily market updates to clients", "status": "Planned", "status_icon": "📋"},
            {"item": "AI agent launch", "status": "Planned", "status_icon": "📋"},
        ],
    },
}


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return deepcopy(DEFAULT_CONFIG)
    try:
        with CONFIG_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return deepcopy(DEFAULT_CONFIG)
    merged = deepcopy(DEFAULT_CONFIG)
    merged.update({k: data[k] for k in data if k in merged})
    if "assignment_pools" in data:
        merged["assignment_pools"] = data["assignment_pools"]
    if "roadmap" in data:
        merged["roadmap"] = data["roadmap"]
    if "implementation_log" in data:
        merged["implementation_log"] = data["implementation_log"]
    return merged


def save_config(config: dict) -> dict:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    out = deepcopy(DEFAULT_CONFIG)
    out.update(config)
    with CONFIG_PATH.open("w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    return out
