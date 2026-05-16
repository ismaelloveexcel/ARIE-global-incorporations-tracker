"""Pipeline alert status for the /dev dashboard (GitHub native notifications)."""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_REPO = "ismaelloveexcel/ARIE-global-incorporations-tracker"
WORKFLOW_NAME = "Incorporation Intelligence Engine — Daily Pipeline"


def _repo() -> str:
    return os.getenv("GITHUB_REPOSITORY", DEFAULT_REPO)


def _github_get(path: str) -> dict | None:
    url = f"https://api.github.com{path}"
    req = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "ARIE-incorporation-monitor",
        },
    )
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data if isinstance(data, dict) else None
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def get_pipeline_alert_status() -> dict:
    repo = _repo()
    runs_data = _github_get(f"/repos/{repo}/actions/runs?per_page=8") or {}
    runs: list[dict] = []
    for row in (runs_data.get("workflow_runs") or [])[:8]:
        runs.append(
            {
                "id": row.get("id"),
                "name": row.get("name"),
                "status": row.get("status"),
                "conclusion": row.get("conclusion"),
                "event": row.get("event"),
                "created_at": row.get("created_at"),
                "html_url": row.get("html_url"),
            }
        )

    return {
        "method": "github_notifications",
        "repo": repo,
        "workflow_name": WORKFLOW_NAME,
        "setup": {
            "summary": (
                "When the daily GitHub workflow fails, GitHub emails the address on "
                "your GitHub account. No paid email service or Outlook SMTP setup required."
            ),
            "steps": [
                {
                    "title": "Turn on failure emails",
                    "detail": "Settings → Notifications → Actions → enable alerts for failed workflows.",
                    "url": "https://github.com/settings/notifications#workflow_notifications",
                },
                {
                    "title": "Confirm your email",
                    "detail": "Settings → Emails. Alerts go to your primary GitHub email.",
                    "url": "https://github.com/settings/emails",
                },
                {
                    "title": "Open the daily pipeline",
                    "detail": "Runs at 06:00 UTC. Re-run manually from Actions if needed.",
                    "url": f"https://github.com/{repo}/actions/workflows/daily_pipeline.yml",
                },
            ],
        },
        "links": {
            "actions": f"https://github.com/{repo}/actions",
            "workflow": f"https://github.com/{repo}/actions/workflows/daily_pipeline.yml",
            "notification_settings": "https://github.com/settings/notifications#workflow_notifications",
        },
        "runs": runs,
        "latest": runs[0] if runs else None,
        "last_success": next((r for r in runs if r.get("conclusion") == "success"), None),
        "last_failure": next((r for r in runs if r.get("conclusion") == "failure"), None),
        "api_ok": bool(runs_data.get("workflow_runs") is not None),
    }
