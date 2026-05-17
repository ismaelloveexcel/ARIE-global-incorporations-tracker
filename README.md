# Arie Incorporation Monitor

Internal **onboarding intelligence** dashboard for [Arie Finance](https://www.ariefinance.com/) — a regulated Mauritius-based provider serving international businesses, management companies, trusts, and complex multi-entity structures.

The app turns **official registry feeds** (UK Companies House + Mauritius GBC/AC where available) into a daily **work queue**: scored leads, team assignment, verify links, and operator notes. It is built for relationship managers and ops, not as a public product.

## Product model (important)

| List | How it is maintained |
|------|----------------------|
| **Direct clients** | **Automatic** — pipeline + dashboard (`/`) show newly incorporated companies to onboard as Arie clients. |
| **Introducers** | **Manual** — referral partners (management firms, professional services, etc.) are **not** auto-split into a second tab. Track them outside this queue or in your CRM until a manual introducers feature exists. |

Name-based hints in the detail panel (e.g. “fiduciary / professional services”) are for **scoring context only** — they do not create a duplicate list. See [`docs/CLASSIFICATION.md`](docs/CLASSIFICATION.md) for the full contract.

## Quick start

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set `COMPANIES_HOUSE_API_KEY` ([register free](https://developer.company-information.service.gov.uk/)). Optional: `OPENAI_API_KEY` for AI briefs in the lead panel.

### Run the daily pipeline (optional)

```bash
python main.py --date YYYY-MM-DD --skip-difc
# or UK-only helper:
python run_uk_daily.py --date YYYY-MM-DD --demo
```

### Start the dashboard

```bash
python -m app.main
```

Open **http://127.0.0.1:8080**

- **Operator UI:** `/` — single work queue, filters, assignments, Companies House / MNS verify links.
- **Operations UI:** `/dev` — pipeline health, alerts, assignment pool config (not linked from operator header except Settings → Operations).

## What operators see

1. **Hero strip** — incorporation snapshot date, queue stats, UK/Mauritius breakdown, last refresh.
2. **Filters + table** — search, priority, jurisdiction, sort, assign, notes.
3. **Review high priority** — one-click filter to high-priority leads.
4. **Row detail** — score breakdown, classification hints, directors (UK), optional AI brief.
5. **Settings** (header) — refresh register data, cap UK volume (top 25 by score in demo mode).

## Scoring

- Heuristic **0–100** fit score (not calibrated to conversion).
- Components: entity type, jurisdiction, SIC (UK), name keywords — see `uk_leads/score_explain.py` and the detail panel.
- Priority: High ≥ 70, Medium ≥ 40, Low otherwise.

## Architecture (high level)

```
main.py / run_uk_daily.py  →  exports/YYYY-MM-DD.csv (+ MU sources)
         ↓
uk_leads/data_loader.py    →  merge UK + Mauritius for a date
         ↓
uk_leads/enrichment.py     →  score, lead_type hints, score_breakdown
uk_leads/dashboard.py      →  direct-client queue rules (single tab)
uk_leads/assignments.py    →  round-robin + data/assignments.json
         ↓
app/main.py (FastAPI)      →  /api/leads, static operator UI
```

## Tests

```bash
python -m pytest -q
```

Run from the **repository root** (same command as CI). Do not report “tests broken” without this exact command and the error output.

## Repository layout

| Path | Purpose |
|------|---------|
| `app/` | FastAPI app + static operator UI |
| `uk_leads/` | Scoring, enrichment, classification, assignments |
| `scoring/` | Score engine |
| `tests/` | Unit tests |
| `exports/` | Pipeline CSV output (gitignored) |
| `data/assignments.json` | Saved assignments (gitignored) |

## Product focus

**Strong prospect output** — newly incorporated companies that match Arie’s client profile, ranked and explainable so RMs can turn them into clients. The dashboard is a **discovery and prioritisation** tool, not a CRM or workflow system.

Use **Strong prospects (40+)** (default filter), **Review high priority**, the **Why contact** column, score breakdown, verify links, assign, and notes. Scores are recomputed on load using Arie ICP rules (international, payments, GBC/AC, etc.). Track outreach in your existing CRM or spreadsheet.

## Deliberately out of scope (for now)

- RM workflow layers (follow-up dates, won/lost pipelines) — see deferred notes in [`docs/WORKFLOW_MVP.md`](docs/WORKFLOW_MVP.md)
- Auth / multi-tenant access control
- Auto introducers tab or CRM sync
- Fake companies or invented contact data
- Mauritius directors/PSC until MNS API access is confirmed

## Independent review

- **Full production audit (recommended):** [`docs/INDEPENDENT_AUDIT_PROMPT.md`](docs/INDEPENDENT_AUDIT_PROMPT.md) — end-to-end, line-by-line, demo→production, missing data, AI/workarounds.  
- **Shorter growth review:** [`docs/INDEPENDENT_REVIEW_PROMPT.md`](docs/INDEPENDENT_REVIEW_PROMPT.md).

## Legacy

`main.py` (multi-jurisdiction + optional Supabase) remains for batch pipeline runs; the **demo path** is `app.main` + `exports/` CSVs.
