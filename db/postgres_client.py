"""
db/postgres_client.py
─────────────────────
PostgreSQL client helpers used by the daily pipeline.
All database writes for the pipeline go through this module.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from dotenv import load_dotenv
from psycopg import connect
from psycopg.rows import dict_row
from psycopg.types.json import Json

import os

load_dotenv()


def is_configured() -> bool:
    return bool(os.getenv("DATABASE_URL", "").strip())


def _database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is not configured")
    return value


@contextmanager
def _with_pg_cursor():
    with connect(_database_url()) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            yield cur


def upsert_canonical_entity(canonical_name: str, jurisdiction: str, date: str | None) -> int:
    """
    Insert or update a canonical_entity record.
    Returns the canonical entity id.
    """
    with _with_pg_cursor() as cur:
        cur.execute(
            """
            SELECT id, jurisdictions, first_seen, last_seen
            FROM canonical_entities
            WHERE canonical_name = %s
            LIMIT 1
            """,
            (canonical_name,),
        )
        row = cur.fetchone()
        if row:
            jurisdictions = sorted(set(row.get("jurisdictions") or []) | {jurisdiction})
            first_seen = row.get("first_seen") or date
            last_seen = date if date and (not row.get("last_seen") or str(date) > str(row["last_seen"])) else row.get("last_seen")
            cur.execute(
                """
                UPDATE canonical_entities
                SET jurisdictions = %s, first_seen = %s, last_seen = %s
                WHERE id = %s
                """,
                (jurisdictions, first_seen, last_seen, row["id"]),
            )
            return int(row["id"])

        cur.execute(
            """
            INSERT INTO canonical_entities (canonical_name, jurisdictions, first_seen, last_seen)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (canonical_name, [jurisdiction], date, date),
        )
        return int(cur.fetchone()["id"])


def insert_company(record: dict[str, Any]) -> dict[str, Any]:
    """
    Insert a single normalised company record.
    Returns the inserted row.
    """
    payload = dict(record)
    payload["raw_data"] = Json(payload.get("raw_data") or {})
    columns = list(payload.keys())
    values = [payload[k] for k in columns]
    col_sql = ", ".join(columns)
    placeholder_sql = ", ".join(["%s"] * len(columns))
    with _with_pg_cursor() as cur:
        cur.execute(
            f"INSERT INTO companies ({col_sql}) VALUES ({placeholder_sql}) RETURNING *",
            values,
        )
        return dict(cur.fetchone())


def fetch_all_companies(jurisdiction: str | None = None) -> list[dict[str, Any]]:
    """
    Fetch companies, optionally filtered by jurisdiction.
    Used by the deduplication pass to build the in-memory index.
    """
    with _with_pg_cursor() as cur:
        if jurisdiction:
            cur.execute(
                """
                SELECT id, normalized_name, jurisdiction, canonical_entity_id
                FROM companies
                WHERE jurisdiction = %s
                """,
                (jurisdiction,),
            )
        else:
            cur.execute(
                """
                SELECT id, normalized_name, jurisdiction, canonical_entity_id
                FROM companies
                """
            )
        return [dict(r) for r in cur.fetchall()]


def upsert_lead_assignment(
    lead_id: str,
    assigned_to: str | None = None,
    notes: str | None = None,
    status: str | None = None,
    contacted_at: str | None = None,
    follow_up_at: str | None = None,
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if assigned_to is not None:
        updates["assigned_to"] = assigned_to
    if notes is not None:
        updates["notes"] = notes
    if status is not None:
        updates["status"] = status
    if contacted_at is not None:
        updates["contacted_at"] = contacted_at or None
    if follow_up_at is not None:
        updates["follow_up_at"] = follow_up_at or None

    default_status = updates.get("status") or "Not contacted"
    with _with_pg_cursor() as cur:
        cur.execute(
            """
            INSERT INTO lead_assignments (lead_id, assigned_to, notes, status, contacted_at, follow_up_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (lead_id) DO UPDATE
            SET assigned_to = COALESCE(EXCLUDED.assigned_to, lead_assignments.assigned_to),
                notes = COALESCE(EXCLUDED.notes, lead_assignments.notes),
                status = COALESCE(EXCLUDED.status, lead_assignments.status),
                contacted_at = COALESCE(EXCLUDED.contacted_at, lead_assignments.contacted_at),
                follow_up_at = COALESCE(EXCLUDED.follow_up_at, lead_assignments.follow_up_at)
            RETURNING lead_id, assigned_to, notes, status, contacted_at, follow_up_at
            """,
            (
                lead_id,
                updates.get("assigned_to"),
                updates.get("notes"),
                default_status,
                updates.get("contacted_at"),
                updates.get("follow_up_at"),
            ),
        )
        row = cur.fetchone() or {}

    return dict(row)


def fetch_lead_assignments(lead_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not lead_ids:
        return {}

    with _with_pg_cursor() as cur:
        cur.execute(
            """
            SELECT lead_id, assigned_to, notes, status, contacted_at, follow_up_at
            FROM lead_assignments
            WHERE lead_id = ANY(%s)
            """,
            (lead_ids,),
        )
        rows = [dict(r) for r in cur.fetchall()]

    return {str(r.get("lead_id")): r for r in rows if r.get("lead_id")}


def fetch_leads_for_date(
    incorporation_date: str,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    with _with_pg_cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM companies
            WHERE incorporation_date::text = %s
            ORDER BY score DESC NULLS LAST
            LIMIT %s
            """,
            (incorporation_date, limit),
        )
        return [dict(r) for r in cur.fetchall()]


def fetch_available_dates(limit: int = 30) -> list[str]:
    with _with_pg_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT incorporation_date::text AS d
            FROM companies
            WHERE incorporation_date IS NOT NULL
            ORDER BY d DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [r["d"] for r in cur.fetchall()]


