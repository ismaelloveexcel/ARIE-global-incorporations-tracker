# Arie Incorporation Monitor

Internal **onboarding intelligence** dashboard for [Arie Finance](https://www.ariefinance.com/) — a regulated Mauritius-based provider serving international businesses, management companies, trusts, and complex multi-entity structures.

The app turns **official registry feeds** (UK Companies House + Mauritius GBC/AC where available) into a daily **work queue**: scored leads, manual assignment, verify links, and operator notes. It is built for relationship managers and ops, not as a public product.

## Product model (important)

| List | How it is maintained |
|------|----------------------|
| **Direct clients** | **Automatic** — pipeline + dashboard (`/`) show newly incorporated companies to onboard as Arie clients. |
| **Introducers** | **Manual** — referral partners are **not** auto-queued. The Introducers tab is a roadmap placeholder only. |

Name-based hints in the detail panel are for **scoring context only**. See [`docs/CLASSIFICATION.md`](docs/CLASSIFICATION.md).

---

## Operational model

- **Snapshot-first** — RMs work from prepared `exports/YYYY-MM-DD.csv` files produced by the **overnight pipeline** (or an engineering run in dev).
- **No live registry access in production** — the operator UI does not fetch Companies House or MNS on demand in `APP_MODE=production`.
- **Deterministic scoring** — heuristic enrichments are recomputed when a snapshot is loaded (not calibrated to conversion).
- **Registry verify links only** — official Companies House / MNS URLs; no invented contact data or guessed domains.
- **Manual assignment** — dropdown ownership saved to `data/assignments.json`; no auto-distribution.
- **AI brief (optional)** — non-authoritative; always verify on the source register before outreach.

## Snapshot lifecycle

1. **Overnight (or manual) pipeline** — `python main.py --date YYYY-MM-DD --skip-difc` (or `python run_uk_daily.py`) writes **`exports/{date}.csv`** (canonical UK + Mauritius rows).
2. **Operator opens date** — `uk_leads/data_loader.py` merges the CSV, enriches scores, merges saved assignments.
3. **Review queue** — filter, sort, assign, export current view, open detail for breakdown and optional brief.
4. **Stale warning** — if the snapshot file is older than 36 hours, the UI shows an amber banner (review before outreach).

Recovery when a date is missing: see [Recovery](#recovery-when-a-snapshot-is-missing) below.

## Development vs production

| | **Development** (`APP_MODE=development`) | **Production** (`APP_MODE=production`) |
|---|-------------------------------------------|----------------------------------------|
| Operator badge | DEV MODE | PRODUCTION |
| `/dev` operations UI | Available | Hidden (404) |
| In-app “build snapshot” control | Shown in header (engineering) | Hidden |
| Data source | Prepared `exports/` + optional dev fetch | **Prepared `exports/` only** |
| Mauritius auto-merge on open | May trigger engineering fetch | Expects pipeline output |

Set `APP_MODE=production` on RM workstations. Use development on engineering machines only.

## Manual assignment workflow

1. Open a lead (row or detail panel).
2. Choose an RM from the dropdown (detail panel shows names; queue table shows **Assign** / **Assigned** only).
3. Assignment saves immediately via `PATCH /api/leads/{id}` → `data/assignments.json`.
4. No round-robin, bulk assign, or ownership history.

## Provenance model

Labels used consistently in the UI:

| Label | Meaning |
|-------|---------|
| **Registry verified** | From Companies House or MNS registry fields / verify link |
| **Internal heuristic** | Rule-based score and intelligence signals |
| **AI-generated** | Optional brief text |
| **Not available from registry** | Field not supplied by the register |

## Recovery when a snapshot is missing

**Production**

1. Confirm the date in the header picker.
2. If yesterday’s file is missing, contact operations — the overnight pipeline may not have run.
3. Do not expect the RM UI to pull live registry data.

**Development / engineering**

1. Run `python main.py --date YYYY-MM-DD --skip-difc` or use **Settings → Operations** (`/dev`) health checks.
2. Or place a valid prepared CSV at `exports/YYYY-MM-DD.csv` (see pipeline header in `uk_leads/data_loader.py`).
3. Restart the app after changing `.env`: `python -m app.main`.

## What this system intentionally does NOT do

- Live registry refresh in production
- Invented emails, phones, LinkedIn, or website domains
- CRM workflows (follow-ups, pipelines, commissions)
- Outreach automation or notifications
- Introducer relationship management (placeholder tab only)
- Auto-assignment or round-robin distribution

---

## Pilot runbook (for RMs)

Day-to-day usage guide (non-technical): [`docs/PILOT_RUNBOOK.md`](docs/PILOT_RUNBOOK.md)

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env — set a real COMPANIES_HOUSE_API_KEY (not the placeholder)
```

### Run the daily pipeline (optional)

```bash
python main.py --date YYYY-MM-DD --skip-difc
# or UK-only:
python run_uk_daily.py --date YYYY-MM-DD
```

### Start the dashboard

```bash
python -m app.main
```

Open **http://127.0.0.1:8080** (default port **8080**, single process).

- **Operator UI:** `/` — snapshot queue, filters, assignment, verify links.
- **Operations UI:** `/dev` — pipeline health, snapshot file status (development only).

`uvicorn` runs with **reload=True** in dev when started via `python -m app.main`. For production, run the same command with `APP_MODE=production` and rely on prepared snapshots; restart the process after pipeline drops new CSV files.

## Scoring

- Heuristic **0–100** fit score — see `uk_leads/score_explain.py` and the detail panel.
- Priority: High ≥ 70, Medium ≥ 40, Low otherwise.

## Architecture (high level)

```
main.py / run_uk_daily.py  →  exports/YYYY-MM-DD.csv
         ↓
uk_leads/data_loader.py    →  merge UK + Mauritius for a date
uk_leads/enrichment.py     →  score, signals, score_breakdown
uk_leads/assignments.py    →  manual RM assignment + data/assignments.json
         ↓
app/main.py (FastAPI)      →  /api/leads, static operator UI
```

## Tests

```bash
python -m pytest -q
```

Run from the **repository root**.

## Repository layout

| Path | Purpose |
|------|---------|
| `app/` | FastAPI app + static operator UI |
| `uk_leads/` | Scoring, enrichment, assignments, data loading |
| `scoring/` | Score engine |
| `tests/` | Unit tests |
| `exports/` | Pipeline CSV output (gitignored) |
| `data/assignments.json` | Saved assignments (gitignored) |

## Deliberately out of scope (for now)

- RM workflow layers — see [`docs/WORKFLOW_MVP.md`](docs/WORKFLOW_MVP.md)
- Auth / multi-tenant access control
- Introducer automation or CRM sync
- Mauritius directors/PSC until MNS API access is confirmed

## Independent review

- [`docs/CLAUDE_STATUS_REVIEW_PROMPT.md`](docs/CLAUDE_STATUS_REVIEW_PROMPT.md)
- [`docs/INDEPENDENT_AUDIT_PROMPT.md`](docs/INDEPENDENT_AUDIT_PROMPT.md)

## Legacy

`main.py` (multi-jurisdiction + optional Supabase) remains for batch pipeline runs; the **operator path** is `app.main` reading `exports/{date}.csv`.
