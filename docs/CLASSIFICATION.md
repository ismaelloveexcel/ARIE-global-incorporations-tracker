# Lead classification contract

This document is the **source of truth** for how leads appear in the operator dashboard vs enrichment metadata.

## Operator queue (automatic)

| Rule | Behavior |
|------|----------|
| **Tab** | `direct_clients` only in `/` |
| **UK** | All Companies House leads in the queue |
| **Mauritius** | GBC / Authorised Company only (domestic types excluded) |
| **API** | `GET /api/leads?tab=direct_clients` (default when `tab` omitted) |

Implementation: `uk_leads/dashboard.py` → `is_direct_client()`, `filter_tab_leads(..., "direct_clients")`.

## Introducers (manual)

| Rule | Behavior |
|------|----------|
| **Auto queue** | **None** — pipeline does not populate an introducers work list |
| **API** | `tab=introducers` is **deprecated** and always returns `[]` |
| **Tracking** | CRM, spreadsheet, or a future manual module |

Do not re-enable name-keyword splitting into a second dashboard tab without an explicit product decision.

## Metadata only (not queue membership)

These fields help scoring and the detail panel; they **do not** add a second tab:

| Field | Module | Purpose |
|-------|--------|---------|
| `lead_type` / `lead_type_reason` | `uk_leads/enrichment.py` | Name-pattern hint (`direct` vs `introducer`) for copy and signals |
| `is_introducer(row)` | `uk_leads/dashboard.py` | Legacy detector (Mauritius name keywords); **not** used for tab assignment |
| `dashboard_tabs` | enrichment → `dashboard_tabs_for_lead()` | Always `["direct_clients"]` for includable leads |

## Assignments

- Round-robin pool: **`direct_clients`** only for pipeline leads.
- Introducer pool in `data/assignments.json` / `/dev` config remains for **manual** introducer workflows, not auto-queue routing.

## Tests that enforce this contract

- `tests/test_dashboard_classification.py`
- `tests/test_classification_contract.py`

Run: `python -m pytest -q` from the repository root.
