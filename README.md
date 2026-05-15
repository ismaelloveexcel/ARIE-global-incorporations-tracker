# Arie Incorporation Monitor

Internal onboarding intelligence dashboard for **Arie Finance** — verified UK incorporations from the official Companies House API, scored and ready for outreach assignment.

## Monday stakeholder demo

### 1. Setup

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set `COMPANIES_HOUSE_API_KEY` ([register free](https://developer.company-information.service.gov.uk/)).

### 2. Pre-load data (optional)

```bash
python run_uk_daily.py --date 2026-05-14 --demo
```

### 3. Start the app

```bash
python -m app.main
```

Open **http://127.0.0.1:8080**

### Demo talking points

- Every company is from the **official Companies House API** — click **Verify** to open the government register.
- **Metrics** at the top: totals, high priority, fintech/payments, assigned count, last refresh time.
- **Scoring** prioritises financial SIC codes and fintech-style names.
- **Lead type** (direct vs introducer) uses transparent name-based rules — hover the subtitle under each company.
- **Assign** leads to Aisha, Stephen, Rajesh, Tasneem, or Ismael — saved on server + browser backup.
- **Mauritius** and other jurisdictions show as roadmap items until official API access is in place.

### App features

| Feature | Description |
|---------|-------------|
| Dashboard metrics | Total, high priority, fintech/payments, assigned, last refreshed |
| Full lead table | Score, priority, SIC, lead type, website guess, contact placeholders |
| Verify links | Companies House profile for every row |
| Filters | Search, min score, priority, lead type, assigned to |
| Sortable columns | Click column headers |
| Refresh | Live API pull with loading indicator |

### What we deliberately did not include (yet)

- Supabase, deduplication, Playwright scrapers
- Fake emails or AI-invented companies
- Mauritius / DIFC automation until trustworthy access exists

## CSV export (backup)

```bash
python run_uk_daily.py --date 2026-05-14 --demo
```

## Tests

```bash
python -m pytest tests/ -v
```

## Legacy pipeline

`main.py` (multi-jurisdiction + Supabase) remains in the repo but is **not** part of the demo path.
