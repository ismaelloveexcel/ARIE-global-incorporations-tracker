# Lead classification contract

This document is the **source of truth** for how leads appear in the operator dashboard vs enrichment metadata.

## Operator queues (automatic)

| Rule | Behavior |
|------|----------|
| **Tabs** | `direct_clients` and `introducers` in `/` |
| **UK** | All Companies House leads in the queue |
| **Mauritius** | GBC / Authorised Company only (domestic types excluded) |
| **Introducer routing** | Introducer tab is populated by Mauritius name-keyword classification (`is_introducer`) |
| **API** | `GET /api/leads?tab=direct_clients` (default) and `GET /api/leads?tab=introducers` |

Implementation: `uk_leads/dashboard.py` → `is_direct_client()`, `is_introducer()`, `filter_tab_leads(...)`.

## Introducers channel

| Rule | Behavior |
|------|----------|
| **Auto queue** | Populated for introducer-pattern entities only |
| **Scope** | Overlay channel for relationship-intelligence triage |
| **Tracking** | Assignment and notes still persist in-app; CRM can remain system of record |

Note: entities can appear in both `direct_clients` and `introducers` when they match both rules.

## Metadata only (not queue membership)

These fields help scoring and the detail panel; tab behavior is controlled by dashboard classification:

| Field | Module | Purpose |
|-------|--------|---------|
| `lead_type` / `lead_type_reason` | `uk_leads/enrichment.py` | Name-pattern hint (`direct` vs `introducer`) for copy and signals |
| `is_introducer(row)` | `uk_leads/dashboard.py` | Mauritius name-keyword detector used for introducer tab assignment |
| `dashboard_tabs` | enrichment → `dashboard_tabs_for_lead()` | One or both tabs depending on classification |

## Assignments

- **Manual only** — operators choose an RM per lead; saved in `data/assignments.json`.
- Assignment pools in `/dev` config list dropdown names only (no auto-distribution).
- Introducer queue uses introducer assignment pool; direct queue uses direct assignment pool.

## Tests that enforce this contract

- `tests/test_dashboard_classification.py`
- `tests/test_classification_contract.py`

Run: `python -m pytest -q` from the repository root.
