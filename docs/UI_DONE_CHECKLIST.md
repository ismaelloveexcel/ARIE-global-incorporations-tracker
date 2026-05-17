# UI done checklist

Use this before marking the Incorporation Monitor front end complete or requesting an external HTML/UX review. The live app is served from `app/static/`; do not treat chat-pasted HTML as source of truth.

## 1. Markup validity

- [ ] `app/static/index.html` uses only valid HTML elements (no custom tag names such as `motion`).
- [ ] Every opening tag has a matching closing tag; run through [validator.w3.org](https://validator.w3.org/) or IDE HTML validation on `index.html`.
- [ ] Table `colspan` matches column count (currently **10**; keep in sync with `TABLE_COLSPAN` in `app.js`).

## 2. View mode (single source of truth)

- [ ] All filtering reads from `filterState` in `app.js` (`viewMode`: pursue | strong | all).
- [ ] View-mode buttons, search, and **Review pursue-now leads** update the same `filterState`.
- [ ] Default on load is **High priority** (pursue, score ≥ 70).
- [ ] Score thresholds come from `SCORE_TIERS` in `app.js`.

Manual smoke test:

1. Load app → **High priority** view active, pursue-now leads shown.
2. Switch to **Strong** → score band widens; hero hint updates.
3. **Review pursue-now leads** → returns to High priority view.

## 3. Accessibility

- [ ] Filters wrapped in `<form id="filtersForm">`; submit does not reload the page.
- [ ] Table has `<caption class="visually-hidden">`.
- [ ] Column headers use `scope="col"`.
- [ ] Lead rows are keyboard-openable (`role="button"`, `tabindex="0"`, Enter/Space).
- [ ] Detail panel: `role="dialog"`, `aria-modal="true"`, close on Escape.
- [ ] Loading overlay: `role="status"`, `aria-busy` toggled while loading.
- [ ] `aria-live` only on true status regions (banner, toast) — not on stats that refresh every filter change.

## 4. Empty and loading states

- [ ] No snapshot data → full empty state with pipeline hint (`showTableEmptyState`).
- [ ] Data loaded but filters hide everything → inline empty state + reset (`showFilteredEmptyState`).
- [ ] Loading row replaced after first successful fetch.

## 5. Export and hero metrics

- [ ] Export button label shows filtered count: `Export CSV (n)`.
- [ ] Export toast says “filtered leads”; exports current filter view only.
- [ ] Hero stat cards update when filters change (tier counts from filtered rows).

## 6. Automated checks

```bash
python -m pytest -q
```

- [ ] All tests pass on the branch before push.

## 7. Review artifacts

- [ ] For external HTML review, use `docs/review/index-revised.html` (annotated copy of production markup).
- [ ] Production file remains `app/static/index.html` (linked CSS/JS under `/static/`).

## Product rules (unchanged)

- No invented contacts, emails, or LinkedIn URLs.
- UK/Mauritius verify links point to official registries only.
- Single auto queue (direct clients); introducers tracked outside the app.
- No in-app CRM workflow (follow-up dates, won/lost pipelines) unless explicitly re-scoped.
