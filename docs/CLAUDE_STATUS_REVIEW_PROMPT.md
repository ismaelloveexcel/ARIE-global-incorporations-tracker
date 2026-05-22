# Claude review prompt — current status, gaps, lightweight improvements

**Copy everything below the horizontal rule** into a **new Claude session** with this repository open (read + run commands). You are **reviewing and advising only** — do not change code unless the user explicitly asks you to implement fixes afterward.

**Repo:** ARIE Global Incorporations Tracker (Arie Finance — internal Incorporation Monitor)  
**Operator app:** `python -m app.main` → http://127.0.0.1:8080  
**Tests:** `python -m pytest -q` from repository root

For a deeper line-by-line production audit, see `docs/INDEPENDENT_AUDIT_PROMPT.md`. **This prompt is narrower:** current state, gaps, and **small** improvements only.

---

## Production expectations (read first)

Treat this as a **production operational system**, not a prototype or demo.

Assume **non-technical relationship managers** depend on the output **daily** for real client acquisition activity.

Evaluate **reliability, consistency, operator trust, failure visibility, and operational safety** accordingly.

**Do not excuse:**

- ambiguous UX,
- silent failures,
- inconsistent data sources,
- temporary/demo affordances,
- undocumented manual recovery steps,
- or behaviour that depends on developer knowledge.

**Production-safe** means:

- deterministic queue behaviour,
- clear source provenance,
- predictable exports,
- recoverable failures,
- understandable empty states,
- stable scoring behaviour,
- and **no dependence on engineer supervision** for normal operation.

**Explicitly evaluate** whether operators can easily distinguish:

- **live vs historical** data,
- **verified registry data** vs inferred enrichment,
- **production vs development** behaviour,
- and **official vs internally generated** information.

Any remaining demo/development affordances that could mislead operators or create uncertainty in production should be treated as a **trust and operational risk issue**.

**Snapshot freshness (operational risk):** Assess whether operators can easily determine:

- snapshot freshness,
- last successful refresh,
- partial-refresh failures,
- and whether the currently displayed data is **complete and trustworthy**.

An RM acting on stale or partial data is a **business risk**, not a minor UX issue.

---

## Your role

You are a **senior product engineer** reviewing an **operational fintech intelligence system** that must behave predictably every day — not an “interesting lead-gen prototype.”

You are advising a **startup fintech** where this tool is **business-critical** for daily commercial use. Be direct, practical, and evidence-based. Cite **file paths** (and line numbers where useful). Run the app and tests; do not rely on assumptions.

**Evidence standard (required):** Every material claim must be backed by one of:

- **runtime verification**,
- **test evidence**,
- **code-path citation**, or
- **explicit documentation**.

Label anything **not** verified at runtime explicitly (e.g. “code-inferred”, “docs-only”, “not runtime-tested”).

**Prefer runtime behaviour over documentation/comments where they conflict.** Do not write “appears production-safe”, “likely deterministic”, or “seems stable” without stating the evidence class.

Avoid speculative language (“probably”, “appears”, “likely”) unless explicitly labelled as **inference**. Operational conclusions should be **evidence-backed**, not intuition-backed.

**Bar for success:** A non-technical relationship manager can rely on this tool daily in production to identify trustworthy prospects, understand why each company was surfaced, assign ownership, export outreach-ready data, and verify information through official registries — **without engineering intervention, hidden manual steps, or ambiguous system behaviour.**

---

## System intent and architecture (verify against runtime behaviour and code)

- **Purpose:** Daily queue of newly incorporated **UK** and **Mauritius (GBC/AC)** companies, ranked by heuristic fit score (0–100), for direct-client onboarding at Arie Finance.
- **Not:** A CRM, introducer auto-queue, or source of invented contact details.
- **Data path:** Pipeline writes `exports/YYYY-MM-DD.csv` → `uk_leads/data_loader.py` merges/enriches → FastAPI `app/main.py` → static UI `app/static/`.
- **Modes:** `APP_MODE` in `.env` (`development` vs `production` / `rm`) — see `uk_leads/app_mode.py`. Production limits live registry refresh from the operator UI; development allows it.
- **Optional:** OpenAI brief in lead detail panel; Companies House people enrichment for UK rows.

Read first: `README.md`, `docs/CLASSIFICATION.md`, `uk_leads/app_mode.py`, `app/main.py`, `app/static/app.js`, `uk_leads/data_loader.py`.

---

## Review objectives

### 1. Current status snapshot (required)

Produce a short **“as of today”** assessment for **operationally dependable, daily commercial use**:

| Area | Status (Green / Amber / Red) | One-sentence evidence |
|------|------------------------------|------------------------|
| Operator can load leads for a snapshot date | | |
| UK data path reliable | | |
| Mauritius data path reliable | | |
| Date navigation usable | | |
| Scoring + “why contact” actionable | | |
| Assignments persist | | |
| Export usable for outreach | | |
| Production vs dev behaviour clear to operators | | |
| Operators can distinguish verified vs inferred data | | |
| Operators can distinguish live vs stale snapshots | | |
| Ranking/scores/exports deterministic for same snapshot | | |
| CI / tests trustworthy | | |
| Deploy / ops documented enough for production | | |

Include: latest relevant commits on `main` (run `git log -5 --oneline`), test count from `pytest -q`, and whether README matches actual behaviour.

### 2. Gaps and issues (required)

List **every material gap** you find, grouped as:

- **P0 — Blocks daily commercial use** (wrong data, crashes, trust/compliance risk, data loss, silent failure)
- **P1 — Operational friction or missed leads** (confusing UX, unclear failures, inconsistent state)
- **P2 — Hardening / maintainability** (polish that improves long-term dependability)

For each item: **what** | **where** (file/path) | **who is hurt** (RM / ops / engineer) | **fix type** (config / copy / bug / docs — not “build a new module”) | **evidence** (runtime / test / code / docs).

**Single source of truth:** Identify any duplicate data paths, legacy fallbacks, shadow state, or parallel workflows that could cause operators to see **inconsistent lead data** or **inconsistent application behaviour** (e.g. multiple CSV naming schemes, competing refresh paths, duplicate filter state, multiple server processes).

**Explicitly check:**

- Demo vs production confusion (`demo` query param, “cap UK top 25”, `LIVE SNAPSHOT` / `DEV MODE` badges, `operator_refresh_allowed`) — frame as **production trust risks**, not acceptable quirks
- Whether queue reads **only** canonical `exports/{date}.csv` or still mixes legacy `uk-leads-demo-*.csv` (see `tests/test_canonical_merge.py`)
- Mauritius director gap and whether operators are clearly told what is **verified** vs **unavailable**
- Multiple local servers on different ports (8080 vs 8082) — operational confusion and stale-process risk
- Empty states, loading errors, and what happens with **no** `exports/` on first run — must be recoverable without engineer tribal knowledge
- Assignment / status field mismatches between UI and backend (if any remain)
- **Security:** Assess whether current route exposure (`/`, `/dev`), environment controls, and operational safeguards are appropriate for a **production fintech workflow** handling commercial lead intelligence. **Distinguish between:** acceptable on an **internal trusted network**, acceptable for **authenticated internal production use**, and acceptable for **public internet exposure**. Classify overall as one of those three (or **not acceptable without remediation**) — do not default to leniency
- **Deterministic ranking:** Assess whether the same snapshot and inputs consistently produce the same ranking, scores, and export ordering across reloads and environments (runtime-test if possible)
- Playwright / Mauritius scrape failures — failure visibility and operator messaging in production
- Observability: can ops detect pipeline failure, stale snapshots, or partial data without reading logs?

**Do not** recommend invented emails, fake LinkedIn, or unverified “AI facts.”

### 3. Recommendations — stronger tool, **no substantial new features** (required)

The team will **not** add major new product areas (full CRM, introducers tab, new registry APIs, React rewrite, multi-module workflow).

**Prefer hardening, simplification, clarity, and operational trust over adding capabilities.**

Recommend only changes that **compound value** from what already exists:

**Allowed (examples):**

- Copy, defaults, and env clarity (`APP_MODE`, `.env.example`)
- Bug fixes and single-source-of-truth refactors
- Clearer empty/loading/error messages (no silent failure)
- Small export column improvements (outreach-ready for Sheets/CRM)
- Score threshold labels, hero metrics, filter wording
- Reliability: retries, timeouts, idempotent refresh, snapshot retention docs
- Remove or hide dead UI / misleading demo/development affordances
- Tighten tests for paths RMs rely on in production
- One-page RM morning playbook using **existing** features — written for non-technical operators
- Responsible use of existing OpenAI brief (disclaimers, labelled as internal/AI-generated, no hallucinated contacts)
- External research may support operational improvements to the current workflow, but must **not** introduce new product surfaces, new workflow categories, or speculative roadmap expansion

**Not allowed (call out if tempted, then reject):**

- New registry connectors or “get UK-level API for every country”
- Full outreach workflow (follow-up CRM inside app) unless ≤2 fields already in backend
- Second queue / introducers automation
- Large AI agent platform (Manus-style) as a new subsystem
- Rebuild front end in React
- Roadmap-style feature expansion disguised as “recommendations”

Deliver a **prioritised table** (max **12 rows**):

| Priority | Recommendation | Why it improves daily commercial operations | Effort (S/M) | Complexity added (1–5, lower is better) |

### 4. Missing information for lead gen (brief)

Without new registry APIs, list the **top 5 data gaps** that limit outbound quality today (e.g. website, director contact, payment intent). For each: **workaround using existing data + human verification** vs **do not do** (invented contact).

One short paragraph only — not a research report.

---

## How to work

1. Read the entry-point files listed above.  
2. Run `python -m pytest -q` and report **exact** pass/fail count and command used.  
3. Skim `.github/workflows/` for pipeline and test CI.  
4. **Runtime verification (required attempt):** Start the production operator app and report:
   - exact startup command run,
   - whether startup succeeded,
   - startup errors (if any),
   - HTTP outcomes for `/`, `/api/meta`, `/api/available-dates`, and `/api/leads` (use a date that exists in `exports/`, or document absence and impact),
   - and any **runtime mismatches** vs README or code comments.
   
   If runtime verification is blocked, explain **exactly why** instead of inferring behaviour.  
5. Compare `docs/UI_DONE_CHECKLIST.md` to production `app/static/index.html` — note stale checklist items; label conflicts as runtime-verified vs docs-only.

---

## Deliverable format (strict)

Keep the full response **under ~2,500 words** unless P0 list forces more detail.

1. **Executive summary** — 6–8 bullets for a non-technical founder, including: **“production-safe for daily RM operations: yes / partial / no”** with one sentence why. State what was **runtime-verified** vs inferred.  
2. **Runtime verification log** — commands run, outcomes, API status codes or errors (brief).  
3. **Current status table** (section 1) — each row cites evidence class.  
4. **Gaps & issues** — P0, then P1, then P2 (bullet lists); each item labelled runtime-verified or code/docs-inferred.  
5. **Lightweight recommendations table** (section 3, max 12 rows).  
6. **Top 5 missing data elements** (section 4).  
7. **Three things already operationally dependable** — specific, with evidence class.  
8. **Open questions** — max 5 for the team (production exposure, data freshness, auth, recovery runbooks).

---

## Constraints

- UK and Mauritius treated with equal product respect.  
- Introducers stay manual outside this app.  
- Verify links must stay official registry URLs only.  
- Prefer **one port, one process** for local use: **8080**.  
- Review standard is **production operational dependability**, not prototype tolerance.  
- **Do not** classify intentionally out-of-scope product decisions (e.g. not a CRM, no full auth layer, no in-app outreach workflow) as defects unless they create **operational ambiguity, trust issues, or production risk** within the current workflow.  
- Do not implement code changes in this review unless asked.

---

*End of prompt.*
