"""
db/supabase_client.py
─────────────────────
Thin wrapper around the Supabase Python client.
All database writes for the pipeline go through this module.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any

from dotenv import load_dotenv
from psycopg import connect
from psycopg.rows import dict_row
from psycopg.types.json import Json
from supabase import Client, create_client

load_dotenv()

_FETCH_PAGE_SIZE = 1000  # rows per page when building the deduplication index


def _database_url() -> str | None:
    value = os.getenv("DATABASE_URL", "").strip()
    return value or None


def _use_postgres() -> bool:
    return _database_url() is not None


@contextmanager
def _with_pg_cursor():
    db_url = _database_url()
    if not db_url:
        raise RuntimeError("DATABASE_URL is not configured")
    conn = connect(db_url)
    try:
        with conn, conn.cursor(row_factory=dict_row) as cur:
            yield cur
    finally:
        conn.close()


def _get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return create_client(url, key)


# Module-level lazy singleton so tests can swap it out easily.
_client: Client | None = None


def get_client() -> Client:
    if _use_postgres():
        raise RuntimeError("Supabase client is not used when DATABASE_URL is configured")
    global _client
    if _client is None:
        _client = _get_client()
    return _client


# ─────────────────────────────────────────────────────────────────────────────
# canonical_entities helpers
# ─────────────────────────────────────────────────────────────────────────────

def upsert_canonical_entity(canonical_name: str, jurisdiction: str, date: str | None) -> int:
    """
    Insert or update a canonical_entity record.
    Returns the canonical entity id.
    """
    if _use_postgres():
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

    client = get_client()

    existing = (
        client.table("canonical_entities")
        .select("id, jurisdictions, first_seen, last_seen")
        .eq("canonical_name", canonical_name)
        .limit(1)
        .execute()
    )

    if existing.data:
        row = existing.data[0]
        jurisdictions = list(set(row.get("jurisdictions") or []) | {jurisdiction})
        first_seen = row.get("first_seen") or date
        last_seen = date if date and (not row.get("last_seen") or date > row["last_seen"]) else row.get("last_seen")

        client.table("canonical_entities").update(
            {
                "jurisdictions": jurisdictions,
                "first_seen": first_seen,
                "last_seen": last_seen,
            }
        ).eq("id", row["id"]).execute()

        return row["id"]

    result = (
        client.table("canonical_entities")
        .insert(
            {
                "canonical_name": canonical_name,
                "jurisdictions": [jurisdiction],
                "first_seen": date,
                "last_seen": date,
            }
        )
        .execute()
    )
    return result.data[0]["id"]


# ─────────────────────────────────────────────────────────────────────────────
# companies helpers
# ─────────────────────────────────────────────────────────────────────────────

def insert_company(record: dict[str, Any]) -> dict[str, Any]:
    """
    Insert a single normalised company record.
    Returns the inserted row.
    """
    if _use_postgres():
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

    client = get_client()
    result = client.table("companies").insert(record).execute()
    return result.data[0]


def fetch_all_companies(jurisdiction: str | None = None) -> list[dict[str, Any]]:
    """
    Fetch companies, optionally filtered by jurisdiction.
    Used by the deduplication pass to build the in-memory index.

    Results are fetched in pages to avoid hitting the PostgREST row limit.
    """
    if _use_postgres():
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

    client = get_client()
    offset = 0
    all_rows: list[dict[str, Any]] = []

    while True:
        query = client.table("companies").select(
            "id, normalized_name, jurisdiction, canonical_entity_id"
        )
        if jurisdiction:
            query = query.eq("jurisdiction", jurisdiction)
        result = query.range(offset, offset + _FETCH_PAGE_SIZE - 1).execute()
        rows = result.data or []
        all_rows.extend(rows)
        if len(rows) < _FETCH_PAGE_SIZE:
            break
        offset += _FETCH_PAGE_SIZE

    return all_rows


def set_canonical_entity_id(company_id: int, canonical_entity_id: int) -> None:
    """Link a company row to its canonical entity."""
    if _use_postgres():
        with _with_pg_cursor() as cur:
            cur.execute(
                """
                UPDATE companies
                SET canonical_entity_id = %s
                WHERE id = %s
                """,
                (canonical_entity_id, company_id),
            )
        return

    client = get_client()
    client.table("companies").update(
        {"canonical_entity_id": canonical_entity_id}
    ).eq("id", company_id).execute()
