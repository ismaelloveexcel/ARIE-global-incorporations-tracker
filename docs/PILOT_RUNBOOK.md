# Pilot runbook — Corporate Leads Intelligence

For relationship managers and operations staff using the **prepared snapshot queue**.

This tool shows newly incorporated companies from official registries. It does **not** send emails, track CRM stages, or replace your outreach systems.

---

## 1. Morning workflow

1. Open the queue in your browser (your operations team will give you the link — usually `http://127.0.0.1:8080` on the office server).
2. Confirm the **snapshot date** in the header matches the business day you are reviewing (typically **yesterday’s incorporations**).
3. Glance at the top summary: total leads, UK / Mauritius counts, high-priority count.
4. If you see an **amber stale warning**, treat the list as “review carefully before outreach” — the file may be older than expected.
5. Work **high-priority leads first**, or use **Review lead queue** to focus the table.
6. Open a company row for detail, verify on the official registry, assign ownership if needed, add notes.
7. Export the current view if you need a spreadsheet for your own tracking.

---

## 2. How to open the queue

- Use the link from operations — always through the **app server**, not by opening an HTML file from disk.
- You should see **Corporate Leads Intelligence** and a date picker in the header.
- In production you will see a **PRODUCTION** badge. That means the app only uses **prepared overnight files**, not live registry pulls.

---

## 3. How to switch snapshot dates

- Use the **date menu** in the header (with ◀ ▶ arrows for previous / next prepared snapshot).
- Each date is a **fixed snapshot** prepared by the overnight pipeline.
- If a date is missing from the list, that snapshot was not produced — see section 10.

---

## 4. What stale warnings mean

An amber banner such as **“Snapshot may be stale”** means the prepared file for that date is **older than the usual freshness window** (about 36 hours).

**What to do**

- You may still review leads, but **confirm key facts on the official registry** before contacting anyone.
- If the date should be fresh, contact operations — the overnight job may have been delayed.

This is a caution, not a system error.

---

## 5. What “Registry verified” means

Information marked **Registry verified** comes from the **official public register** (UK Companies House or Mauritius MNS), or the **Verify** link opens that source.

Use it for: company name, incorporation date, registry identifiers, and official profile links.

It does **not** mean Arie has validated the company as a client or that contact details exist.

---

## 6. What “Internal heuristic” means

**Internal heuristic** is Arie’s **rule-based prioritisation score** (0–100) and related signals. It helps you **order your review**, not prove commercial fit.

Examples of what affects the score: jurisdiction, entity type, industry codes (UK), name patterns.

Scores are **recomputed when the snapshot loads** — they are not live market data.

---

## 7. What “AI-generated” means

**AI-generated** applies only to the optional **brief** in the detail panel (if enabled).

- It is **draft assistance**, not approved outreach copy.
- It can be wrong or incomplete.
- **Always confirm facts on the official registry** before any client contact.

If no brief appears, that is normal — the tool works fully without it.

---

## 8. Manual assignment usage

- In the table, the **Assigned** column shows **Assign** or **Assigned** only (lightweight control).
- Click it to choose a relationship manager. Changes **save immediately**.
- To see or change the **full name**, open the company **detail panel** (click the row).
- Assignment is for **internal ownership tracking** only — not client allocation in CRM.

There is **no automatic distribution** of leads.

---

## 9. Export workflow

1. Apply any filters you need (search, jurisdiction, view mode).
2. Click **Export current view**.
3. You receive a CSV of **exactly what is on screen** (filtered and sorted).
4. Use it in your own spreadsheet or import process — the tool does not sync to CRM.

Exported files include snapshot date, scores, assignment, notes, and registry links where available. Empty fields are left blank (no placeholder text).

---

## 10. What to do if no snapshot exists

**Message: “No prepared snapshots available”**

The overnight pipeline has not produced a file for review yet.

**What to do**

- Try another date in the header.
- If you expected yesterday’s queue, **contact operations** — do not assume the tool can pull live registry data in production.

**Quiet day**

The snapshot exists but has **no direct-client leads** for that date. That can be normal.

---

## 11. What NOT to assume from this tool

| Do not assume | Reality |
|---------------|---------|
| Emails or phone numbers are shown | Contact fields are **not invented** — often empty until separately sourced |
| High score = approved prospect | Score is **prioritisation only** |
| AI brief is accurate | **Verify on the registry** |
| Introducers tab is active | It is a secondary relationship-intelligence channel and may include overlap with onboarding entities |
| The app refreshes registries live in production | Production uses **prepared snapshots only** |
| Assignment updates CRM | Saves **only inside this tool** (`assignments` file) |
| Every Mauritius company has directors listed | Mauritius director data may show **not available from registry** until MNS access is expanded |

---

## Quick reference — provenance labels

| Label | Meaning |
|-------|---------|
| Registry verified | From official register or verify link |
| Internal heuristic | Rule-based score / signals |
| AI-generated | Optional brief text |
| Not available from registry | Register does not supply this field |

---

## Need help?

Contact your **operations / engineering** contact for: missing dates, stale snapshots, access issues, or export problems.

Technical setup (pipelines, servers, keys) is documented in the repository **README.md** — not required for daily RM use.
