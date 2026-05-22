"""Environment variable helpers — detect placeholders and document operational keys."""
from __future__ import annotations

import os

# Substrings that indicate an unset .env.example placeholder (not a real secret).
_PLACEHOLDER_MARKERS = (
    "your-",
    "your_project",
    "changeme",
    "replace-me",
    "xxx",
    "example.com",
)


def env_value(key: str) -> str:
    return os.environ.get(key, "").strip()


def is_placeholder_value(value: str) -> bool:
    if not value:
        return True
    low = value.lower()
    return any(marker in low for marker in _PLACEHOLDER_MARKERS)


def env_configured(key: str) -> bool:
    """True when the variable is set to a non-placeholder value."""
    return not is_placeholder_value(env_value(key))


def companies_house_key_status() -> dict:
    raw = env_value("COMPANIES_HOUSE_API_KEY")
    if not raw:
        return {"configured": False, "reason": "not_set"}
    if is_placeholder_value(raw):
        return {"configured": False, "reason": "placeholder"}
    return {"configured": True, "reason": "ok"}


def openai_key_status() -> dict:
    raw = env_value("OPENAI_API_KEY")
    if not raw:
        return {"configured": False, "reason": "not_set"}
    if is_placeholder_value(raw):
        return {"configured": False, "reason": "placeholder"}
    return {"configured": True, "reason": "ok"}
