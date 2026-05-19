# Claude review prompt — current status, gaps, lightweight improvements

**Copy everything below the horizontal rule** into a **new Claude session** with this repository open (read + run commands). You are **reviewing and advising only** — do not change code unless the user explicitly asks you to implement fixes afterward.

**Repo:** ARIE Global Incorporations Tracker (Arie Finance — internal Incorporation Monitor)  
**Operator app:** `python -m app.main` → http://127.0.0.1:8080  
**Tests:** `python -m pytest -q` from repository root

For a deeper line-by-line production audit, see `docs/INDEPENDENT_AUDIT_PROMPT.md`. **This prompt is narrower:** current state, gaps, and **small** improvements only.

---

## Your role

You are a **senior product engineer** advising a **startup fintech** that depends on this tool for daily client acquisition. Be direct, practical, and evidence-based. Cite **file paths** (and line numbers where useful). Run the app and tests; do not rely on assumptions.

**Bar for success:** A relationship manager can open the tool each morning, see trustworthy prospects for a chosen incorporation date, understand who to contact and why, assign leads, export for outreach, and verify via official registries — **without engineer help**.

---

## What this tool is (verify in code)

- **Purpose:** Daily queue of newly incorporated **UK** and **Mauritius (GBC/AC)** companies, ranked by heuristic fit score (0–100), for direct-client onboarding at Arie Finance.
- **Not:** A CRM, introducer auto-queue, or source of invented contact details.
- **Data path:** Pipeline writes `exports/YYYY-MM-DD.csv` → `uk_leads/data_loader.py` merges/enriches → FastAPI `app/main.py` → static UI `app/static/`.
- **Modes:** `APP_MODE` in `.env` (`development` vs `production` / `rm`) — see `uk_leads/app_mode.py`. Production limits live registry refresh from the operator UI; development allows it.
- **Optional:** OpenAI brief in lead detail panel; Companies House people enrichment for UK rows.

Read first: `README.md`, `docs/CLASSIFICATION.md`, `uk_leads/app_mode.py`, `app/main.py`, `app/static/app.js`, `uk_leads/data_loader.py`.

---

## Review objectives

### 1. Current status snapshot (required)

Produce a short **“as of today”** assessment:

| Area | Status (Green / Amber / Red) | One-sentence evidence |
|------|------------------------------|------------------------|
| Operator can load leads for a snapshot date | | |
| UK data path reliable | | |
| Mauritius data path reliable | | |
| Date navigation usable | | |
| Scoring + “why contact” actionable | | |
| Assignments persist | | |
| Export usable for outreach | | |
| Production vs dev behaviour clear | | |
| CI / tests trustworthy | | |
| Deploy / ops documented enough | | |

Include: latest relevant commits on `main` (run `git log -5 --oneline`), test count from `pytest -q`, and whether README matches actual behaviour.

### 2. Gaps and issues (required)

List **every material gap** you find, grouped as:

- **P0 — Blocks daily use** (wrong data, crashes, trust/compliance risk, data loss)
- **P1 — Friction or missed leads** (confusing UX, silent failures, stale copy)
- **P2 — Polish / maintainability**

For each item: **what** | **where** (file/path) | **who is hurt** (RM / ops / engineer) | **fix type** (config / copy / bug / docs — not “build a new module”).

**Explicitly check:**

- Demo vs production confusion (`demo` query param, “cap UK top 25”, `LIVE SNAPSHOT` badge, `operator_refresh_allowed`)
- Whether queue reads **only** canonical `exports/{date}.csv` or still mixes legacy `uk-leads-demo-*.csv` (see `tests/test_canonical_merge.py`)
- Mauritius director gap and how operators are told
- Multiple local servers on different ports (8080 vs 8082) — operational confusion only
- Empty states, loading errors, and what happens with **no** `exports/` on first run
- Assignment / status field mismatches between UI and backend (if any remain)
- Security: open `/` and `/dev` without auth — acceptable for internal pilot or not?
- Playwright / Mauritius scrape failures in production

**Do not** recommend invented emails, fake LinkedIn, or unverified “AI facts.”

### 3. Recommendations — stronger tool, **no substantial new features** (required)

The team will **not** add major new product areas (full CRM, introducers tab, new registry APIs, React rewrite, multi-module workflow). Recommend only changes that **compound value** from what already exists:

**Allowed (examples):**

- Copy, defaults, and env clarity (`APP_MODE`, `.env.example`)
- Bug fixes and single-source-of-truth refactors
- Clearer empty/loading/error messages
- Small export column improvements (what RMs paste into Sheets/CRM)
- Score threshold labels, hero metrics, filter wording
- Reliability: retries, timeouts, idempotent refresh, snapshot retention docs
- Remove or hide dead UI / misleading “demo” affordances
- Tighten tests for paths RMs rely on
- One-page RM morning playbook using **existing** features
- Responsible use of existing OpenAI brief (disclaimers, no hallucinated contacts)
- Lightweight cited research **only** if it fits current architecture without a new product surface

**Not allowed (call out if tempted, then reject):**

- New registry connectors or “get UK-level API for every country”
- Full outreach workflow (follow-up CRM inside app) unless ≤2 fields already in backend
- Second queue / introducers automation
- Large AI agent platform (Manus-style) as a new subsystem
- Rebuild front end in React

Deliver a **prioritised table** (max **12 rows**):

| Priority | Recommendation | Why it helps RMs win clients | Effort (S/M) | Complexity added (1–5, lower is better) |

### 4. Missing information for lead gen (brief)

Without new registry APIs, list the **top 5 data gaps** that limit outbound quality today (e.g. website, director contact, payment intent). For each: **workaround using existing data + human verification** vs **do not do** (invented contact).

One short paragraph only — not a research report.

---

## How to work

1. Read the entry-point files listed above.  
2. Run `python -m pytest -q` and report pass/fail count.  
3. Skim `.github/workflows/` for pipeline and test CI.  
4. If possible, start the app and hit `/`, `/api/meta`, `/api/available-dates`, `/api/leads` for a date that exists in `exports/` (or note absence).  
5. Compare `docs/UI_DONE_CHECKLIST.md` to production `app/static/index.html` — note stale checklist items.

---

## Deliverable format (strict)

Keep the full response **under ~2,500 words** unless P0 list forces more detail.

1. **Executive summary** — 6–8 bullets for a non-technical founder (“ready for RM pilot: yes / partial / no”).  
2. **Current status table** (section 1).  
3. **Gaps & issues** — P0, then P1, then P2 (bullet lists).  
4. **Lightweight recommendations table** (section 3, max 12 rows).  
5. **Top 5 missing data elements** (section 4).  
6. **Three things already working well** — be specific, not generic praise.  
7. **Open questions** — max 5 for the team.

---

## Constraints

- UK and Mauritius treated with equal product respect.  
- Introducers stay manual outside this app.  
- Verify links must stay official registry URLs only.  
- Prefer **one port, one process** for local use: **8080**.  
- Do not implement code changes in this review unless asked.

---

*End of prompt.*
