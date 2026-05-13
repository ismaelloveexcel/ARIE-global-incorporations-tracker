# ARIE — Global Incorporations Tracker

> **A deterministic, auditable, multi-jurisdiction corporate intelligence pipeline.**

---

## Table of Contents

1. [What This System Is](#1-what-this-system-is)
2. [Why It Exists](#2-why-it-exists)
3. [Long-Term Vision](#3-long-term-vision)
4. [Current Jurisdictions Supported](#4-current-jurisdictions-supported)
5. [System Architecture](#5-system-architecture)
6. [Data Flow](#6-data-flow)
7. [Deduplication Philosophy](#7-deduplication-philosophy)
8. [Scoring Methodology](#8-scoring-methodology)
9. [Why Canonical Entities Matter](#9-why-canonical-entities-matter)
10. [Mauritius Snapshot Reconciliation](#10-mauritius-snapshot-reconciliation)
11. [How to Run Locally](#11-how-to-run-locally)
12. [GitHub Actions Automation](#12-github-actions-automation)
13. [Future Roadmap](#13-future-roadmap)

---

## 1. What This System Is

ARIE (Automated Registration Intelligence Engine) is a production-grade, backend-only pipeline that:

- **Ingests** newly registered companies daily from multiple jurisdictions
- **Normalises** raw records into a unified internal schema
- **Deduplicates** related entities across jurisdictions using fuzzy name matching
- **Scores** each entity deterministically on a 0–100 scale based on jurisdiction, entity type, sector, and name signals
- **Persists** all records and canonical entity graphs to Supabase (PostgreSQL)
- **Exports** structured CSV snapshots for downstream compliance, lead intelligence, and outbound workflows

This is **not** a scraper demo, a dashboard, or a frontend project. It is an auditable data pipeline whose outputs feed into compliance workflows, relationship-mapping systems, and outbound intelligence tools.

---

## 2. Why It Exists

Global corporate registrations are publicly available but fragmented. Each jurisdiction exposes its own interface — some via structured API, others via JavaScript-rendered portals with no public API. Tracking newly incorporated entities manually across even three jurisdictions is operationally impractical.

Beyond raw ingestion, the real intelligence challenge is **entity resolution**: the same real-world company may appear as:

- `Alpha Holdings Ltd` in the UK Companies House register
- `Alpha Holdings SPV` in the DIFC register
- `Alpha Holdings GBC` in the Mauritius MNS register

Without a deduplication layer these are treated as three unrelated records. With it, they resolve to a single canonical entity — enabling cross-jurisdictional relationship mapping, compliance tracking, and enrichment.

ARIE solves this end-to-end: ingest → normalise → deduplicate → score → persist → export.

---

## 3. Long-Term Vision

This repository is intended to evolve into a **multi-jurisdiction corporate intelligence and relationship-mapping engine** — not merely a scraper.

The long-term roadmap includes:

- Expanding to 20+ jurisdictions (BVI, Cayman, Jersey, Singapore, Hong Kong, Luxembourg, Delaware, etc.)
- Building a canonical entity graph with ownership, director, and shareholder edges
- Enriching entities with beneficial ownership data (e.g. OpenCorporates, OpenSanctions)
- Integrating with sanctions databases (OFAC, EU, UN) for automated compliance screening
- Supporting outbound CRM workflows (HubSpot, Salesforce) via scored lead export
- Providing a queryable GraphQL API over the canonical entity graph
- Enabling real-time alerting for high-score entities (Slack, email, webhook)

Every architectural decision made today — UUID keys, raw JSONB payloads, normalised names, canonical entity IDs — is designed with this multi-year trajectory in mind.

---

## 4. Current Jurisdictions Supported

| Jurisdiction | Source | Method | Date Filtering |
|---|---|---|---|
| United Kingdom | UK Companies House API | REST API (`advanced-search`) | ✅ Native (`incorporated_from` / `incorporated_to`) |
| DIFC | DIFC Public Register | Playwright (headless browser) | ✅ Post-scrape filter by `incorporation_date` |
| Mauritius | MNS Online Search | Playwright + snapshot diff | ⚠️ Snapshot reconciliation (no reliable date filter) |

**Mauritius target entity types:**

- Global Business Companies (GBC)
- Authorised Companies

---

## 5. System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         main.py (CLI orchestrator)                  │
└──────────────┬──────────────┬──────────────────────────────────────┘
               │              │
   ┌───────────▼──┐  ┌────────▼──────────┐  ┌──────────────────────┐
   │  connectors/ │  │  connectors/      │  │  connectors/         │
   │  companies_  │  │  difc.py          │  │  mauritius.py        │
   │  house.py    │  │  (Playwright)     │  │  (Playwright +       │
   │  (REST API)  │  │                   │  │   snapshot diff)     │
   └──────┬───────┘  └────────┬──────────┘  └──────────┬───────────┘
          │                   │                         │
          └───────────────────┴─────────────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │  normalization/    │
                    │  schema.py         │
                    │  CompanyRecord     │
                    │  normalize_name()  │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │  scoring/          │
                    │  engine.py         │
                    │  score() → 0–100   │
                    └─────────┬──────────┘
                              │
                    ┌─────────▼──────────┐
                    │  deduplication/    │
                    │  matcher.py        │
                    │  RapidFuzz ≥92     │
                    └─────────┬──────────┘
                              │
               ┌──────────────┴───────────────┐
               │                              │
     ┌─────────▼──────────┐       ┌───────────▼──────────┐
     │  db/               │       │  exports/            │
     │  supabase_client.py│       │  YYYY-MM-DD.csv      │
     │  (PostgreSQL)      │       │                      │
     └────────────────────┘       └──────────────────────┘
```

### Module breakdown

| Module | Responsibility |
|---|---|
| `connectors/companies_house.py` | Fetches UK incorporations via official REST API with pagination and retry/backoff |
| `connectors/difc.py` | Playwright scraper for the DIFC public register with date-based filtering |
| `connectors/mauritius.py` | Playwright scraper + SHA-256 snapshot reconciliation for MNS |
| `normalization/schema.py` | `CompanyRecord` dataclass and `normalize_name()` utility |
| `scoring/engine.py` | Deterministic 0–100 scoring across four dimensions |
| `deduplication/matcher.py` | RapidFuzz-based cross-jurisdiction entity resolution |
| `db/supabase_client.py` | Supabase/PostgreSQL read and write helpers |
| `db/schema.sql` | Production DDL (run once against your Supabase project) |
| `main.py` | CLI pipeline orchestrator |

---

## 6. Data Flow

```
1. INGEST
   ├── Companies House → list[CompanyRecord]
   ├── DIFC Playwright → list[CompanyRecord]
   └── Mauritius Playwright + snapshot diff → list[CompanyRecord]

2. SCORE
   └── Each CompanyRecord.score = engine.score(record)   [0–100]

3. DEDUPLICATE
   ├── Load existing normalised names from DB
   ├── For each record: fuzzy-match against index (token_sort_ratio ≥ 92)
   ├── Match found → reuse existing canonical_entity_id
   └── No match → INSERT new canonical_entity, assign new id

4. PERSIST
   ├── INSERT INTO companies (all records + canonical_entity_id)
   └── UPSERT canonical_entities (create or update jurisdictions/dates)

5. EXPORT
   └── Write exports/YYYY-MM-DD.csv
       Columns: company_name, jurisdiction, entity_type,
                incorporation_date, score, canonical_entity_id, source
```

**Idempotency guarantee:** The pipeline can be re-run for the same date window without creating duplicate canonical entities. The deduplicator loads the full existing index before processing any new records, and `upsert_canonical_entity` uses `canonical_name` as the upsert key.

**Connector isolation:** A failure in any single connector (network error, site change, API rate limit) is caught and logged. The pipeline continues processing records from the remaining connectors.

---

## 7. Deduplication Philosophy

### The problem

Company names vary significantly across jurisdictions. A single real-world entity may incorporate under slightly different names in different jurisdictions:

| Jurisdiction | Registered name |
|---|---|
| UK | `Alpha Holdings Ltd` |
| DIFC | `Alpha Holdings SPV` |
| Mauritius | `Alpha Holdings GBC` |

Without deduplication, all three generate separate unrelated records. With cross-jurisdiction deduplication, they resolve to a single canonical entity — enabling relationship tracking, compliance workflows, and enrichment pipelines that operate at the entity level rather than the registration level.

### The algorithm

1. **Name normalisation** — before any comparison, all names go through `normalize_name()`:
   - Unicode NFKD normalisation → ASCII fold
   - Lowercase
   - Punctuation removal
   - Whitespace collapse
   - Iterative legal suffix stripping (LTD, LIMITED, GBC, SPV, HOLDINGS, LLC, LLP, PLC, AUTHORISED COMPANY, FOUNDATION, INC, SPV, etc.)

   Result: `"Alpha Holdings Ltd"` → `"alpha"` becomes `"alpha"` across all three variants.

2. **Fuzzy matching** — `rapidfuzz.fuzz.token_sort_ratio` is applied between the incoming normalised name and every entry in the in-memory index.

3. **Threshold** — a score of **≥ 92** triggers a match. This threshold was chosen to be tight enough to avoid false positives (common words like "capital" or "holdings" matching unrelated entities) while being tolerant of minor spelling variations.

4. **Index bootstrap** — at the start of each pipeline run, the deduplicator loads all existing company rows from the database into memory. This ensures the matching is consistent across runs and new records are matched against the full historical corpus, not just within the current day's batch.

5. **Canonical entity update** — when a match is found in a new jurisdiction, `canonical_entities.jurisdictions` is updated to include the new jurisdiction. This continuously enriches the cross-jurisdiction picture.

### Why not exact matching?

Exact string matching after normalisation would miss common real-world variations:
- Unicode encoding differences
- Extra spaces or punctuation
- Minor transliteration differences
- Abbreviation vs full form (e.g. `Intl` vs `International`)

The fuzzy layer bridges these gaps while remaining deterministic and auditable.

---

## 8. Scoring Methodology

Each company record receives a deterministic score from 0 to 100. The score is computed from four independent dimensions, each with a defined maximum contribution.

### Dimension 1 — Entity Type (max 40 pts)

| Entity type | Score |
|---|---|
| Global Business Company (GBC) | 40 |
| DIFC SPV | 35 |
| Authorised Company | 30 |
| Company Limited by Shares / LLC | 30 |
| UK Private Limited Company / LTD | 15 |
| UK Public Limited Company / PLC | 20 |
| UK LLP | 20 |

Higher-scoring entity types are vehicles commonly used in offshore structuring, financial services, and wealth management — making them higher-priority intelligence targets.

### Dimension 2 — Jurisdiction (max 20 pts)

| Jurisdiction | Score |
|---|---|
| Mauritius | 20 |
| DIFC | 18 |
| UK | 12 |

Mauritius and DIFC are primary offshore financial centres and warrant higher baseline attention.

### Dimension 3 — Sector / SIC Code (max 20 pts, UK only)

| SIC prefix | Sector | Score |
|---|---|---|
| 64xx | Financial service activities | 20 |
| 65xx | Insurance / reinsurance | 20 |
| 66xx | Auxiliary financial activities | 18 |
| 62xx | Computer programming / IT | 15 |
| 63xx | Information service activities | 15 |
| 70xx | Head offices / management consultancy | 12 |
| 74xx | Other professional / scientific | 10 |
| 69xx | Legal and accounting | 8 |
| 68xx | Real estate | 6 |

SIC codes are a UK-only signal (Companies House API provides them). Non-UK records always score 0 on this dimension.

### Dimension 4 — Keyword Detection (max 20 pts, capped)

The company name is scanned for high-signal keywords using regex. Scores accumulate but are capped at 20 pts total.

Keywords include: `fintech`, `crypto`, `payments`, `blockchain`, `digital asset`, `defi`, `web3`, `nft`, `offshore`, `structuring`, `holdings`, `capital`, `investment`, `venture`, `fund`, `insurance`, `remittance`, `exchange`, `lending`, `custod(y|ian)`, `wallet`, `paytech`, `regtech`.

### Score interpretation

| Range | Signal |
|---|---|
| 75–100 | Very high priority — offshore financial vehicle with sector and keyword signals |
| 50–74 | High priority — significant jurisdictional or type signal |
| 30–49 | Medium — worth monitoring |
| 0–29 | Low priority — generic UK Ltd or similar |

---

## 9. Why Canonical Entities Matter

The `canonical_entities` table is the **intelligence layer** of this system.

Without it, the system is a list of company registrations. With it, the system becomes a cross-jurisdiction entity graph.

A canonical entity represents a **real-world organisation** regardless of:
- How many jurisdictions it has registered in
- What legal suffix it uses in each jurisdiction
- Minor name variations across registries

Each canonical entity accumulates:
- All jurisdictions it has been observed in (`jurisdictions TEXT[]`)
- The earliest date it was first seen (`first_seen DATE`)
- The most recent date it was observed (`last_seen DATE`)

This enables queries such as:
- "Show me all entities that appear in both Mauritius and DIFC"
- "Which entities were first seen more than 12 months ago but are still active in three jurisdictions?"
- "Find all entities with a score > 70 that have not been assigned to a CRM owner"

As the system evolves, canonical entities will become the anchors for beneficial ownership graphs, sanctions screening results, director network mapping, and outbound CRM records.

---

## 10. Mauritius Snapshot Reconciliation

The Mauritius MNS Online Search portal does not expose a reliable date filter. It is not possible to query "companies incorporated after date X" directly.

### The challenge

Without date filtering, the only way to identify new entities is to:
1. Scrape the **entire** register on each run
2. Compare the current scrape against the previous scrape
3. Emit only entities that appear in the current scrape but were absent from the previous one

This is the **snapshot reconciliation model**.

### Implementation

1. On each run, the Mauritius connector scrapes all pages of the MNS register and builds a `current_snapshot` dict: `{ SHA-256(name)[:16] → company_name }`.

2. It loads the `previous_snapshot` from `snapshots/mauritius_snapshot.json`.

3. Any name hash present in `current_snapshot` but absent from `previous_snapshot` is treated as a new entity and emitted as a `CompanyRecord`.

4. After the run, the snapshots are merged and saved: `{ ...previous_snapshot, ...current_snapshot }`. The snapshot grows monotonically — once a name is seen it is never re-emitted.

5. On the **very first run** (no snapshot file exists), the connector emits all scraped entities. This is intentional: the first run bootstraps the baseline.

### SHA-256 hashing

Each company name is hashed using `hashlib.sha256` (first 16 hex characters used as the key). This:
- Normalises case and whitespace before hashing (`name.strip().lower()`)
- Produces a stable, compact key
- Avoids storing full names as dict keys (though names are also stored as values for auditability)

### Snapshot file location

`snapshots/mauritius_snapshot.json`

This file should be committed back to the repository (or persisted to object storage) after each run so that subsequent runs have a valid baseline. The GitHub Actions workflow will re-use the snapshot across runs via the checked-out repository state.

---

## 11. How to Run Locally

### Prerequisites

- Python 3.12+
- A Supabase project (free tier is sufficient for development)
- A UK Companies House API key ([register here](https://developer.company-information.service.gov.uk/))
- Playwright Chromium installed

### Setup

```bash
# Clone the repository
git clone https://github.com/ismaelloveexcel/ARIE-global-incorporations-tracker.git
cd ARIE-global-incorporations-tracker

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium

# Configure environment
cp .env.example .env
# Edit .env and fill in:
#   SUPABASE_URL
#   SUPABASE_SERVICE_ROLE_KEY
#   COMPANIES_HOUSE_API_KEY
```

### Apply the database schema

Run `db/schema.sql` against your Supabase project via the SQL editor or psql:

```bash
psql "$SUPABASE_DATABASE_URL" -f db/schema.sql
```

Or paste the contents of `db/schema.sql` into the Supabase SQL editor and execute.

### Run the pipeline

```bash
# Process yesterday (default)
python main.py

# Process a specific date
python main.py --date 2026-05-13

# Process the last 7 days
python main.py --lookback 7

# Dry run (ingest + score, no DB writes)
python main.py --dry-run

# Skip the DIFC scraper
python main.py --skip-difc

# Skip the Mauritius scraper
python main.py --skip-mauritius

# Combine flags
python main.py --lookback 3 --skip-mauritius --dry-run
```

### Run the test suite

```bash
python -m pytest tests/ -v
```

### CSV output

After each pipeline run, a CSV file is written to `exports/YYYY-MM-DD.csv`. The filename matches the `date_to` parameter of the run.

---

## 12. GitHub Actions Automation

The pipeline runs automatically via `.github/workflows/daily_pipeline.yml`.

### Schedule

- **Automatic**: every day at **06:00 UTC** via cron
- **Manual**: trigger via `workflow_dispatch` from the GitHub Actions UI

### Manual dispatch inputs

| Input | Default | Description |
|---|---|---|
| `date` | _(blank)_ | Specific date to process (YYYY-MM-DD). Overrides `lookback`. |
| `lookback` | `1` | Number of days back to fetch |
| `skip_difc` | `false` | Skip DIFC Playwright scraper |
| `skip_mauritius` | `false` | Skip Mauritius Playwright scraper |
| `dry_run` | `false` | Parse and score only — no DB writes |

### Required secrets

Configure these in **Settings → Secrets and variables → Actions**:

| Secret | Description |
|---|---|
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key (not the anon key) |
| `COMPANIES_HOUSE_API_KEY` | UK Companies House API key |

### Artifact retention

CSV snapshots are uploaded as GitHub Actions artifacts with a **90-day retention window**. Each artifact is named `incorporation-snapshot-<run_id>` and contains all CSV files from the `exports/` directory.

---

## 13. Future Roadmap

### Phase 2 — Jurisdiction expansion

- British Virgin Islands (BVI) FSC register
- Cayman Islands CIMA register
- Jersey Financial Services Commission
- Singapore ACRA
- Hong Kong Companies Registry
- Luxembourg RCSL
- Delaware Division of Corporations

### Phase 3 — Entity graph enrichment

- Director and officer linking across jurisdictions
- Beneficial ownership extraction (where publicly available)
- Registered agent and registered address clustering
- Historical name change tracking

### Phase 4 — Compliance integration

- OpenSanctions database cross-reference
- OFAC SDN list matching
- EU consolidated sanctions screening
- UN Security Council list matching
- PEP (Politically Exposed Person) cross-reference

### Phase 5 — Intelligence API

- GraphQL API over the canonical entity graph
- Real-time webhook alerts for high-score new entities
- Bulk export to CRM systems (HubSpot, Salesforce)
- Enrichment pipeline integration (Clearbit, Companies House filings, etc.)

### Phase 6 — Relationship mapping

- Multi-hop entity graphs (company → director → company)
- Ownership chain visualisation
- Cross-jurisdiction group structure detection
- Common registered agent clustering

---

## Engineering principles

- **Auditability first**: all raw payloads are stored permanently in `raw_data JSONB`. Nothing is discarded.
- **Deterministic outputs**: the same input data always produces the same scores and canonical entity assignments.
- **Idempotent runs**: re-running the pipeline for the same date window is safe — it will not create duplicate records or canonical entities.
- **Connector isolation**: a failure in one jurisdiction's connector does not crash the pipeline. Errors are logged and processing continues.
- **No hidden business logic**: all scoring weights, deduplication thresholds, and suffix lists are declared as module-level constants that can be audited and adjusted without touching core logic.
- **Typed Python throughout**: all public functions use type hints for IDE support and static analysis.

---

*Built for the ARIE intelligence platform.*
