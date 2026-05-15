"""OpenAI lead brief — synthesis only, structured JSON."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests

BRIEFS_DIR = Path("data") / "briefs"
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def _build_prompt(lead: dict[str, Any], people: dict[str, Any] | None) -> str:
    officers = (people or {}).get("officers") or []
    psc = (people or {}).get("psc") or []
    return f"""You are an onboarding intelligence assistant for Arie Finance (cross-border payments and onboarding).

Using ONLY the verified and rule-based facts below, produce a JSON object for internal outreach planning.
Do NOT invent emails, websites, LinkedIn URLs, or compliance conclusions.
If information is missing, say so in the text — do not guess contacts.

Company facts (Companies House):
- Name: {lead.get('company_name')}
- Number: {lead.get('company_number')}
- Incorporated: {lead.get('incorporation_date')} ({lead.get('incorporation_age_label')})
- SIC: {lead.get('sic_codes')}
- Entity type: {lead.get('entity_type')}
- Score: {lead.get('score')} ({lead.get('priority')} priority)
- Lead type: {lead.get('lead_type')}
- Rule tags: {', '.join(lead.get('why_tags') or [])}
- Strengths (rules): {', '.join(lead.get('strengths') or [])}
- Caution (rules): {', '.join(lead.get('cautions') or [])}

Officers: {json.dumps(officers[:10], default=str)}
PSCs: {json.dumps(psc[:10], default=str)}

Return ONLY valid JSON with keys:
business_summary, why_arie, likely_need, outreach_angle, opening_line, strengths, cautions
- strengths/cautions: arrays of short strings (may refine rule lists, no new facts)
- opening_line: one professional sentence for cold outreach
"""


def generate_brief(lead: dict[str, Any], people: dict[str, Any] | None = None) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set in .env")

    prompt = _build_prompt(lead, people)
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": "You output only valid JSON. You never invent contact details or URLs.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    data = json.loads(content)
    data["source"] = "ai_generated"
    data["disclaimer"] = (
        "AI synthesis for internal use only — not a compliance or AML assessment. "
        "Confirm facts on Companies House before outreach."
    )
    return data


def save_brief(company_number: str, brief: dict[str, Any]) -> None:
    BRIEFS_DIR.mkdir(parents=True, exist_ok=True)
    path = BRIEFS_DIR / f"{company_number}.json"
    with path.open("w", encoding="utf-8") as fh:
        json.dump(brief, fh, indent=2)


def load_brief(company_number: str) -> dict[str, Any] | None:
    path = BRIEFS_DIR / f"{company_number}.json"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)
