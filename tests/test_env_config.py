"""Environment placeholder detection."""
from __future__ import annotations

import os

import pytest

from uk_leads.env_config import (
    companies_house_key_status,
    env_configured,
    is_placeholder_value,
    openai_key_status,
)


def test_placeholder_detection():
    assert is_placeholder_value("")
    assert is_placeholder_value("your-companies-house-api-key")
    assert is_placeholder_value("https://your-project.supabase.co")
    assert not is_placeholder_value("abc123-real-key-material")


def test_companies_house_key_status(monkeypatch):
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    assert companies_house_key_status()["configured"] is False

    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "your-companies-house-api-key")
    assert companies_house_key_status()["configured"] is False
    assert companies_house_key_status()["reason"] == "placeholder"

    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "real-key-abc")
    assert companies_house_key_status()["configured"] is True


def test_openai_key_status(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "your-openai-api-key")
    assert openai_key_status()["configured"] is False

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert openai_key_status()["configured"] is True


def test_env_configured_helper(monkeypatch):
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "your-companies-house-api-key")
    assert env_configured("COMPANIES_HOUSE_API_KEY") is False
