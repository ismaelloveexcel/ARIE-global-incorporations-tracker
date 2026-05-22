"""Central operational mode for RM-facing vs engineering behaviour."""
from __future__ import annotations

import os

_VALID_MODES = frozenset({"development", "dev", "staging", "production", "prod", "rm"})


def get_app_mode() -> str:
    raw = os.environ.get("APP_MODE", "development").strip().lower()
    if raw in _VALID_MODES:
        return raw
    return "development"


def is_production() -> bool:
    return get_app_mode() in ("production", "prod", "rm")


def is_staging() -> bool:
    return get_app_mode() == "staging"


def operator_refresh_allowed() -> bool:
    """Engineering-only in-app snapshot rebuild from registries (dev/staging)."""
    return not is_production()


def mode_config() -> dict:
    """Expose to /api/meta for the operator UI."""
    production = is_production()
    return {
        "app_mode": get_app_mode(),
        "is_production": production,
        "operator_refresh_allowed": operator_refresh_allowed(),
        "snapshot_first_queue": True,
        "show_dev_link": not production,
    }
