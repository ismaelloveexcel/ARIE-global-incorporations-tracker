# Independent agent review prompt — ARIE Global Incorporations Tracker

Copy everything below the line into a **fresh** agent session with full repo access. The agent should read the codebase and README first, then produce a structured report.

---

## Role

You are an independent **product + engineering reviewer** for an internal fintech operations tool. You are not implementing changes unless explicitly asked at the end. Your job is to assess whether this repository is **efficient**, **maintainable**, and **meaningfully helps a growth-stage fintech acquire and onboard clients**.

## Company context (use for all recommendations)

**Arie Finance** ([ariefinance.com](https://www.ariefinance.com/)) is a **Mauritius-regulated** financial services provider (FSC) focused on:

- **International payments** and multi-balance accounts for complex businesses  
- **Two go-to-market motions** on the public site:  
  - **Global companies** — international businesses scaling cross-border  
  - **Management companies** — trusts, corporate services, and structures representing clients  
- Target segments include: trusts & management firms, holding companies/SPVs, scaleups, family offices, professional services, VC/PE, and EDD-heavy industries  
- Value props: competitive FX/payments, dedicated relationship managers (not chatbots), safeguarded funds, digital platform for multi-entity organisations  

This repo is **not** the customer-facing banking app. It is an **internal incorporation monitor**: daily leads from official registries (UK Companies House + Mauritius GBC/AC), heuristic scoring, team assignment, and verify links for ops/RMs.

## Critical product rules (do not ignore)

1. **Direct clients** — Must be fed **automatically** by pipeline + operator dashboard. This is the primary growth lever: catch newly incorporated companies early for onboarding outreach.  
2. **Introducers** — Must be maintained **manually** (CRM, spreadsheet, or future manual module). The dashboard must **not** auto-duplicate leads into a second “introducers” queue. Any auto name-based introducer **tab** is considered product debt.  
3. **UK verify links** must remain official Companies House URLs.  
4. **No fake data** — no invented companies, emails, or contacts.  
5. Score is **heuristic** (0–100), not a conversion model — critique presentation, not “ML accuracy,” unless calibration is proposed with clear data needs.

## Repository entry points

Start with:

- `README.md`  
- `app/main.py` + `app/static/` (operator UI)  
- `uk_leads/` (enrichment, dashboard rules, assignments)  
- `scoring/`  
- `main.py` / `run_uk_daily.py` (pipeline)  
- `tests/`  
- `/dev` operations UI (`app/static/dev.html`)

## Review objectives

### A. Efficiency & engineering health

- Architecture clarity: pipeline → merge → enrich → API → UI  
- Duplication, dead code, conflicting classifiers (`lead_type` vs `dashboard_tabs` vs tab filters)  
- Test coverage gaps that risk regressions in classification or assignments  
- CI/CD, observability, failure modes (stale data, API 404, partial Mauritius data)  
- Security & ops: secrets, assignment file locking, no auth on internal tool — acceptable risks vs fixes  
- Cost/latency: Companies House calls, caching, demo mode “top 25 UK”  

### B. Growth impact for Arie Finance

Map features to **how they help win clients**, aligned with [ariefinance.com](https://www.ariefinance.com/):

| Motion | How this tool could help | Current gap |
|--------|--------------------------|-------------|
| Direct onboarding | Early detection of new UK/MU corps matching ICP (fintech, payments, holdings, etc.) | ? |
| Management co / introducer | Manual introducer list + RM workflows; avoid duplicate auto queues | ? |
| RM productivity | Assignment, priority, notes, verify, brief | ? |
| Compliance trust | Official registry links, transparent scoring explanation | ? |

Answer: **If an RM used this 30 minutes every morning, what revenue or pipeline outcome improves in 90 days?** Be specific and skeptical.

### C. UX for non-technical operators

- Can a new RM understand the job in **under 60 seconds**?  
- Is the UI queue-first (work before explanation)?  
- Jurisdiction-neutral (UK not privileged in copy or controls)?  
- Mobile-usable in a pinch (390px)?  

### D. Recommendations — make it a **powerful client-acquisition tool**

Provide a **prioritised** list (P0 / P1 / P2) of recommendations, each with:

- **What** to build or change  
- **Why** it matters for Arie’s ICP and GTM  
- **Effort** (S / M / L)  
- **Risk** if not done  

Include ideas such as (only if justified after reading the code):

- ICP tuning tied to Arie segments (management companies vs scaleups vs payments)  
- Outreach workflow: status, follow-up dates, contact log, CRM export  
- Manual introducers module (lightweight) vs external CRM  
- Mauritius data completeness (directors/PSC when API exists)  
- Alerting when high-priority lead appears  
- Conversion feedback loop (won/lost) to improve scoring over time  
- Integration with marketing site inbound (contact@ariefinance.com leads)  

Do **not** recommend a React rewrite unless strongly justified.

## Deliverable format

1. **Executive summary** (≤ 10 bullets) for a non-technical founder  
2. **Architecture diagram** (Mermaid) of current data flow  
3. **Strengths** (what already helps growth)  
4. **Gaps & risks** (honest, ranked)  
5. **Product recommendations** (P0/P1/P2 table)  
6. **Engineering recommendations** (P0/P1/P2 table)  
7. **90-day roadmap** — three phases, outcome-oriented  
8. **Open questions** for the team (max 5)  

## Verifying tests (required)

From the **repository root**, run:

```bash
python -m pytest -q
```

- Report the **exact pass/fail count** and command used.  
- If collection fails, show the **full error** — do not claim “tests are broken” without it.  
- A healthy local suite can still lack CI enforcement; check `.github/workflows/test.yml` for PR test runs.  
- Distinguish **“no CI on PRs”** (engineering gap) from **“pytest fails”** (regression).

## Classification contract (verify in code)

Read `docs/CLASSIFICATION.md` before critiquing introducers:

- **Operator queue** = `direct_clients` only (automatic).  
- **`tab=introducers`** = deprecated, returns `[]` — legacy API, not an active product bug.  
- **`is_introducer()` / `lead_type`** = metadata hints only unless explicitly scoped to enrichment.

## Constraints for the reviewer

- Read actual code; do not assume features from this prompt alone.  
- Treat all jurisdictions equally in UX critique.  
- Do not propose fake data or misleading “AI certainty.”  
- Separate **operator dashboard** (`/`) from **dev/ops** (`/dev`).  
- Note anything that should stay out of scope for a small team.

## Optional stretch (only if time permits)

- Compare this approach to buying a generic sales intelligence tool.  
- One-page “RM morning playbook” using only features that exist today.

## UI sign-off (front end)

Before approving the operator dashboard HTML, use **`docs/UI_DONE_CHECKLIST.md`**. Annotated markup for reviewers: **`docs/review/index-revised.html`** (production: `app/static/index.html`).

---

*End of prompt.*
