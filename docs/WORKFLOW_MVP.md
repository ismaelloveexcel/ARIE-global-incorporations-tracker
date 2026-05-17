# Operator workflow MVP (deferred)

**Status: not planned for now.** Product priority is **strong prospect output** (scoring, prioritisation, verify, assign) — not in-app outreach workflow. Keep this doc for reference only if requirements change later.

---

Small slice to close the RM loop **without** choosing a CRM. Builds on `data/assignments.json` and existing `PATCH /api/leads/{id}`.

## Problem today

| Field | Backend (`assignments.py`) | Operator UI (`app.js`) |
|-------|---------------------------|-------------------------|
| Status | `WORKFLOW_STATUSES` (6 values) | `PANEL_STATUSES` (4 different values) — **mismatch** |
| Next follow-up | `follow_up_at` (ISO date string) | Not exposed |
| Last contact | `contacted_at` | Not exposed |
| Contact channel | — | — |
| Won / lost | — | — |
| Reason | Notes only (free text) | Notes only |

Operators cannot run a consistent morning workflow: *who to call today → what happened → did we win*.

## MVP goal

After 30 minutes on `/`, an RM can answer:

1. Who is **due for follow-up today**?
2. What is each lead’s **stage** and **last touch**?
3. Did we **win or lose**, and **why**?

No CRM integration in this slice — CSV export includes new columns for handoff.

---

## Scope (in)

### 1. Status (single aligned list)

Replace UI `PANEL_STATUSES` with backend list (or one shared constant):

| Status | Meaning |
|--------|---------|
| Not contacted | Default |
| Contacted | First outreach done |
| Follow-up | Active conversation |
| Interested | Qualified intent |
| Onboarding | KYC / account opening in progress |
| Not fit | Closed — not a client (use with outcome reason) |

**Out of MVP:** custom statuses per user.

### 2. Next follow-up date

- Field: `follow_up_at` (already exists) — `YYYY-MM-DD`
- Detail panel: date input
- Table: optional compact column or badge “Due today” / “Overdue”
- Filter: **Due for follow-up** (follow_up_at ≤ today, status not terminal)

### 3. Last contact date + channel

- Fields (new):
  - `contacted_at` (already exists) — date of last touch
  - `last_contact_channel` — enum: `Email` | `Phone` | `LinkedIn` | `Meeting` | `Other`
- Detail panel: date + channel dropdown
- Optional: **“Log contact now”** button sets `contacted_at` = today and channel from dropdown

### 4. Won / lost (outcome)

- Fields (new):
  - `outcome` — `""` | `won` | `lost`
  - `outcome_reason` — short text or enum + optional “Other” text
- Suggested reason enums:
  - **Won:** Onboarded, In progress
  - **Lost:** Not fit / ICP, No response, Chose competitor, Timing, Other
- When `outcome` is set, auto-set status to `Onboarding` (won) or `Not fit` (lost) unless already set

### 5. Reason

- `outcome_reason` (required when outcome is won/lost)
- Keep `notes` for free-form context

---

## Scope (out)

- CRM sync (HubSpot, Salesforce, etc.)
- Email/calendar integration
- Multi-user permissions / audit log
- Introducer manual list module
- Changing scoring engine from outcomes (phase 2: export + weekly report)

---

## Technical plan (minimal diff)

### Backend (~1 file + tests)

`uk_leads/assignments.py` + `app/main.py` `AssignmentUpdate`:

```python
# New optional fields on set_assignment / PATCH body
last_contact_channel: str | None = None
outcome: str | None = None          # "", "won", "lost"
outcome_reason: str | None = None
```

`apply_assignments`: merge new fields onto each row for API + CSV.

`WORKFLOW_OUTCOMES = ["", "won", "lost"]`  
`CONTACT_CHANNELS = ["Email", "Phone", "LinkedIn", "Meeting", "Other"]`

Tests:

- PATCH persists all fields under lock
- Terminal outcome requires reason
- `follow_up_at` filter helper (unit test)

### Operator UI (~2 files)

`app/static/app.js` + `index.html`:

- Detail panel **Workflow** section (above or below assign/notes):
  - Status select (from `/api/meta` `workflow_statuses`)
  - Follow-up date
  - Last contact date + channel
  - Outcome + reason (reason shown when outcome selected)
- Remove hardcoded `PANEL_STATUSES`
- Filter: **Due for follow-up**
- Hero or filter chip: count of due today (optional, S)

`app/static/styles.css`: compact form layout in detail panel only.

### Export

Include in CSV export: `status`, `follow_up_at`, `contacted_at`, `last_contact_channel`, `outcome`, `outcome_reason`.

### Docs

- Link from `README.md` to this file
- One line in `CLASSIFICATION.md`: workflow fields are per `lead_id`, independent of queue rules

---

## Acceptance criteria

- [ ] RM can set all 5 workflow dimensions from the detail panel; values persist after refresh.
- [ ] Status values in UI match `WORKFLOW_STATUSES` from API meta.
- [ ] “Due for follow-up” filter shows only leads with `follow_up_at` ≤ today and no terminal outcome.
- [ ] Setting won/lost without reason shows validation (inline or toast).
- [ ] CSV export includes new columns.
- [ ] `python -m pytest -q` passes; assignment lock behavior unchanged.
- [ ] No change to pipeline, scoring, or introducer classification.

---

## Effort estimate

| Piece | Size |
|-------|------|
| Backend fields + PATCH + merge + tests | S |
| Detail panel workflow UI | M |
| Follow-up filter + optional due count | S |
| CSV + meta alignment | S |
| **Total** | **~1–2 days** focused |

---

## Morning playbook (after MVP)

1. Open `/` → select snapshot date.
2. Click **Due for follow-up** (or **Review high priority** for new leads).
3. Open row → verify registry → assign owner if needed.
4. After call/email → **Log contact** (date + channel) → set **Follow-up date**.
5. When decided → **Won** or **Lost** + reason.
6. End of week → export CSV for leadership / CRM paste.

---

## Phase 2 (not MVP)

- Weekly conversion report: won/lost by jurisdiction and score band
- Score tuning from outcomes
- Slack digest: “N leads due today”
- Manual introducers list (separate from this workflow)
