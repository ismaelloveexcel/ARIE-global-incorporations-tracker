# Independent agent audit prompt — production readiness & lead generation

**Copy everything below the horizontal rule into a fresh agent session** with full repository access (read, run commands, optional browser). You are performing an **end-to-end audit**, not implementing fixes unless the team explicitly asks afterward.

**Repository:** ARIE Global Incorporations Tracker  
**Latest operator UI:** `app/static/index.html`, `app.js`, `styles.css`  
**API / server:** `app/main.py`  
**Pipeline:** `main.py`, `uk_leads/`, `scoring/`, `connectors/`

---

## Role

You are an independent **product auditor + senior engineer + growth operator** reviewing an internal tool that must help a **startup fintech** win real clients. This is **not a demo or proof-of-concept review**. The bar is: *Can a relationship manager use this every working day to discover incorporations, decide who to contact, and move prospects forward with confidence?*

Be **skeptical, specific, and evidence-based**. Cite file paths and line ranges. Do not assume features exist—verify in code and by running the app.

---

## Company context (non-negotiable)

**Arie Finance** is a Mauritius-regulated financial services provider (FSC) serving international businesses, management companies, trusts, and complex structures. Go-to-market motions include **direct client onboarding** and **introducer / management-company relationships**.

This repository is the **internal Incorporation Monitor**: daily leads from official registries (UK Companies House + Mauritius GBC/AC via MNS scraper), heuristic scoring, assignment, verify links, notes, optional AI brief.

**Success in 90 days looks like:** RMs consistently find high-fit newly incorporated companies, understand *why* to contact them, assign ownership, and hand off to outreach (CRM/spreadsheet) without duplicate work or false confidence.

---

## Critical product rules (verify; flag violations)

1. **Direct clients queue** — Primary automatic feed. Operator UI uses `direct_clients` only.  
2. **Introducers** — **Manual** outside this tool (CRM/spreadsheet). No auto introducers tab/queue. `tab=introducers` is deprecated (empty list)—not a bug if documented.  
3. **No fake data** — No invented companies, emails, phone numbers, or LinkedIn URLs.  
4. **Verify links** — UK → official Companies House URLs only. Mauritius → official MNS/search URLs only.  
5. **Scoring** — Heuristic 0–100, explainable—not a trained conversion model unless the team adds labeled outcomes later.  
6. **Jurisdiction parity** — UX and copy must not treat UK as “real” and Mauritius as secondary (audit for bias in defaults, empty states, and loading behaviour).

Read `docs/CLASSIFICATION.md` before critiquing classification or introducer logic.

---

## Audit mandate: stop treating this as a demo

The codebase still contains **demo-mode** concepts (e.g. UK “top 25 by score”, `demo` query flags, `uk-leads-demo-*.csv`). Your audit must answer:

| Question | Required evidence |
|----------|-------------------|
| What still behaves like a **demo** vs **production**? | List flags, UI copy, caps, filenames, defaults |
| What must change for **daily production use** by 2–5 RMs? | P0 list with file references |
| Is “Cap UK volume (top 25)” acceptable in production? | Recommend keep/remove/rename and default |
| Can users **generate and use prospects end-to-end** today without engineer help? | Step-by-step truth test |
| What breaks on a **fresh deploy** with only `.env` and no `exports/`? | Document recovery path |

**Deliverable:** a **“Demo → Production”** table: *Current behaviour | Risk | Recommended change | Effort S/M/L*.

---

## Part 1 — Line-by-line & module audit (required)

Walk these areas **in order**. For each file/module, note: purpose, correctness, dead code, error handling, and operator impact.

### 1.1 Operator front end (`app/static/`)

- `index.html` — Valid HTML5 (no invalid tags), semantics, a11y, `colspan` vs column count vs `TABLE_COLSPAN` in JS.  
- `app.js` — Single source of truth for filters (`filterState`), date navigation, loading/empty states, fetch flows (UK auto-load, Mauritius auto-load), export, detail panel, keyboard a11y.  
- `styles.css` — Decision UI, mobile ~390px, contrast, cognitive load (one primary action per screen).  

**Method:** Read file sequentially; note line ranges for every issue (P0/P1/P2).

### 1.2 API layer (`app/main.py`)

- Every route: inputs, errors, side effects, auth (none today—risk?).  
- `/api/leads`, `/api/refresh`, `/api/refresh/mauritius`, `/api/available-dates`, assignment PATCH, people enrichment, brief generation.  
- Timeouts, partial failures, 404 vs empty responses.

### 1.3 Data loading & snapshots (`uk_leads/data_loader.py`, `mauritius_snapshot.py`, `refresh_meta.py`)

- How dates appear in the picker (30-day window, snapshots, refresh meta).  
- Merge logic UK + Mauritius; dedupe; enrichment order.  
- What is persisted vs ephemeral.

### 1.4 Scoring & enrichment (`scoring/engine.py`, `uk_leads/enrichment.py`, `uk_leads/score_explain.py`, `uk_leads/signals.py`)

- ICP alignment with Arie segments (payments, holdings, GBC/AC, professional services as *hint* not auto-introducer queue).  
- Whether scores and “why contact” text help an RM **act**, not just read.  
- Gaps where score is high but lead is not actually contactable.

### 1.5 Connectors (`connectors/companies_house.py`, `connectors/mauritius.py`)

- Reliability, rate limits, Playwright fragility, retries, failure messages to operators.  
- **Assume no new registry APIs** will be added (no new “UK-level” integrations). Audit **workarounds** already in repo and what’s missing.

### 1.6 Pipeline & CI (`main.py`, `.github/workflows/daily_pipeline.yml`, `run_uk_daily.py`)

- Daily automation, snapshot retention (cache/artifacts), dry-run defaults in CI.  
- Whether production deploy receives cumulative `exports/` or only latest artifact.

### 1.7 Assignments & persistence (`uk_leads/assignments.py`, `data/assignments.json`)

- Concurrency, data loss risk, backup, round-robin fairness.

### 1.8 Tests (`tests/`)

Run from repo root:

```bash
python -m pytest -q
```

Report exact pass/fail count. Map **critical paths without tests** (classification, date nav, Mauritius merge, assignment PATCH).

### 1.9 Ops UI (`app/static/dev.html`, `dev.js`)

- What operators must use vs what only engineers should see.

---

## Part 2 — End-to-end operator journey (required)

Execute or simulate this **morning playbook** and document every friction point:

1. **Deploy / first open** — No snapshots yet; only API keys in `.env`.  
2. **Pick yesterday’s date** — UK load; Mauritius load (timing, errors).  
3. **Review “High priority” (≥70)** — Are leads actually worth calling?  
4. **Open row detail** — Score breakdown, classification, directors (UK), Mauritius limitations.  
5. **Assign** to RM; add note.  
6. **Export CSV** — Usable in CRM/email tool?  
7. **Optional AI brief** — If `OPENAI_API_KEY` set: quality, hallucination risk, usefulness.  
8. **Next day** — Date navigation; historical snapshots; assignment persistence.

**Deliverable:** journey map (Mermaid sequence or flowchart) + **friction log** (step | what happened | severity | fix type product/engineering).

---

## Part 3 — Information gaps for stronger lead generation (required)

The team **will not** receive additional registry APIs comparable to UK Companies House. Identify what data the tool **does not have today** but that would materially improve **outbound quality** for a regulated fintech.

Structure as a table:

| Data element | Why it matters for Arie | Available today? | Reliable workaround (no new registry API) | Unreliable / do not recommend |
|--------------|-------------------------|------------------|-------------------------------------------|-------------------------------|
| e.g. Director email | Outreach | | LLM + public web with citation? Manual? | Invented email |
| e.g. Website / domain | Fit signal | | | |
| e.g. LinkedIn company | Research | | | |
| e.g. Payment / FX intent | ICP | | SIC + name heuristics | Fake intent |
| e.g. Group structure / UBO | Compliance prep | | CH PSC (UK only) | |
| … | | | | |

Be explicit about **Mauritius director/PSC gap** and what operators should do until MNS API exists.

**Deliverable:** top **10 missing fields**, ranked by revenue impact vs effort, with **only workarounds that preserve trust** (official links, human verification, labeled uncertainty).

---

## Part 4 — Stronger tool without unnecessary complexity (required)

Provide recommendations that help a **startup** ship value fast. **Avoid** CRM rebuilds, React rewrites, or multi-tab product sprawl unless overwhelmingly justified.

### 4.1 AI / LLM (OpenAI already optional for briefs)

Evaluate **responsible** uses of ChatGPT-class APIs (and mention alternatives like Manus/agent tools only where they add clear ops value):

| Use case | Value | Risk | Verdict (do / defer / never) |
|----------|-------|------|------------------------------|
| One-paragraph outreach hook from **registry facts only** | | Hallucination | |
| Company research summary with **mandatory citations** | | Cost, privacy | |
| Fit explanation in plain English | | Overconfidence | |
| Auto-send email | | Compliance | likely **never** |

Rules: no invented contacts; label AI-generated text; human approves before send.

### 4.2 Non-API workarounds (preferred)

Ideas to consider (only if validated against code):

- Scheduled Playwright + snapshot archive (already partially in CI).  
- Website discovery from company name (DNS/search) with confidence score.  
- “Copy outreach pack” (verify link + why contact + suggested hook) to clipboard.  
- Slack/email **alert** when pursue-now count &gt; N.  
- Lightweight outcome capture (contacted / not fit) **without** full CRM.  
- Conversion feedback later to tune weights (needs discipline).  
- Better **export** columns for HubSpot/Pipedrive/Sheets.

### 4.3 What to **not** build (guardrails)

List features that would **complicate** the tool without proportional gain for a small team.

**Deliverable:** P0 / P1 / P2 table — *Recommendation | Why (growth) | Effort S/M/L | Complexity cost (1–5) | Depends on*.

---

## Part 5 — Production & reliability (required)

| Area | Questions |
|------|-----------|
| Auth | Is open `/` acceptable on internal network only? |
| Hosting | Persistent `exports/` volume? Playwright on server? |
| Secrets | `.env` handling; keys in CI |
| Monitoring | How ops know pipeline failed |
| Data retention | Snapshot growth; GDPR-ish sensitivity |
| Performance | Mauritius scrape blocking UI; concurrent RMs |
| Disaster recovery | Rebuild assignments; lost exports |

---

## Part 6 — UX / UI excellence (required)

Apply a **brutally honest** UX review (startup bar: excellent, not “fine for internal”):

- First-time user knows what to do in **5 seconds**.  
- One primary action per screen.  
- Empty states guide action.  
- No template-SaaS feel; intentional Arie branding.  
- Mobile 390px usable for triage.

Cross-check `docs/UI_DONE_CHECKLIST.md` and `docs/review/index-revised.html` against **production** `app/static/index.html` (checklist may be stale—note discrepancies).

---

## Deliverable format (strict)

Your final report must include:

1. **Executive summary** (≤ 12 bullets) for a **non-technical founder** — include “production-ready: yes/no/partially” and why.  
2. **Demo vs production** table (see mandate above).  
3. **Architecture diagram** (Mermaid) — pipeline → storage → API → UI.  
4. **Line-by-line findings index** — grouped by file with severity counts (P0/P1/P2).  
5. **E2E journey friction log**.  
6. **Missing data & workarounds** table (Part 3).  
7. **Recommendations** — product and engineering tables (P0/P1/P2).  
8. **AI / automation** subsection — what to use, what to avoid.  
9. **90-day roadmap** — three phases, outcome-oriented for a startup team.  
10. **Open questions** (max 7) for leadership.  
11. **Test & CI report** — exact `pytest` output summary + workflow gaps.

### Severity definitions

- **P0** — Blocks daily use, wrong data, trust/compliance risk, or data loss.  
- **P1** — Material friction or missed leads; fix within weeks.  
- **P2** — Polish, maintainability, nice-to-have.

---

## Constraints for the auditor

- Read actual code; run tests; run the app if possible (`python -m app.main`).  
- Do not propose invented contact data or unverified “AI facts.”  
- Do not recommend a React rewrite unless evidence is overwhelming.  
- Separate operator UI (`/`) from ops UI (`/dev`).  
- Treat Mauritius and UK with equal product respect.  
- When recommending LLM features, include **human-in-the-loop** and **compliance** notes for a regulated fintech.

## Optional stretch

- Compare build-vs-buy for sales intelligence (1 page).  
- Draft **RM morning playbook** (one page) using only features that exist **after** your recommended P0 fixes.  
- Estimate **cost per month** (API + hosting + LLM) for 5 daily users.

---

*End of audit prompt.*
