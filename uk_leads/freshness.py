"""Central freshness state machine for snapshots and operator status surfaces."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

STALE_SNAPSHOT_HOURS = 36


def snapshot_age_hours(file_modified: str | None, now: datetime) -> float | None:
    if not file_modified:
        return None
    try:
        modified = datetime.fromisoformat(file_modified.replace("Z", "+00:00"))
        return (now - modified).total_seconds() / 3600
    except ValueError:
        return None


def _fallback_snapshot_date(exclude: str) -> str | None:
    exports = Path("exports")
    if not exports.exists():
        return None
    dates: list[str] = []
    for path in exports.glob("*.csv"):
        stem = path.stem
        if len(stem) == 10 and stem[4] == "-" and stem[7] == "-" and stem != exclude:
            dates.append(stem)
    if not dates:
        return None
    return sorted(dates, reverse=True)[0]


def _label(state: str) -> str:
    labels = {
        "healthy": "Healthy",
        "stale": "Stale",
        "partial": "Partial",
        "missing": "No Snapshot",
        "error": "Issue",
        "unknown": "Unknown",
    }
    return labels.get(state, "Unknown")


def evaluate_freshness(
    *,
    target: str,
    is_today: bool,
    uk: dict,
    mauritius: dict,
    summary: dict | None,
    now: datetime,
) -> dict:
    connectors = (summary or {}).get("connectors") or {}
    outcome = (summary or {}).get("pipeline_outcome")
    matches_date = (summary or {}).get("matches_selected_date", True)
    if not matches_date:
        outcome = None
        connectors = {}

    has_uk = bool(uk.get("exists"))
    has_mu = bool(mauritius.get("exists"))
    has_snapshot = has_uk or has_mu
    file_modified = uk.get("file_modified") or mauritius.get("file_modified")
    age_hours = snapshot_age_hours(file_modified, now)
    fallback_snapshot = _fallback_snapshot_date(target)

    ch = connectors.get("companies_house") or {}
    mu = connectors.get("mauritius_mns") or {}
    ch_err = ch.get("error_message") if ch.get("outcome") == "ERROR" else None
    mu_err = mu.get("error_message") if mu.get("outcome") == "ERROR" else None

    state = "unknown"
    reason = "insufficient_context"

    if has_snapshot and age_hours is not None and age_hours > STALE_SNAPSHOT_HOURS:
        state = "stale"
        reason = "snapshot_age_exceeds_threshold"
    elif outcome == "FAILED" and is_today:
        state = "error"
        reason = "pipeline_failed"
    elif outcome == "PARTIAL" and is_today:
        state = "partial"
        reason = "connector_partial_failure"
    elif not has_snapshot:
        if is_today and now.hour >= 7:
            state = "error"
            reason = "snapshot_missing_after_cutoff"
        else:
            state = "missing"
            reason = "snapshot_missing"
    elif has_uk and not has_mu:
        state = "partial"
        reason = "mauritius_missing"
    elif (not has_uk and has_mu) or ch_err or mu_err:
        state = "partial"
        reason = "one_source_degraded"
    else:
        state = "healthy"
        reason = "all_sources_available"

    degraded_since = None
    if state in {"stale", "partial", "missing", "error"}:
        degraded_since = (
            (summary or {}).get("run_timestamp")
            or file_modified
            or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        )

    verified_sources = 0
    failed_sources = 0
    for connector in (ch, mu):
        outcome_value = (connector or {}).get("outcome")
        if outcome_value == "OK":
            verified_sources += 1
        elif outcome_value == "ERROR":
            failed_sources += 1

    if verified_sources == 0:
        # Connector outcomes may be unavailable for historical dates; infer from snapshot presence.
        if has_uk:
            verified_sources += 1
        if has_mu:
            verified_sources += 1

    active_degradations = 0 if state == "healthy" else max(1, failed_sources)
    fallback_active = bool(fallback_snapshot and state in {"stale", "partial", "missing", "error"})

    if state == "healthy" and failed_sources == 0:
        confidence = "high"
    elif state in {"stale", "partial"}:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "state": state,
        "label": _label(state),
        "reason": reason,
        "stale_threshold_hours": STALE_SNAPSHOT_HOURS,
        "age_hours": round(age_hours, 1) if age_hours is not None else None,
        "degraded_since": degraded_since,
        "fallback_snapshot": fallback_snapshot,
        "provenance": {
            "pipeline_outcome": outcome,
            "companies_house": {
                "outcome": ch.get("outcome"),
                "error": ch_err,
            },
            "mauritius_mns": {
                "outcome": mu.get("outcome"),
                "error": mu_err,
            },
            "has_uk": has_uk,
            "has_mauritius": has_mu,
            "has_snapshot": has_snapshot,
        },
        "operational_confidence": {
            "level": confidence,
            "active_degradations": active_degradations,
            "fallback_active": fallback_active,
            "verified_sources": verified_sources,
            "failed_sources": failed_sources,
        },
    }