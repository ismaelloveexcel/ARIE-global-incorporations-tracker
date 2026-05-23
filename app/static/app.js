const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const PANEL_STATUSES = ["High Relevance", "Monitor", "Introducer Opportunity", "Not Relevant"];
const MU_DIRECTOR_MSG =
  "Director and PSC data is not yet available for Mauritius companies. This will be added when MNS API access is confirmed.";

let team = [];
let assignmentPools = {};
let allLeads = [];
const DEFAULT_QUEUE_TAB = "direct_clients";
let sortKey = "score";
let sortDir = "desc";
let lastPayload = null;
let hasOpenaiKey = false;
let hasCompaniesHouseKey = false;
let canFetchUk = false;
let canFetchMauritius = false;
let snapshotDates = [];
let availableDates = [];
let calendarDates = [];
let dateDetails = [];
let currentDate = "";
let activeDateMessage = "";
let openLeadId = null;
let detailLead = null;
let bannerHideTimer = null;
let isProductionMode = false;
let modeVariant = "development";
let operatorRefreshAllowed = true;
let lastDataStatus = null;
let detailReturnFocus = null;
let activeQueueView = "direct_clients";
let uiViewMode = "technical";
const TABLE_COLSPAN = 5;
const SCORE_TIERS = { high: 70, strong: 40, monitor: 0 };
const DEFAULT_ASSIGNEES = ["Aisha", "Ismael", "Rajesh", "Stephen", "Tasneem"];
const ADD_ASSIGNEE_VALUE = "__add_name__";
const customAssignees = new Set();

const VIEW_MODES = {
  strong: { minScore: SCORE_TIERS.strong, label: "High Relevance" },
  all: { minScore: 0, label: "Candidate Entities" },
};

function createDefaultFilterState() {
  return {
    search: "",
    viewMode: "all",
    minScore: 0,
    priority: "",
    assigned: "",
    jurisdiction: "",
    sortKey: "score",
    sortDir: "desc",
  };
}

let filterState = createDefaultFilterState();
let appHasDates = false;
let datesApiOk = true;

const UI_STATE_KEYS = {
  queueTab: "arie.queueTab",
  date: "arie.currentDate",
  windowScrollY: "arie.windowScrollY",
  tableScrollTop: "arie.tableScrollTop",
};

function safeSessionGet(key) {
  try {
    return window.sessionStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

function safeSessionSet(key, value) {
  try {
    window.sessionStorage.setItem(key, String(value ?? ""));
  } catch {
    // Ignore storage failures in restricted environments.
  }
}

function persistOperationalUiState() {
  safeSessionSet(UI_STATE_KEYS.queueTab, activeQueueView || DEFAULT_QUEUE_TAB);
  if (currentDate) safeSessionSet(UI_STATE_KEYS.date, currentDate);
}

function restorePersistedQueueTab() {
  const value = safeSessionGet(UI_STATE_KEYS.queueTab);
  return value === "introducers" ? "introducers" : DEFAULT_QUEUE_TAB;
}

function restorePersistedDate() {
  const fromUrl = requestedDateFromUrl();
  if (fromUrl) return "";
  const saved = safeSessionGet(UI_STATE_KEYS.date);
  return isIsoDateString(saved) ? saved : "";
}

function persistScrollState() {
  const tableWrap = document.querySelector(".table-wrap");
  safeSessionSet(UI_STATE_KEYS.windowScrollY, Math.max(0, Math.round(window.scrollY || 0)));
  safeSessionSet(UI_STATE_KEYS.tableScrollTop, Math.max(0, Math.round(tableWrap?.scrollTop || 0)));
}

function restoreScrollState() {
  const windowY = Number(safeSessionGet(UI_STATE_KEYS.windowScrollY));
  const tableTop = Number(safeSessionGet(UI_STATE_KEYS.tableScrollTop));
  if (!Number.isNaN(windowY) && windowY > 0) {
    window.scrollTo({ top: windowY, behavior: "auto" });
  }
  const tableWrap = document.querySelector(".table-wrap");
  if (tableWrap && !Number.isNaN(tableTop) && tableTop > 0) {
    tableWrap.scrollTop = tableTop;
  }
}

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function isIsoDateString(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(value || "").trim());
}

function requestedDateFromUrl() {
  try {
    const params = new URLSearchParams(window.location.search);
    const value = params.get("date") || "";
    return isIsoDateString(value) ? value : "";
  } catch {
    return "";
  }
}

function syncUrlDateParam(date) {
  try {
    const url = new URL(window.location.href);
    if (date) url.searchParams.set("date", date);
    else url.searchParams.delete("date");
    window.history.replaceState({}, "", url);
  } catch {
    // Ignore URL sync failures in restricted environments.
  }
}

function nearestAvailableDateFromList(dates, targetDate) {
  if (!targetDate || !dates.length) return "";
  if (dates.includes(targetDate)) return targetDate;
  for (const d of dates) {
    if (d < targetDate) return d;
  }
  return dates[dates.length - 1] || "";
}

function resolveBootstrapDate(recommended, requestedDate) {
  if (requestedDate && availableDates.includes(requestedDate)) {
    return { date: requestedDate, message: "" };
  }

  const fallbackDate =
    nearestAvailableDateFromList(availableDates, requestedDate) ||
    recommended ||
    availableDates[0] ||
    "";

  if (requestedDate && fallbackDate && fallbackDate !== requestedDate) {
    return {
      date: fallbackDate,
      message: `Displaying latest validated operational intelligence from ${formatDisplayDate(fallbackDate)}.`,
    };
  }

  if (!requestedDate && fallbackDate) {
    return {
      date: fallbackDate,
      message: "Latest validated operational intelligence loaded.",
    };
  }

  return { date: fallbackDate, message: "" };
}

function pipelineCommandToday() {
  return `python main.py --date ${todayISO()} --skip-difc`;
}

const PROVENANCE_LABELS = {
  registry: "Registry Verified",
  heuristic: "Heuristic Signal",
  ai: "AI-Assisted Classification",
  unavailable: "No Data Available",
};

function provenanceLabel(kind) {
  const text = PROVENANCE_LABELS[kind] || kind;
  return `<span class="provenance-label provenance-label--${kind}">${escapeHtml(text)}</span>`;
}

function renderProvenancePanel() {
  const panel = $("#provenancePanelItems");
  if (!panel) return;
  panel.innerHTML = `
    ${provenanceLabel("registry")}
    ${provenanceLabel("heuristic")}
    ${provenanceLabel("ai")}
    ${provenanceLabel("unavailable")}
  `;
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

function operatorSafeErrorMessage(raw) {
  const msg = String(raw || "").trim();
  if (!msg) return "Unable to load operational intelligence. Contact operations if this continues.";
  if (msg.length > 160 || /traceback|exception|errno|syntaxerror|typeerror/i.test(msg)) {
    return "Unable to load operational intelligence. Contact operations if this continues.";
  }
  return msg;
}

function showToast(msg, isError = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.hidden = false;
  el.classList.toggle("error", isError);
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => {
    el.hidden = true;
  }, 4000);
}

function setLoading(on, text) {
  const overlay = $("#loadingOverlay");
  if (overlay) {
    overlay.hidden = !on;
    overlay.setAttribute("aria-busy", on ? "true" : "false");
  }
  const refreshBtn = $("#refreshBtn");
  if (refreshBtn) refreshBtn.disabled = on;
  if (text) $("#loadingText").textContent = text;
}

function syncSortGlobalsFromFilterState() {
  sortKey = filterState.sortKey;
  sortDir = filterState.sortDir;
}

function applyFilterStateToDom() {
  const search = $("#filterSearch");
  if (search) search.value = filterState.search;
  const jurisdictionSel = $("#jurisdictionFilter");
  if (jurisdictionSel) jurisdictionSel.value = filterState.jurisdiction || "";
  const mode = VIEW_MODES[filterState.viewMode] || VIEW_MODES.all;
  filterState.minScore = mode.minScore;
  syncViewModeButtons();
  syncSortGlobalsFromFilterState();
  updateSortHeaders();
}

function readFilterStateFromDom() {
  filterState.search = ($("#filterSearch")?.value || "").trim();
  filterState.jurisdiction = $("#jurisdictionFilter")?.value || "";
  const active = document.querySelector(".view-mode__btn.active");
  if (active?.dataset.view && VIEW_MODES[active.dataset.view]) {
    filterState.viewMode = active.dataset.view;
    filterState.minScore = VIEW_MODES[filterState.viewMode].minScore;
  }
  syncSortGlobalsFromFilterState();
}

function commitFilterState() {
  applyFilterStateToDom();
  syncViewModeButtons();
  updateExportButtonLabel();
  updateTabGuidance();
  renderExecutiveQuickBar();
  renderTable();
  renderIntroducersView();
  renderQueueFromFiltered();
  updateHeroMetaLine();
  if (lastDataStatus) renderTrustStrip(lastDataStatus);
}

function applyUiViewModeToDom() {
  const body = document.body;
  if (!body) return;
  uiViewMode = "technical";
  body.classList.remove("ui-view-executive", "ui-view-technical");
  body.classList.add("ui-view-technical");
  document.querySelectorAll(".ui-mode-switch__btn[data-mode]").forEach((btn) => {
    const on = btn.dataset.mode === "technical";
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

function setUiViewMode(mode) {
  if (mode !== "executive" && mode !== "technical") return;
  uiViewMode = mode;
  applyUiViewModeToDom();
  renderTable();
  renderIntroducersView();
  updateTabGuidance();
  if (lastDataStatus) renderTrustStrip(lastDataStatus);
}

function setFilterState(partial) {
  filterState = { ...filterState, ...partial };
  commitFilterState();
}

function applyScoreTierLabels() {
  const heroBtn = $("#reviewHighPriorityBtn");
  if (heroBtn) heroBtn.textContent = "Open Priority Queue";
  const heroEyebrow = $("#queueHeroEyebrow");
  if (heroEyebrow) heroEyebrow.textContent = "Onboarding Pipeline";
  document.querySelectorAll(".view-mode__btn[data-view]").forEach((btn) => {
    const mode = VIEW_MODES[btn.dataset.view];
    if (mode) btn.textContent = mode.label;
  });
}

function syncViewModeButtons() {
  document.querySelectorAll(".view-mode__btn[data-view]").forEach((btn) => {
    const on = btn.dataset.view === filterState.viewMode;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

function applyViewMode(viewMode) {
  if (!VIEW_MODES[viewMode]) return;
  filterState.viewMode = viewMode;
  filterState.minScore = VIEW_MODES[viewMode].minScore;
  filterState.priority = "";
  commitFilterState();
}

function formatRefreshedShort(iso) {
  if (!iso) return "Sorted by opportunity score";
  try {
    const d = new Date(iso);
    const mins = Math.floor((Date.now() - d.getTime()) / 60000);
    if (mins < 1) return "Updated just now";
    if (mins < 60) return `Updated ${mins} min ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `Updated ${hrs} hr ago`;
    return formatRefreshed(iso);
  } catch {
    return "Sorted by opportunity score";
  }
}

function jurisdictionScopeSlug() {
  const j = filterState.jurisdiction;
  if (j === "UK") return "uk";
  if (j === "Mauritius") return "mu";
  return "";
}

function exportScopeSlug() {
  const mode = filterState.viewMode;
  const j = jurisdictionScopeSlug();
  let base = "all";
  if (mode === "strong") base = "strong";
  return j ? `${base}_${j}` : base;
}

function exportScopeLabel() {
  const mode = filterState.viewMode;
  let scope = "all";
  if (mode === "strong") scope = "evaluate-soon";
  const j = filterState.jurisdiction;
  if (j === "UK") return `${scope} · UK`;
  if (j === "Mauritius") return `${scope} · Mauritius`;
  return scope;
}

function updateExportButtonLabel() {
  const btn = $("#exportBtn");
  if (!btn) return;
  const n = queueScopedLeads(getFilteredLeads()).length;
  const scope = exportScopeLabel();
  btn.textContent = n
    ? `Export current view (${n} ${scope})`
    : "Export current view";
  btn.title = n
    ? `Download ${n} ${scope} leads as CSV (current filters and sort order)`
    : "Download the leads currently shown (filters and sort applied)";
  btn.disabled = !n && allLeads.length > 0;
}

function formatRefreshed(iso) {
  if (!iso) return "Register data not refreshed this session";
  try {
    const d = new Date(iso);
    return `Last refreshed ${d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`;
  } catch {
    return `Last refreshed ${iso}`;
  }
}

function scrollToLeadQueue() {
  const n = queueScopedLeads(getFilteredLeads()).length;
  if (!n) showToast("No candidates available for this operational date", true);
  document.querySelector(".table-wrap")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function formatDisplayDate(iso) {
  try {
    return new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

function formatDisplayDateShort(iso) {
  try {
    return new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

function countPriorityBuckets(rows) {
  let high = 0;
  let evaluate = 0;
  let monitor = 0;
  for (const r of rows) {
    const score = Number(r.score) || 0;
    if (score >= SCORE_TIERS.high) high += 1;
    else if (score >= SCORE_TIERS.strong) evaluate += 1;
    else monitor += 1;
  }
  return { high, evaluate, monitor, total: rows.length };
}

function buildConicGradient(segments) {
  const total = segments.reduce((sum, seg) => sum + seg.value, 0);
  if (!total) return "conic-gradient(#e8ecf3 0deg 360deg)";
  let acc = 0;
  const parts = [];
  for (const seg of segments) {
    if (!seg.value) continue;
    const start = (acc / total) * 360;
    acc += seg.value;
    const end = (acc / total) * 360;
    parts.push(`${seg.color} ${start}deg ${end}deg`);
  }
  return `conic-gradient(${parts.join(", ")})`;
}

function renderChartCard(title, segments, ariaSummary) {
  const total = segments.reduce((sum, seg) => sum + seg.value, 0);
  const gradient = buildConicGradient(segments);
  const legend = segments
    .map((seg) => {
      const pct = total ? Math.round((seg.value / total) * 100) : 0;
      return `<li class="hero-chart-legend__item">
        <span class="hero-chart-legend__swatch" style="background:${seg.color}"></span>
        <span class="hero-chart-legend__label">${escapeHtml(seg.label)}</span>
        <span class="hero-chart-legend__count">${seg.value}</span>
        <span class="hero-chart-legend__pct">${pct}%</span>
      </li>`;
    })
    .join("");
  return `
    <article class="hero-chart-card">
      <h3 class="hero-chart-card__title">${escapeHtml(title)}</h3>
      <div class="hero-chart-card__body">
        <div class="hero-donut" style="background:${gradient}" role="img" aria-label="${escapeHtml(ariaSummary || title)}">
          <span class="hero-donut__center">${total}</span>
        </div>
        <ul class="hero-chart-legend">${legend}</ul>
      </div>
    </article>`;
}

function renderQueueSummaryMetrics(statsEl, metrics) {
  if (!statsEl) return;
  const m = metrics || {};
  const total = Number(m.total_leads) || 0;
  if (!total && !allLeads.length) {
    statsEl.innerHTML =
      '<p class="queue-summary__empty muted">Latest validated operational intelligence will appear here automatically.</p>';
    return;
  }
  const uk = Number(m.uk_count) || 0;
  const mu = Number(m.mauritius_count) || 0;
  const high = Number(m.high_priority) || 0;
  statsEl.innerHTML = `
    <p class="queue-summary__caption muted">Morning briefing posture</p>
    <div class="queue-summary" role="group" aria-label="Queue summary for this snapshot">
      <div class="queue-summary__item">
        <span class="queue-summary__value">${total}</span>
        <span class="queue-summary__label">Entities</span>
      </div>
      <div class="queue-summary__item">
        <span class="queue-summary__value">${uk}</span>
        <span class="queue-summary__label">United Kingdom</span>
      </div>
      <div class="queue-summary__item">
        <span class="queue-summary__value">${mu}</span>
        <span class="queue-summary__label">Mauritius</span>
      </div>
      <div class="queue-summary__item queue-summary__item--highlight">
        <span class="queue-summary__value">${high}</span>
        <span class="queue-summary__label">High Relevance</span>
      </div>
    </div>`;
}

function renderExecutiveQuickBar() {
  const el = $("#executiveQuickBar");
  if (!el) return;

  const rows = queueScopedLeads(getFilteredLeads());
  const ranked = [...rows].sort((a, b) => (Number(b.score) || 0) - (Number(a.score) || 0));
  const topLead = ranked[0] || null;
  const scopeLabel = activeQueueView === "introducers" ? "Introducer Review" : "Onboarding Review";
  const total = rows.length;
  const high = rows.filter((l) => (Number(l.score) || 0) >= SCORE_TIERS.high).length;
  const assigned = rows.filter((l) => (l.assigned_to || "").trim()).length;
  const ukCount = rows.filter((l) => (l.jurisdiction || "") === "UK").length;
  const muCount = rows.filter((l) => (l.jurisdiction || "") === "Mauritius").length;
  const concentration = ukCount >= muCount ? `Primary coverage: UK (${ukCount}/${total || 1})` : `Primary coverage: Mauritius (${muCount}/${total || 1})`;
  const topName = topLead ? displayCompanyName(topLead.company_name || "Top candidate") : "No candidate selected";
  const urgencyLine = high ? `${high} high-relevance entities require close review` : "No immediate high-relevance escalation at this time";
  let nextMove = "Wait for the next published snapshot";
  if (topLead) {
    nextMove = (topLead.assigned_to || "").trim()
      ? `Advance ${topName} into onboarding diligence`
      : `Assign ${topName} for first-pass review`;
  }
  const statusType = lastDataStatus?.banner?.type || "green";
  const statusLabel =
    statusType === "red"
      ? "Issue"
      : statusType === "amber"
        ? "Check"
        : "Healthy";

  el.innerHTML = `
    <article class="executive-quick-bar__item executive-quick-bar__item--decision">
      <p class="executive-quick-bar__label">Decision Focus</p>
      <p class="executive-quick-bar__value executive-quick-bar__value--text">${escapeHtml(topName)}</p>
      <p class="executive-quick-bar__meta">${escapeHtml(urgencyLine)} · ${escapeHtml(nextMove)} · ${escapeHtml(concentration)}</p>
    </article>
    <article class="executive-quick-bar__item">
      <p class="executive-quick-bar__label">Ready in ${scopeLabel}</p>
      <p class="executive-quick-bar__value">${total}</p>
    </article>
    <article class="executive-quick-bar__item executive-quick-bar__item--highlight">
      <p class="executive-quick-bar__label">Immediate</p>
      <p class="executive-quick-bar__value">${high}</p>
    </article>
    <article class="executive-quick-bar__item">
      <p class="executive-quick-bar__label">In Review</p>
      <p class="executive-quick-bar__value">${assigned}</p>
    </article>
    <article class="executive-quick-bar__item">
      <p class="executive-quick-bar__label">Confidence</p>
      <p class="executive-quick-bar__value executive-quick-bar__status executive-quick-bar__status--${statusType}">${statusLabel}</p>
    </article>`;
}

function updateHeroMetaLine() {
  const metaEl = $("#queueHeroMeta");
  if (!metaEl) return;
  const scopeLabel = activeQueueView === "introducers" ? "Introducer Lens" : "Onboarding Lens";
  const total = queueScopedLeads(allLeads).length;
  if (!total) {
    metaEl.hidden = true;
    metaEl.textContent = "";
    return;
  }
  const visible = queueScopedLeads(getFilteredLeads()).length;
  const mode = VIEW_MODES[filterState.viewMode]?.label || "View";
  const shortMode = mode === "Candidate Entities" ? "Candidates" : mode;
  if (visible === total) {
    metaEl.textContent = `${scopeLabel} · ${total} entities · ${shortMode}`;
  } else {
    metaEl.textContent = `${scopeLabel} · ${visible} of ${total} · ${shortMode}`;
  }
  metaEl.hidden = false;
}

function updateTablePanelSubtitle() {
  const total = queueScopedLeads(allLeads).length;
  if (!total) {
    setPanelSubtitle("");
    return;
  }
  const visible = queueScopedLeads(getFilteredLeads()).length;
  const dateLabel = formatDisplayDateShort(getCurrentDate());
  const wrap = document.querySelector(".table-wrap");
  const scrollMore =
    wrap?.classList.contains("is-scrollable-y") && visible > 0 ? " · Scroll for more" : "";
  if (visible === total) {
    setPanelSubtitle(`${total} entities · ${dateLabel}${scrollMore}`);
  } else {
    setPanelSubtitle(`${visible} of ${total} entities · ${dateLabel}${scrollMore}`);
  }
}

function getCurrentDate() {
  return $("#dateSelect")?.value || currentDate;
}

function isMauritiusLead(lead) {
  const source = (lead?.source || "").toLowerCase();
  return source === "mauritius_mns" || (lead?.jurisdiction || "").trim() === "Mauritius";
}

function isIntroducerLead(lead) {
  return leadHasQueueTab(lead, "introducers");
}

function leadHasQueueTab(lead, tab) {
  const tabs = Array.isArray(lead?.dashboard_tabs)
    ? lead.dashboard_tabs.map((t) => String(t || "").trim().toLowerCase()).filter(Boolean)
    : [];
  const normalized = String(tab || "").trim().toLowerCase();
  if (tabs.length) return tabs.includes(normalized);
  if (normalized === "introducers") return (lead?.lead_type || "").toLowerCase() === "introducer";
  if (normalized === "direct_clients") return (lead?.lead_type || "").toLowerCase() !== "introducer";
  return false;
}

function queueScopedLeads(rows = [], queueView = activeQueueView) {
  return rows.filter((lead) => leadHasQueueTab(lead, queueView));
}

function introducerCategoryFromName(name) {
  const text = (name || "").toLowerCase();
  if (/management\s+company|management/i.test(text)) return "Management Company";
  if (/fiduciary|trust|trustee|nominee/i.test(text)) return "Fiduciary";
  if (/corporate\s+services|secretarial|administration|csp/i.test(text)) return "CSP";
  if (/legal|solicitor|law|attorney|advisory|advisor|adviser/i.test(text)) {
    return "Legal / Advisory";
  }
  return "Legal / Advisory";
}

function leadKey(lead) {
  return lead?.lead_id || lead?.company_number || "";
}

function applyOperationalMode(meta) {
  isProductionMode = !!meta?.is_production;
  operatorRefreshAllowed = meta?.operator_refresh_allowed !== false;
  const modeLabel = String(meta?.mode_label || "").trim();
  modeVariant = String(meta?.mode_variant || "").trim() || "development";

  const devLink = $("#devOpsLink");
  if (devLink) devLink.hidden = meta?.show_dev_link === false || modeVariant === "demo";

  const refreshBtn = $("#refreshBtn");
  if (refreshBtn) {
    refreshBtn.hidden = !operatorRefreshAllowed;
    refreshBtn.disabled = !operatorRefreshAllowed;
    refreshBtn.title = operatorRefreshAllowed
      ? "Engineering: load UK operational data into exports/ (dev only)"
      : "Operational data is prepared overnight — contact operations if a date is missing";
  }

  const badge = $("#envBadge");
  if (badge && meta?.is_production !== undefined) {
    badge.textContent = modeLabel || (meta.is_production ? "PRODUCTION" : "DEV MODE");
    badge.classList.toggle("env-badge--live", !!meta.is_production);
    badge.classList.toggle("env-badge--demo", modeVariant === "demo");
    badge.classList.toggle("env-badge--hybrid", modeVariant === "hybrid");
    badge.classList.toggle("env-badge--dev", !meta.is_production && modeVariant !== "demo" && modeVariant !== "hybrid");
  }
}

async function loadMeta() {
  const res = await fetch("/api/meta");
  if (!res.ok) throw new Error("Could not reach the app server");
  const data = await res.json();
  team = data.team || [];
  assignmentPools = data.assignment_pools || {};
  hasOpenaiKey = !!data.has_openai_key;
  hasCompaniesHouseKey = !!data.has_api_key;
  applyOperationalMode(data);
  if (data.canonical_pipeline_queue !== true) {
    showToast(
      "This app server is out of date — stop it and run: python -m app.main",
      true
    );
  }
  const assignedFilter = $("#filterAssigned");
  if (assignedFilter) {
    team.forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      assignedFilter.appendChild(opt);
    });
  }
}

async function loadAvailableDates() {
  try {
    const res = await fetch("/api/available-dates");
    datesApiOk = res.ok;
    if (!res.ok) {
      availableDates = [];
      calendarDates = [];
      dateDetails = [];
      appHasDates = false;
      syncSnapshotControls();
      updateDateNavButtons();
      return currentDate || "";
    }
    const data = await res.json();
    availableDates = data.dates || [];
    snapshotDates = data.snapshot_dates || [];
    calendarDates = data.calendar_dates || [];
    dateDetails = data.date_details || [];
    canFetchUk = !!data.can_fetch_uk;
    canFetchMauritius = !!data.can_fetch_mauritius;
    const recommended = data.recommended || availableDates[0] || "";
    const restoredDate = restorePersistedDate();
    const requestedDate = currentDate || requestedDateFromUrl() || restoredDate;
    const resolved = resolveBootstrapDate(recommended, requestedDate);
    if (resolved.date) currentDate = resolved.date;
    activeDateMessage = resolved.message || "";
    appHasDates = availableDates.length > 0;
    syncSnapshotControls();
    updateDateNavButtons();
    if (currentDate) {
      syncUrlDateParam(currentDate);
      persistOperationalUiState();
    }
    return appHasDates ? currentDate || recommended : currentDate || "";
  } catch {
    datesApiOk = false;
    availableDates = [];
    calendarDates = [];
    dateDetails = [];
    appHasDates = false;
    syncSnapshotControls();
    updateDateNavButtons();
    return currentDate || "";
  }
}

function dateDetail(date) {
  return (
    dateDetails.find((d) => d.date === date) || {
      date,
      uk_count: 0,
      mauritius_count: 0,
      has_data: false,
      has_snapshot: false,
      publication_timestamp: null,
      freshness_state: "unknown",
      confidence_level: "unknown",
      fallback_active: false,
      archive_available: false,
    }
  );
}

function upsertDateDetailFromPayload(data) {
  if (!data?.incorporation_date) return;
  const m = data.metrics || {};
  const uk = Number(m.uk_count) || 0;
  const mu = Number(m.mauritius_count) || 0;
  const entry = {
    date: data.incorporation_date,
    uk_count: uk,
    mauritius_count: mu,
    has_uk: uk > 0,
    has_mauritius: mu > 0,
    has_data: uk > 0 || mu > 0,
    has_snapshot: uk > 0 || mu > 0,
    mauritius_export_exists: mu > 0,
  };
  const idx = dateDetails.findIndex((d) => d.date === entry.date);
  if (idx >= 0) {
    dateDetails[idx] = { ...dateDetails[idx], ...entry };
  } else {
    dateDetails.push(entry);
  }
}

function refreshDateSelectLabels() {
  const sel = $("#dateSelect");
  if (!sel || sel.hidden) return;
  [...sel.options].forEach((opt) => {
    if (opt.value) opt.textContent = dateOptionLabel(opt.value);
  });
}

function dateHasLoadedQueue(date) {
  if (lastPayload?.incorporation_date !== date) return false;
  const m = lastPayload.metrics || {};
  const total =
    Number(lastPayload.count) ||
    (Number(m.uk_count) || 0) + (Number(m.mauritius_count) || 0);
  return total > 0;
}

function dateOptionLabel(d) {
  const label = formatDisplayDate(d);
  const detail = dateDetail(d);
  if (detail.has_data || dateHasLoadedQueue(d)) return label;
  if (detail.has_snapshot) return `${label} · quiet day`;
  return label;
}

function nearestAvailableDate(targetDate) {
  return nearestAvailableDateFromList(availableDates, targetDate);
}

function dateToneForTimeline(date, statusData) {
  const detail = dateDetail(date);
  const isCurrent = date === getCurrentDate();

  if (!detail.has_snapshot) return { key: "missing", label: "Missing" };
  if (!detail.has_data) return { key: "partial", label: "Quiet Day" };

  const detailState = String(detail.freshness_state || "").toLowerCase();
  if (!isCurrent) {
    if (detail.fallback_active) return { key: "stale", label: "Fallback" };
    if (detailState === "error") return { key: "critical", label: "Critical" };
    if (detailState === "stale") return { key: "stale", label: "Stale" };
    if (detailState === "partial") return { key: "partial", label: "Partial" };
    if (detail.archive_available) return { key: "healthy", label: "Archived" };
  }

  if (isCurrent) {
    const state = statusData?.freshness?.state || "unknown";
    if (state === "error") return { key: "critical", label: "Critical" };
    if (state === "stale") return { key: "stale", label: "Stale" };
    if (state === "partial") return { key: "partial", label: "Partial" };
    if (state === "healthy") return { key: "healthy", label: "Healthy" };
  }

  return { key: "healthy", label: "Published" };
}

function formatTimelineTimestamp(iso) {
  if (!iso) return "No publication time";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-GB", {
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "UTC",
      timeZoneName: "short",
    });
  } catch {
    return String(iso);
  }
}

function timelineDates() {
  const source = calendarDates.length ? calendarDates : availableDates;
  if (!source.length) return [];
  const baseline = getCurrentDate() || source[0];
  const idx = source.indexOf(baseline);
  if (idx < 0) return source.slice(0, 12);
  const end = Math.min(source.length, idx + 12);
  return source.slice(idx, end);
}

function renderDateHistory(statusData = null) {
  const timelineEl = $("#dateHistoryTimeline");
  const narrativeEl = $("#dateHistoryNarrative");
  if (!timelineEl || !narrativeEl) return;

  const current = getCurrentDate();
  const dates = timelineDates();

  if (!dates.length) {
    timelineEl.innerHTML = '<p class="date-history__empty">No recent timeline context is available in this environment yet.</p>';
    narrativeEl.textContent = "No recent briefing dates are currently available.";
    return;
  }

  let missingRun = 0;
  timelineEl.innerHTML = dates
    .map((d) => {
      const tone = dateToneForTimeline(d, statusData);
      const isCurrent = d === current;
      const isAvailable = availableDates.includes(d);
      const detail = dateDetail(d);
      if (!isCurrent && tone.key === "missing") missingRun += 1;
      else missingRun = 0;
      const quietHistory = !isCurrent && tone.key === "missing" && missingRun > 1;

      const confidence = `Confidence ${String(detail.confidence_level || "unknown").toUpperCase()}`;
      const archived = detail.archive_available ? "Archived lineage" : "Active lineage";
      const metaLine = isCurrent
        ? `${formatTimelineTimestamp(detail.publication_timestamp)} · ${confidence}`
        : quietHistory
          ? ""
          : formatTimelineTimestamp(detail.publication_timestamp);
      const detailTitle = `${formatDisplayDate(d)} · ${tone.label} · ${metaLine} · ${archived}`;
      const chipLabel = quietHistory ? "Past" : tone.label;
      const chipMeta = metaLine ? `<small class="date-chip__meta">${escapeHtml(metaLine)}</small>` : "";
      const chipClass = `${tone.key}${isCurrent ? " is-current" : ""}${quietHistory ? " is-history" : ""}`;
      const action = isAvailable
        ? `<button type="button" class="date-chip date-chip--${chipClass}" data-date="${d}" title="${escapeHtml(detailTitle)}">${escapeHtml(formatDisplayDateShort(d))}<span>${chipLabel}</span>${chipMeta}</button>`
        : `<span class="date-chip date-chip--${tone.key} is-disabled${quietHistory ? " is-history" : ""}" title="${escapeHtml(detailTitle)}">${escapeHtml(formatDisplayDateShort(d))}<span>${chipLabel}</span>${chipMeta}</span>`;
      return action;
    })
    .join("");

  timelineEl.querySelectorAll("button[data-date]").forEach((btn) => {
    btn.addEventListener("click", () => setSelectedDate(btn.dataset.date));
  });

  const detail = dateDetail(current);
  const nearest = nearestAvailableDate(current);
  if (!current) {
    narrativeEl.textContent = "Select an operational date to anchor this briefing.";
  } else if (!detail.has_snapshot && nearest && nearest !== current) {
    narrativeEl.textContent = `No operational dataset is available for ${formatDisplayDate(current)}. The nearest available date is ${formatDisplayDate(nearest)}.`;
  } else if (statusData?.freshness?.state === "stale") {
    narrativeEl.textContent = `You are viewing ${formatDisplayDate(current)}. This operational dataset is stale, so continue with fallback-aware review before escalation.`;
  } else {
    narrativeEl.textContent = `You are viewing ${formatDisplayDate(current)}. Earlier dates remain available above for quiet context.`;
  }
}

function statusSeverity(statusData) {
  const state = statusData?.freshness?.state || "unknown";
  const conf = (statusData?.operational_confidence?.level || "").toLowerCase();
  const fallback = !!statusData?.operational_confidence?.fallback_active;

  if (state === "error") return { key: "critical", label: "Critical" };
  if (state === "stale" || state === "partial") return { key: "degraded", label: "Watch" };
  if (conf === "low") return { key: "degraded", label: "Watch" };
  if (fallback) return { key: "investigating", label: "Review" };
  return { key: "healthy", label: "Healthy" };
}

function renderTrustPanel(statusData) {
  const el = $("#trustPanelText");
  if (!el) return;
  const statement = statusData?.executive?.trust_statement ||
    "Operational intelligence validated.";
  const concise = (statement.split(". ")[0] || statement).replace("This platform only displays ", "");
  el.textContent = concise.endsWith(".") ? concise : `${concise}.`;
}

function renderExecutiveStatusCard(statusData) {
  const headlineEl = $("#opsSummaryHeadline");
  const bodyEl = $("#opsSummaryBody");
  if (!headlineEl || !bodyEl) return;

  if (!statusData) {
    headlineEl.className = "ops-summary__headline ops-summary__headline--investigating";
    headlineEl.textContent = "Briefing: Loading";
    bodyEl.innerHTML = "";
    return;
  }

  const severity = statusSeverity(statusData);
  const conf = statusData?.operational_confidence || {};
  const executive = statusData?.executive || {};
  const actionability = executive.incident_actionability || {};
  const delta = executive.delta_intelligence || {};
  const freshnessState = String(statusData?.freshness?.state || "unknown").toLowerCase();
  const ukUpdated = statusData?.uk?.file_modified || "";
  const muUpdated = statusData?.mauritius?.file_modified || "";
  const entityTotal = (statusData?.uk?.row_count || 0) + (statusData?.mauritius?.row_count || 0);
  const publishedAt = ukUpdated || muUpdated;
  const totalSources = Math.max((conf.verified_sources ?? 0) + (conf.failed_sources ?? 0), 1);
  const sourceCoverage = `${conf.verified_sources ?? 0}/${totalSources} sources confirmed`;
  const narrativeRaw = executive.narrative_sentence || "Opportunity narrative is loading.";
  const narrative = narrativeRaw.split(". ")[0] || narrativeRaw;
  const deltaLine = delta?.available && Array.isArray(delta.highlights) && delta.highlights.length
    ? delta.highlights[0]
    : "Change intelligence will appear after the next operational comparison point.";
  const recommendation = actionability.recommended_next_step || "Continue standard review cadence.";
  const incidentDetail = [
    actionability.what_happened,
    actionability.user_impact,
    actionability.fallback,
  ]
    .filter(Boolean)
    .join(" ");

  headlineEl.className = `ops-summary__headline ops-summary__headline--${severity.key}`;
  headlineEl.textContent = `Today's Opportunity Outlook: ${severity.label}`;

  bodyEl.innerHTML = `
    <article class="ops-summary__metric ops-summary__metric--wide">
      <p class="ops-summary__label">Lead story</p>
      <p class="ops-summary__value ops-summary__value--text">${escapeHtml(narrative)}</p>
    </article>
    <article class="ops-summary__metric">
      <p class="ops-summary__label">As of</p>
      <p class="ops-summary__value">${escapeHtml(formatTrustGenerated(publishedAt))}</p>
    </article>
    <article class="ops-summary__metric">
      <p class="ops-summary__label">Sources</p>
      <p class="ops-summary__value">${escapeHtml(sourceCoverage)}</p>
    </article>
    <article class="ops-summary__metric">
      <p class="ops-summary__label">Entities</p>
      <p class="ops-summary__value">${escapeHtml(String(entityTotal || 0))}</p>
    </article>
    <article class="ops-summary__metric">
      <p class="ops-summary__label">Confidence</p>
      <p class="ops-summary__value">${escapeHtml((conf.level || "unknown").toUpperCase())}</p>
    </article>
    ${freshnessState === "healthy" ? "" : `<article class="ops-summary__metric ops-summary__metric--wide"><p class="ops-summary__label">Context</p><p class="ops-summary__value ops-summary__value--text">${escapeHtml(incidentDetail || deltaLine)}</p></article>`}
    <article class="ops-summary__metric ops-summary__metric--wide">
      <p class="ops-summary__label">Next move</p>
      <p class="ops-summary__value ops-summary__value--text">${escapeHtml(recommendation)}</p>
    </article>
  `;

  renderTrustPanel(statusData);
}

function poolMembersForTab(tab = activeQueueView) {
  const direct = Array.isArray(assignmentPools.direct_clients)
    ? assignmentPools.direct_clients
    : [];
  const introducers = Array.isArray(assignmentPools.introducers)
    ? assignmentPools.introducers
    : [];
  const members = [...DEFAULT_ASSIGNEES, ...direct, ...introducers, ...team, ...customAssignees]
    .map((name) => String(name || "").trim())
    .filter(Boolean);
  return [...new Set(members)];
}

function syncSnapshotControls() {
  const sel = $("#dateSelect");
  const emptyEl = $("#dateSelectEmpty");
  const nav = $("#dateNav");
  if (!sel || !emptyEl) return;

  const list = availableDates.length ? availableDates : dateDetails.map((d) => d.date).filter(Boolean);
  const workingDate = getCurrentDate() || lastPayload?.incorporation_date || "";
  const hasList = list.length > 0;
  const canWork = hasList || workingDate;

  if (!canWork) {
    sel.hidden = true;
    sel.innerHTML = "";
    emptyEl.hidden = false;
    emptyEl.textContent = datesApiOk
      ? "Operational dates unavailable — reload the page"
      : "Operational dates unavailable — contact operations";
    if (nav) nav.classList.add("header-date-nav--disabled");
    renderDateHistory(lastDataStatus);
    return;
  }

  if (nav) nav.classList.remove("header-date-nav--disabled");
  emptyEl.hidden = true;
  sel.hidden = false;

  if (hasList) {
    sel.innerHTML = "";
    list.forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d;
      opt.textContent = dateOptionLabel(d);
      sel.appendChild(opt);
    });
    if (workingDate && list.includes(workingDate)) {
      sel.value = workingDate;
      currentDate = workingDate;
    } else if (list.length) {
      sel.value = list[0];
      currentDate = list[0];
    }
  } else if (workingDate) {
    sel.innerHTML = `<option value="${escapeHtml(workingDate)}">${escapeHtml(formatDisplayDate(workingDate))}</option>`;
    sel.value = workingDate;
    currentDate = workingDate;
  }

  renderDateHistory(lastDataStatus);
}

function renderQueueHero(payload) {
  const dateEl = $("#queueHeroDate");
  const refreshedEl = $("#queueHeroRefreshed");
  const statsEl = $("#queueHeroStats");
  if (!dateEl) return;

  const d = payload?.incorporation_date || getCurrentDate();

  if (!d) {
    dateEl.textContent = appHasDates ? "Operational intelligence" : "Operational intelligence unavailable";
    if (refreshedEl) {
      refreshedEl.textContent = appHasDates
        ? "Latest validated operational intelligence will appear automatically"
        : isProductionMode
          ? "No validated operational data is currently available — contact operations"
          : "Run the overnight pipeline or build operational data in Settings (dev)";
    }
    if (statsEl) {
      statsEl.innerHTML =
          '<p class="queue-summary__empty muted">Operational intelligence will populate automatically when validated data is available.</p>';
    }
    updateHeroMetaLine();
    return;
  }

  dateEl.textContent = formatDisplayDate(d);
  const metrics = payload?.metrics || (allLeads.length ? {
    total_leads: allLeads.length,
    uk_count: countUkMu(allLeads).uk,
    mauritius_count: countUkMu(allLeads).mu,
    high_priority: allLeads.filter((l) => (Number(l.score) || 0) >= SCORE_TIERS.high).length,
  } : null);
  renderQueueSummaryMetrics(statsEl, metrics);
  updateHeroMetaLine();
  if (refreshedEl) {
    const ukMod = lastDataStatus?.uk?.file_modified;
    const muMod = lastDataStatus?.mauritius?.file_modified;
    const snapshotTs = ukMod || muMod;
    const refreshed = payload?.last_refreshed
      ? formatRefreshedShort(payload.last_refreshed)
      : snapshotTs
        ? formatTrustGenerated(snapshotTs)
        : "";
    const parts = [];
    if (activeDateMessage) parts.push(activeDateMessage);
    if (refreshed) parts.push(refreshed);
    if (lastDataStatus?.freshness?.state === "stale") {
      parts.push("Stale snapshot");
    }
    refreshedEl.textContent = parts.length ? parts.join(" · ") : "Awaiting last successful update timestamp";
  }
  syncSnapshotControls();
}

function jurisdictionGuidancePhrase() {
  const j = filterState.jurisdiction;
  if (j === "UK") return " · United Kingdom only";
  if (j === "Mauritius") return " · Mauritius only";
  return "";
}

function updateTabGuidance() {
  const el = $("#tabGuidance");
  if (!el) return;
  const n = queueScopedLeads(getFilteredLeads()).length;
  const mode = VIEW_MODES[filterState.viewMode] || VIEW_MODES.all;
  const modePhrase =
    filterState.viewMode === "strong" ? "high-relevance focus" : "full opportunity queue";
  const jPhrase = jurisdictionGuidancePhrase();
  const search = filterState.search.trim();
  if (!queueScopedLeads(allLeads).length) {
    el.textContent = "";
    return;
  }
  if (n === 0) {
    el.textContent = search
      ? `No matches for “${search}”${jPhrase}.`
      : `No entities in this view${jPhrase}.`;
    return;
  }
  el.textContent = search
    ? `${n} entities match “${search}”${jPhrase}`
    : `${n} entities · ${modePhrase}${jPhrase}`;
}

function updateDateNavButtons() {
  if (!availableDates.length) {
    $("#datePrev").disabled = true;
    $("#dateNext").disabled = true;
    return;
  }
  const idx = availableDates.indexOf(getCurrentDate());
  $("#datePrev").disabled = idx < 0 || idx >= availableDates.length - 1;
  $("#dateNext").disabled = idx <= 0;
}

/** Prev/next move along available operational dates only, never calendar padding. */
function navigateDate(delta) {
  if (!availableDates.length) return;
  const idx = availableDates.indexOf(getCurrentDate());
  if (idx < 0) {
    setSelectedDate(availableDates[0]);
    return;
  }
  const next = idx - delta;
  if (next < 0 || next >= availableDates.length) return;
  setSelectedDate(availableDates[next]);
}

function setSelectedDate(date) {
  currentDate = date;
  activeDateMessage = "";
  syncUrlDateParam(date);
  persistOperationalUiState();
  if ($("#dateSelect") && !$("#dateSelect").hidden) {
    $("#dateSelect").value = date;
  }
  filterState.search = "";
  const searchEl = $("#filterSearch");
  if (searchEl) searchEl.value = "";
  allLeads = [];
  lastPayload = null;
  hideQueueLoadError();
  renderQueueHero({ incorporation_date: date }, []);
  renderTable();
  updateTabGuidance();
  updateDateNavButtons();
  fetchDataStatus();
  fetchLeads(false);
  renderDateHistory(lastDataStatus);
}

function showFieldSaved(anchorEl, success = true, fadeMs = 3000) {
  if (!anchorEl) return;
  const wrap = anchorEl.closest(".field-with-save") || anchorEl.parentElement;
  let indicator = wrap.querySelector(".save-feedback");
  if (!indicator) {
    indicator = document.createElement("span");
    indicator.className = "save-feedback";
    anchorEl.insertAdjacentElement("afterend", indicator);
  }
  indicator.textContent = success ? "Saved" : "Save failed";
  indicator.classList.toggle("save-ok", success);
  indicator.classList.toggle("save-fail", !success);
  clearTimeout(indicator._t);
  indicator._t = setTimeout(() => {
    indicator.textContent = "";
    indicator.classList.remove("save-ok", "save-fail");
  }, fadeMs);
}

function countUkMu(rows) {
  let uk = 0;
  let mu = 0;
  for (const r of rows) {
    if (isMauritiusLead(r)) mu += 1;
    else uk += 1;
  }
  return { uk, mu };
}

function setPanelSubtitle(text) {
  const el = $("#panelSubtitle");
  if (!el) return;
  const msg = text || "";
  el.textContent = msg;
  el.hidden = false;
  el.style.visibility = msg ? "visible" : "hidden";
}

function renderQueueZeroState() {
  renderQueueHero({ incorporation_date: getCurrentDate() || null });
  renderExecutiveQuickBar();
  setPanelSubtitle(appHasDates ? "" : "No operational data in this environment");
  const notice = $("#mauritiusMissingNotice");
  if (notice) notice.hidden = true;
  updateTabGuidance();
}

function renderMetricsZeroState() {
  renderQueueZeroState();
}

function updateMauritiusNotice(payload) {
  const notice = $("#mauritiusMissingNotice");
  const text = $("#mauritiusMissingText");
  if (!notice || !text) return;
  const missing = !!payload?.meta?.mauritius_export_missing;
  const ukCount = Number(payload?.metrics?.uk_count) || 0;
  if (missing && ukCount > 0) {
    text.textContent = isProductionMode
      ? "Mauritius GBC/AC companies are not available for this operational date. United Kingdom leads remain available. Contact operations if you expected Mauritius rows."
      : "Mauritius GBC/AC companies are not available for this operational date yet. United Kingdom leads remain available. Operations can add Mauritius rows via the overnight pipeline.";
    notice.hidden = false;
  } else {
    notice.hidden = true;
  }
}

function renderQueue(payload) {
  renderQueueHero(payload);
  renderExecutiveQuickBar();
  setPanelSubtitle("");
  updateMauritiusNotice(payload);
  updateTabGuidance();
}

function renderMetrics(payload) {
  renderQueue(payload);
}

function renderQueueFromFiltered() {
  if (!lastPayload) return;
  const filtered = queueScopedLeads(getFilteredLeads());
  const { uk, mu } = countUkMu(filtered);
  renderQueueHero({
    ...lastPayload,
    metrics: {
      total_leads: filtered.length,
        high_priority: filtered.filter((l) => (Number(l.score) || 0) >= SCORE_TIERS.high).length,
      assigned_count: filtered.filter((l) => (l.assigned_to || "").trim()).length,
      unassigned_count: filtered.filter((l) => !(l.assigned_to || "").trim()).length,
      uk_count: uk,
      mauritius_count: mu,
    },
  });
  updateHeroMetaLine();
  updateTablePanelSubtitle();
}

function renderMetricsFromFiltered() {
  renderQueueFromFiltered();
}


let copyCmdTimer = null;

function wireBannerCopyButton(btn, raw) {
  if (!btn || !raw) return;
  btn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(raw);
      btn.textContent = "Copied ✓";
      clearTimeout(copyCmdTimer);
      copyCmdTimer = setTimeout(() => {
        btn.textContent = btn.dataset.defaultLabel || "Copy";
      }, 2000);
    } catch {
      showToast("Could not copy", true);
    }
  });
}

function renderNoEnvironmentDataBanner() {
  const el = $("#dataStatusBanner");
  if (bannerHideTimer) {
    clearTimeout(bannerHideTimer);
    bannerHideTimer = null;
  }
  el.className = "data-status-banner data-status-banner--amber";
  el.hidden = false;
  if (isProductionMode) {
    el.innerHTML =
      '<p class="data-status-text">⚠ No validated operational intelligence is available in this environment yet. Contact operations if this continues.</p>';
    return;
  }
  const cmd = pipelineCommandToday();
  el.innerHTML = `<p class="data-status-text">⚠ No pipeline data found for this environment. Run the pipeline to generate today's leads.
    <span class="data-status-cmd-wrap"><code class="data-status-cmd">${escapeHtml(cmd)}</code>
    <button type="button" class="data-status-copy" data-default-label="Copy">Copy</button></span>
    <a class="data-status-link" href="/dev" target="_blank" rel="noopener">Open /dev →</a></p>`;
  wireBannerCopyButton(el.querySelector(".data-status-copy"), cmd);
}

function formatTrustUtc(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return `${d.toISOString().replace("T", " ").slice(11, 16)} UTC`;
  } catch {
    return "—";
  }
}

function formatTrustGenerated(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "UTC",
      timeZoneName: "short",
    });
  } catch {
    return "—";
  }
}

function renderTrustStrip(statusData) {
  const el = $("#trustStripInner");
  if (!el) return;
  const date = getCurrentDate();
  const loaded =
    lastPayload?.incorporation_date === date && Number(lastPayload?.count) >= 0
      ? lastPayload
      : null;
  const uk = statusData?.uk || {};
  const mu = statusData?.mauritius || {};
  const conf = statusData?.operational_confidence || {};
  const ukCount = loaded?.metrics?.uk_count ?? uk.row_count ?? 0;
  const muCount = loaded?.metrics?.mauritius_count ?? mu.row_count ?? 0;
  const entityCount = ukCount + muCount;
  const generatedIso = uk.file_modified || mu.file_modified;
  const sourceLabel = `${conf.verified_sources ?? 0}/${Math.max((conf.verified_sources ?? 0) + (conf.failed_sources ?? 0), 1)} registries verified`;

  let health = statusData?.freshness?.state || "unknown";
  let healthLabel = statusData?.freshness?.label || "Unknown";
  if (!date) {
    health = "unknown";
    healthLabel = "Pick a date";
  }
  if ($("#queueErrorBanner") && !$("#queueErrorBanner").hidden) {
    health = "error";
    healthLabel = "Error";
  }

  const snapshotLabel = date ? formatDisplayDate(date) : "—";
  el.innerHTML = `
    <span class="trust-strip__item trust-strip__item--snapshot"><strong>${escapeHtml(snapshotLabel)}</strong> · Operational date ${formatTrustGenerated(generatedIso)}</span>
    <span class="trust-strip__sep" aria-hidden="true">|</span>
    <span class="trust-strip__item trust-strip__item--source">${escapeHtml(sourceLabel)}</span>
    <span class="trust-strip__sep" aria-hidden="true">|</span>
    <span class="trust-strip__item">${entityCount} entities</span>
    <span class="trust-strip__sep" aria-hidden="true">|</span>
    <span class="trust-strip__item">Quality <span class="trust-strip__health trust-strip__health--${health}">${healthLabel}</span></span>
  `;

  renderExecutiveStatusCard(statusData);
}

function activeFilterSummary() {
  if (!allLeads.length) return "";
  const parts = [];
  const mode = VIEW_MODES[filterState.viewMode];
  if (mode?.label) parts.push(mode.label);
  if (filterState.jurisdiction === "UK") parts.push("United Kingdom only");
  if (filterState.jurisdiction === "Mauritius") parts.push("Mauritius only");
  const q = filterState.search.trim();
  if (q) parts.push(`search “${q}”`);
  return parts.join(" · ");
}

function hideQueueLoadError() {
  const el = $("#queueErrorBanner");
  if (el) el.hidden = true;
}

function showQueueLoadError(message) {
  const el = $("#queueErrorBanner");
  if (!el) return;
  el.hidden = false;
  el.innerHTML = `<p><strong>Unable to load operational data.</strong> ${escapeHtml(
    operatorSafeErrorMessage(message)
  )}</p>`;
}

function showConnectivityFailure() {
  showQueueLoadError("Please retry or contact operations.");
  renderMetricsZeroState();
  showTableErrorState();
}

function renderTableStateCell(title, text, actionsHtml = "") {
  const body = $("#leadsBody");
  body.innerHTML = `<tr><td colspan="${TABLE_COLSPAN}" class="empty-state-cell">
    <div class="table-empty-state">
      <h3 class="table-empty-state__title">${escapeHtml(title)}</h3>
      <p class="table-empty-state__text">${text}</p>
      ${actionsHtml}
    </div>
  </td></tr>`;
}

function showTableLoadingState() {
  renderTableStateCell(
    "Loading operational intelligence…",
    "Loading validated operational data for the selected date."
  );
}

function showTableQuietDayState() {
  const dateLabel = formatDisplayDate(getCurrentDate());
  renderTableStateCell(
    "Quiet day",
    `The ${dateLabel} operational dataset is available but has no candidate entities in this queue.`
  );
}

function showTableErrorState() {
  renderTableStateCell(
    "Unable to load operational data",
    "Try another operational date or contact operations."
  );
}

function showTableEmptyState() {
  const body = $("#leadsBody");
  const date = getCurrentDate();
  const detail = dateDetail(date);
  const nearest = nearestAvailableDate(date);
  const canLoad =
    operatorRefreshAllowed && canFetchUk && hasCompaniesHouseKey && date && !detail.has_snapshot;
  let title = "No validated operational data available";
  if (date && detail.has_snapshot) {
    title = "Quiet day — no leads in this queue";
  } else if (date) {
    title = "No operational data for this date";
  }
  let text;
  let primaryBtn = "";
  let secondaryLink = "";
  if (!appHasDates && !date) {
    text =
      "No validated operational intelligence is available for review yet.";
    if (!isProductionMode) {
      text +=
        " Run the ingestion pipeline or place an operational export in exports/YYYY-MM-DD.csv.";
    }
  } else if (isProductionMode) {
    text =
      "Validated operational intelligence is not available for this date. Try another date or contact operations.";
    if (date && nearest && nearest !== date) {
      text = `No validated operational data exists for ${formatDisplayDate(date)}. Showing the nearest available operational date, ${formatDisplayDate(nearest)}.`;
    }
  } else if (canLoad) {
    text =
      "Validated operational intelligence is not available for this date. Use the date menu to pick another day, or load UK register data for this date.";
    primaryBtn = `<button type="button" class="btn btn-primary" id="emptyRefreshData">Load UK data for this date</button>`;
    secondaryLink = `<a class="btn btn-ghost" href="/dev#health" target="_blank" rel="noopener">Operations health →</a>`;
  } else {
    text =
      "Validated operational intelligence is not available for this date. Run the ingestion pipeline or place an operational export in exports/YYYY-MM-DD.csv.";
    primaryBtn = `<button type="button" class="btn btn-secondary" id="emptyRefreshData">Build operational data (dev)</button>`;
    secondaryLink = `<a class="btn btn-ghost" href="/dev#health" target="_blank" rel="noopener">Operations health →</a>`;
  }

  body.innerHTML = `<tr><td colspan="${TABLE_COLSPAN}" class="empty-state-cell">
    <div class="table-empty-state">
      <span class="table-empty-state__mark" aria-hidden="true">A</span>
      <p class="brand-eyebrow table-empty-state__eyebrow">Onboarding Intelligence Platform</p>
      <h3 class="table-empty-state__title">${title}</h3>
      <p class="table-empty-state__text">${text}</p>
      <div class="table-empty-state__actions">
        ${primaryBtn}
        ${secondaryLink}
      </div>
    </div>
  </td></tr>`;

  $("#emptyRefreshData")?.addEventListener("click", () => fetchLeads(true));
}

function renderDataStatusBanner(status) {
  const el = $("#dataStatusBanner");
  if (bannerHideTimer) {
    clearTimeout(bannerHideTimer);
    bannerHideTimer = null;
  }
  const banner = status?.banner;
  if (!banner || banner.type === "none") {
    el.hidden = true;
    el.innerHTML = "";
    el.className = "data-status-banner";
    return;
  }

  const type = banner.type;
  const icon = type === "red" ? "🔴" : type === "amber" ? "⚠" : "✅";
  el.className = `data-status-banner data-status-banner--${type}`;
  el.hidden = false;

  let actions = "";
  if (banner.show_alerts_link && !isProductionMode) {
    actions += ` <a class="data-status-link" href="/dev#alerts" target="_blank" rel="noopener">Open Alerts →</a>`;
  }
  if (banner.pipeline_command && !isProductionMode) {
    const cmd = escapeHtml(banner.pipeline_command);
    actions += ` <span class="data-status-cmd-wrap"><code class="data-status-cmd">${cmd}</code> <button type="button" class="data-status-copy">Copy</button></span>`;
  }

  el.innerHTML = `<p class="data-status-text">${icon} ${escapeHtml(banner.message)}${actions}</p>`;

  const copyBtn = el.querySelector(".data-status-copy");
  if (copyBtn && banner.pipeline_command) {
    copyBtn.dataset.defaultLabel = "Copy";
    wireBannerCopyButton(copyBtn, banner.pipeline_command);
  }

  if (banner.auto_hide_seconds) {
    bannerHideTimer = setTimeout(() => {
      el.hidden = true;
      bannerHideTimer = null;
    }, banner.auto_hide_seconds * 1000);
  }
}

async function fetchDataStatus() {
  const hasQueue = allLeads.length > 0 || !!lastPayload?.incorporation_date;
  if (!appHasDates && !getCurrentDate() && !hasQueue) {
    renderNoEnvironmentDataBanner();
    return;
  }
  const date = getCurrentDate() || todayISO();
  try {
    const res = await fetch(
      `/api/data-status?date=${encodeURIComponent(date)}`
    );
    if (!res.ok) {
      if (!appHasDates && !hasQueue) renderNoEnvironmentDataBanner();
      return;
    }
    const data = await res.json();
    lastDataStatus = data;
    renderTrustStrip(data);
    renderDateHistory(data);
    if (!appHasDates && (!data.banner || data.banner.type === "none") && !hasQueue) {
      renderNoEnvironmentDataBanner();
      return;
    }
    renderDataStatusBanner(data);
  } catch {
    if (!appHasDates && !hasQueue) renderNoEnvironmentDataBanner();
    renderTrustStrip(lastDataStatus);
    renderDateHistory(lastDataStatus);
  }
}

function tierFromScore(score) {
  const s = Number(score) || 0;
  if (s >= SCORE_TIERS.high) return { key: "a", label: "High priority" };
  if (s >= SCORE_TIERS.strong) return { key: "b", label: "High Relevance" };
  return { key: "c", label: "Monitor" };
}

function countTiersFromRows(rows) {
  let pursue = 0;
  let month = 0;
  let monitor = 0;
  for (const r of rows) {
    const t = tierFromScore(r.score).key;
    if (t === "a") pursue += 1;
    else if (t === "b") month += 1;
    else monitor += 1;
  }
  return { pursue, month, monitor };
}

function tierBadge(score) {
  const t = tierFromScore(score);
  return `<span class="tier-badge tier-badge--${t.key}">${t.label}</span>`;
}

function scoreDecisionCell(score) {
  const s = Number(score) || 0;
  const t = tierFromScore(s);
  return `<span class="score-decision score-decision--${t.key}" title="${escapeHtml(t.label)}">
    <span class="score-decision__num">${s}</span>
  </span>`;
}

function scoreBadge(score) {
  const s = Number(score) || 0;
  let cls = "score-low";
  if (s >= 70) cls = "score-high";
  else if (s >= 40) cls = "score-med";
  return `<span class="score-badge ${cls}">${s}</span>`;
}

function scoreWithBar(score) {
  const s = Number(score) || 0;
  const pct = Math.min(100, Math.round(s));
  const t = tierFromScore(s);
  return `<span class="score-wrap">
    <span class="score-wrap__num score-wrap__num--${t.key}">${s}</span>
    <span class="score-wrap__bar" aria-hidden="true"><span class="score-wrap__fill score-wrap__fill--${t.key}" style="width:${pct}%"></span></span>
  </span>`;
}

function formatEntityTypeLabel(raw, jurisdiction) {
  const e = (raw || "").trim();
  if (!e) return jurisdiction === "Mauritius" ? "Company" : "Private Limited Company";
  const key = e.toUpperCase().replace(/\./g, "");
  const map = {
    LTD: "Private Limited Company",
    PLC: "Public Limited Company",
    LLP: "Limited Liability Partnership",
    "GLOBAL BUSINESS COMPANY": "Global Business Company",
    GBC: "Global Business Company",
    "AUTHORISED COMPANY": "Authorised Company",
    AC: "Authorised Company",
    "PRIVATE LIMITED COMPANY": "Private Limited Company",
  };
  if (map[key]) return map[key];
  if (e === e.toUpperCase() && e.length > 3) {
    return e
      .toLowerCase()
      .split(/\s+/)
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ");
  }
  return e.charAt(0).toUpperCase() + e.slice(1);
}

function companyMetaLine(lead) {
  const j = (lead.jurisdiction || "").trim();
  const entity = formatEntityTypeLabel(lead.entity_type, j);
  if (j === "UK") return `United Kingdom · ${entity}`;
  if (j === "Mauritius") return `Mauritius · ${entity}`;
  return entity;
}

function displayCompanyName(name) {
  const raw = (name || "").trim();
  if (!raw) return "—";
  const trimmed = raw.replace(
    /\s+(ltd|limited|plc|llp|gbc|global business company|authorised company)\.?$/i,
    ""
  ).trim();
  return trimmed || raw;
}

function formatSicBullet(lead) {
  if (isMauritiusLead(lead)) return "";
  const sic = (lead.sic_codes || "").trim();
  if (!sic || sic === "—") return "";
  const code = sic.split(",")[0].trim();
  return `SIC ${code} on registry`;
}

function formatIncorporationBullet(lead) {
  const dateText = (lead.incorporation_date || "").trim();
  if (!dateText) return "";
  return `Date of incorporation: ${dateText}`;
}

function formatRegistryIdBullet(lead) {
  const companyNo = (lead.company_number || "").trim();
  if (companyNo) return `Company number: ${companyNo}`;
  const fileNo = (lead.file_no || "").trim();
  if (fileNo) return `File number: ${fileNo}`;
  return "";
}

function formatEntityTypeBullet(lead) {
  const j = (lead.jurisdiction || "").trim();
  const entity = formatEntityTypeLabel(lead.entity_type, j);
  if (!entity) return "";
  return `Type of company: ${entity}`;
}

function formatLocationBullet(lead) {
  const j = (lead.jurisdiction || "").trim();
  if (!j) return "";
  if (j === "UK") return "Location: United Kingdom";
  return `Location: ${j}`;
}

function normalizeInfoText(text) {
  return String(text || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function isDuplicateMetaBullet(lead, bullet) {
  const meta = companyMetaLine(lead);
  const bulletNorm = normalizeInfoText(bullet);
  const metaNorm = normalizeInfoText(meta);
  if (!bulletNorm || !metaNorm) return false;

  const companyBits = meta
    .split("·")
    .map((part) => normalizeInfoText(part))
    .filter(Boolean);

  if (bulletNorm === metaNorm) return true;
  if (companyBits.length >= 2 && bulletNorm === `${companyBits[0]} ${companyBits[1]}`) return true;
  if (companyBits.some((part) => part === bulletNorm)) return true;
  return false;
}

function intelligenceTableBullets(lead) {
  const bullets = [
    formatIncorporationBullet(lead),
    formatEntityTypeBullet(lead),
    formatLocationBullet(lead),
  ].filter(Boolean);

  if (bullets.length) return bullets.slice(0, 3);

  const fallback = [];
  const registryId = formatRegistryIdBullet(lead);
  if (registryId) fallback.push(registryId);
  const sic = formatSicBullet(lead);
  if (sic) fallback.push(sic);
  return fallback.slice(0, 2);
}

function intelligenceNarrative(lead) {
  const raw = (
    lead.intelligence_summary ||
    lead.prospect_reason ||
    lead.why_summary ||
    ""
  ).trim();
  if (raw.includes(" · ") && /priority review|worth a review/i.test(raw)) {
    const facts = (lead.registry_facts || []).filter(Boolean);
    if (facts.length) return facts.slice(0, 2).join(". ") + (facts.length ? "." : "");
    return companyMetaLine(lead);
  }
  return raw;
}

function strategicHint(lead) {
  return (lead.strategic_hint || "").trim();
}

function jurisdictionPill(lead) {
  const j = (lead.jurisdiction || "").trim();
  if (!j) return "";
  const key = j === "Mauritius" ? "mu" : "uk";
  const short = j === "Mauritius" ? "MU" : "UK";
  return `<span class="jurisdiction-pill jurisdiction-pill--${key}" title="${escapeHtml(j)}">${short}</span>`;
}

function tableInterpretationLine(lead) {
  const relevance = (lead.arie_relevance || []).filter(Boolean);
  if (relevance.length) return relevance[0];
  const signals = (lead.intelligence_signals || []).filter(Boolean);
  if (signals.length) return signals[0];
  return strategicHint(lead) || "";
}

function companyCell(lead) {
  const fullName = (lead.company_name || "").trim();
  const displayName = displayCompanyName(fullName);
  return `<div class="company-cell">
    <div class="company-cell__head">
      <span class="company-name" title="${escapeHtml(fullName)}">${escapeHtml(displayName)}</span>
    </div>
  </div>`;
}

function whyContactCell(lead) {
  const bullets = intelligenceTableBullets(lead);
  if (!bullets.length) {
    return `<span class="intel-empty muted">Registry profile only</span>`;
  }
  return `<ul class="intel-bullets">${bullets
    .map((b) => `<li>${escapeHtml(b)}</li>`)
    .join("")}</ul>`;
}

function priorityText(priority) {
  const p = (priority || "Low").toUpperCase();
  return `<span class="priority-text priority-${p.toLowerCase()}">${escapeHtml(p)}</span>`;
}

function displaySic(lead) {
  const sic = lead.sic_codes;
  if (!sic || sic === "—") return "—";
  if (isMauritiusLead(lead)) return "—";
  return escapeHtml(sic);
}

function resetFilters() {
  filterState = createDefaultFilterState();
  commitFilterState();
}

function passesViewMode(lead) {
  const score = Number(lead.score) || 0;
  const mode = filterState.viewMode;
  if (mode === "all") return true;
  if (score < filterState.minScore) return false;
  return true;
}

function getFilteredLeads() {
  const q = filterState.search.toLowerCase();
  const { priority, assigned, jurisdiction } = filterState;

  return allLeads.filter((l) => {
    if (q && !(l.company_name || "").toLowerCase().includes(q)) return false;
    if (!passesViewMode(l)) return false;
    if (priority && l.priority !== priority) return false;
    if (assigned === "__unassigned__" && (l.assigned_to || "").trim()) return false;
    if (assigned && assigned !== "__unassigned__" && l.assigned_to !== assigned) return false;
    if (jurisdiction && (l.jurisdiction || "") !== jurisdiction) return false;
    return true;
  });
}

function sortLeads(rows) {
  const key = sortKey;
  const dir = sortDir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    let av = a[key];
    let bv = b[key];
    if (key === "score") {
      av = Number(av) || 0;
      bv = Number(bv) || 0;
      return (av - bv) * dir;
    }
    av = String(av ?? "").toLowerCase();
    bv = String(bv ?? "").toLowerCase();
    if (av < bv) return -1 * dir;
    if (av > bv) return 1 * dir;
    return 0;
  });
}

function updateSortHeaders() {
  $$("th.sortable").forEach((th) => {
    th.classList.remove("sorted-asc", "sorted-desc");
    th.removeAttribute("aria-sort");
    if (th.dataset.sort === sortKey) {
      th.classList.add(sortDir === "asc" ? "sorted-asc" : "sorted-desc");
      th.setAttribute("aria-sort", sortDir === "asc" ? "ascending" : "descending");
    }
  });
}

function rmList(lead, queueView = activeQueueView) {
  if (queueView === "introducers") return [...poolMembersForTab("introducers")];
  return [...poolMembersForTab("direct_clients")];
}

function assigneeOptions(lead, queueView = activeQueueView) {
  const val = (lead?.assigned_to || "").trim();
  const members = [...new Set(rmList(lead, queueView))];
  let html = `<option value="">Unassigned</option>`;
  for (const name of members) {
    html += `<option value="${escapeHtml(name)}" ${val === name ? "selected" : ""}>${escapeHtml(name)}</option>`;
  }
  if (val && !members.includes(val)) {
    html += `<option value="${escapeHtml(val)}" selected>${escapeHtml(val)}</option>`;
  }
  html += `<option value="${ADD_ASSIGNEE_VALUE}">+ Add name</option>`;
  return html;
}

function normalizeAssigneeName(raw) {
  const cleaned = String(raw || "").trim().replace(/\s+/g, " ");
  if (!cleaned) return "";
  return cleaned.slice(0, 64);
}

function addCustomAssigneeName(name) {
  const normalized = normalizeAssigneeName(name);
  if (!normalized) return "";
  customAssignees.add(normalized);
  return normalized;
}

function promptForAssigneeName(current = "") {
  let value = null;
  let promptUnsupported = false;
  try {
    value = window.prompt("Add assignee name", current);
  } catch {
    promptUnsupported = true;
  }
  if (promptUnsupported) {
    return addCustomAssigneeName(`New Assignee ${customAssignees.size + 1}`);
  }
  return addCustomAssigneeName(value);
}

function handleAssigneeSelection(sel, leadId) {
  const selected = sel.value;
  if (selected !== ADD_ASSIGNEE_VALUE) {
    onAssign(leadId, { assigned_to: selected }, sel);
    return;
  }

  const added = promptForAssigneeName();
  if (!added) {
    const fallback = sel.dataset.prevValue || "";
    sel.value = fallback;
    updateAssignPickerFace(sel);
    return;
  }

  let existing = [...sel.options].find((opt) => opt.value === added);
  if (!existing) {
    existing = document.createElement("option");
    existing.value = added;
    existing.textContent = added;
    sel.insertBefore(existing, sel.querySelector(`option[value="${ADD_ASSIGNEE_VALUE}"]`));
  }
  sel.value = added;
  sel.dataset.prevValue = added;
  updateAssignPickerFace(sel);
  onAssign(leadId, { assigned_to: added }, sel);
}

function queueAssignFaceLabel(lead) {
  return (lead?.assigned_to || "").trim() ? "Assigned" : "Assign";
}

function updateAssignPickerFace(sel) {
  const picker = sel?.closest(".assign-picker");
  if (!picker) return;
  const face = picker.querySelector(".assign-picker__face");
  if (!face) return;
  const assigned = !!(sel.value || "").trim();
  face.textContent = assigned ? "Assigned" : "Assign";
  picker.classList.toggle("assign-picker--open", !assigned);
}

function showAssignSaved(anchorEl) {
  const picker = anchorEl?.closest(".assign-picker");
  if (!picker) return;
  let indicator = picker.querySelector(".assign-save-indicator");
  if (!indicator) {
    indicator = document.createElement("span");
    indicator.className = "assign-save-indicator";
    picker.appendChild(indicator);
  }
  indicator.textContent = "Saved";
  clearTimeout(indicator._t);
  indicator._t = setTimeout(() => {
    indicator.textContent = "";
  }, 1500);
}

function assigneeSelectCell(lead, queueView = activeQueueView) {
  const lid = leadKey(lead);
  const face = queueAssignFaceLabel(lead);
  const unassigned = !(lead?.assigned_to || "").trim();
  return `<label class="assign-picker${unassigned ? " assign-picker--open" : ""}">
    <span class="assign-picker__face">${escapeHtml(face)}</span>
    <select class="assign-select assign-select--queue" data-lead-id="${escapeHtml(lid)}" aria-label="Assign ownership for ${escapeHtml(lead.company_name || "company")}">${assigneeOptions(lead, queueView)}</select>
  </label>`;
}

function wireAssignSelects(root) {
  const scope = root || document;
  scope.querySelectorAll(".assign-select--queue").forEach((sel) => {
    sel.addEventListener("click", (e) => e.stopPropagation());
    sel.addEventListener("keydown", (e) => e.stopPropagation());
    sel.addEventListener("focus", () => {
      sel.dataset.prevValue = sel.value || "";
    });
    sel.addEventListener("change", (e) => {
      e.stopPropagation();
      handleAssigneeSelection(sel, sel.dataset.leadId);
    });
  });
}

function setQueueView(view) {
  activeQueueView = view;
  persistOperationalUiState();
  const isDirect = view === "direct_clients";
  const directPanel = $("#directClientsView");
  const introPanel = $("#introducersView");
  const tabDirect = $("#tabDirect");
  const tabIntro = $("#tabIntroducers");
  const hero = document.querySelector(".decision-hero");
  const tabs = document.querySelector(".queue-tabs");

  if (directPanel) directPanel.hidden = !isDirect;
  if (introPanel) introPanel.hidden = isDirect;
  if (hero) hero.hidden = !isDirect;
  if (tabs) tabs.hidden = false;

  if (tabDirect) {
    tabDirect.classList.toggle("active", isDirect);
    tabDirect.setAttribute("aria-selected", isDirect ? "true" : "false");
  }
  if (tabIntro) {
    tabIntro.classList.toggle("active", !isDirect);
    tabIntro.setAttribute("aria-selected", !isDirect ? "true" : "false");
  }

  if (!isDirect && openLeadId) closeDetailPanel();
  renderTable();
  renderIntroducersView();
  renderMetricsFromFiltered();
  updateTabGuidance();
  fetchLeads(false, true, view);
}

function renderTrustList(items, emptyText) {
  if (!items?.length) {
    return `<p class="trust-layer__empty muted">${escapeHtml(emptyText)}</p>`;
  }
  return `<ul class="trust-layer__list">${items
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("")}</ul>`;
}

function renderWhyContactHtml(lead) {
  const facts = lead.registry_facts || [];
  const signals = lead.intelligence_signals || [];
  const relevance = lead.arie_relevance || [];
  const cautions = (lead.cautions || []).slice(0, 4);

  return `
    <section class="intel-section trust-intel why-contact-section why-contact-section--featured">
      <h3>Signals summary</h3>
      <p class="trust-intel__intro muted">Facts are Registry verified as recorded. Signals use an internal scoring model and should be validated on the source register.</p>
      <div class="trust-layer trust-layer--fact">
        <h4 class="trust-layer__title"><span class="trust-layer__badge trust-layer__badge--high">Registry facts</span> ${provenanceLabel("registry")}</h4>
        ${renderTrustList(facts, "No structured registry facts available for this row.")}
      </div>
      <div class="trust-layer trust-layer--signal">
        <h4 class="trust-layer__title"><span class="trust-layer__badge trust-layer__badge--medium">Signals observed</span> ${provenanceLabel("heuristic")}</h4>
        ${renderTrustList(signals, "No name/SIC/age heuristics triggered beyond base registry data.")}
      </div>
      <div class="trust-layer trust-layer--interpret">
        <h4 class="trust-layer__title"><span class="trust-layer__badge trust-layer__badge--low">Why this may matter to ARIE</span> ${provenanceLabel("heuristic")}</h4>
        ${renderTrustList(relevance, "No commercial interpretation generated — use registry facts and score breakdown only.")}
      </div>
      ${
        cautions.length
          ? `<div class="trust-layer trust-layer--caution">
        <h4 class="trust-layer__title">Review points</h4>
        <ul class="trust-layer__list">${cautions.map((c) => `<li>${escapeHtml(c)}</li>`).join("")}</ul>
      </div>`
          : ""
      }
    </section>`;
}

function renderScoreBreakdownHtml(lead) {
  const bd = lead.score_breakdown;
  if (!bd || !Array.isArray(bd.components)) {
    return `<section class="intel-section score-explainer">
      <h3>Why this score?</h3>
      <p class="muted">Score breakdown is not available for this lead.</p>
    </section>`;
  }

  const bars = bd.components
    .map((c) => {
      const pct = c.max ? Math.min(100, Math.round((c.points / c.max) * 100)) : 0;
      return `
        <li class="score-component">
          <div class="score-component__head">
            <span class="score-component__label">${escapeHtml(c.label)}</span>
            <span class="score-component__pts">${c.points} / ${c.max}</span>
          </div>
          <div class="score-bar" aria-hidden="true"><span class="score-bar__fill" style="width:${pct}%"></span></div>
          <p class="score-component__detail">${escapeHtml(c.detail || "")}</p>
        </li>`;
    })
    .join("");

  return `
    <section class="intel-section score-explainer">
      <h3>Score breakdown <span class="score-explainer__total">${escapeHtml(String(bd.total))}</span> ${provenanceLabel("heuristic")}</h3>
      <p class="score-explainer__summary muted">${escapeHtml(bd.summary || "")}</p>
      <p class="score-explainer__priority">Score band: <strong>${escapeHtml(tierFromScore(lead.score).label)}</strong> (High priority ≥ ${SCORE_TIERS.high} · High Relevance ≥ ${SCORE_TIERS.strong})</p>
      <ul class="score-components">${bars}</ul>
    </section>`;
}

function renderClassificationHtml(lead) {
  const leadType = (lead.lead_type || "direct").toLowerCase();
  const typeNote =
    leadType === "introducer"
      ? "Name pattern may match a professional / fiduciary firm — confirm direct client vs introducer manually."
      : "Classified as a direct onboarding candidate from registry data (rule-based).";

  return `
    <section class="intel-section classification-explainer">
      <h3>Classification logic</h3>
      <p class="classification-explainer__reason muted">${escapeHtml(lead.lead_type_reason || typeNote)}</p>
    </section>`;
}

function verifyCell(lead) {
  const url = (lead.verify_url || "").trim();
  if (!url) return "—";
  return `<a class="btn btn-verify" href="${escapeHtml(url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Verify</a>`;
}

function notesCell(lead) {
  const lid = leadKey(lead);
  const notes = (lead.notes || "").trim();
  if (notes) {
    const preview = escapeHtml(notes.length > 30 ? `${notes.slice(0, 30)}…` : notes);
    return `<button type="button" class="notes-indicator notes-indicator--has" data-lead-id="${escapeHtml(lid)}" title="${escapeHtml(notes)}"><span class="notes-indicator__label">Note</span><span class="notes-preview">${preview}</span></button>`;
  }
  return `<button type="button" class="notes-indicator" data-lead-id="${escapeHtml(lid)}">Add note</button>`;
}

function introducerCategoryBadge(lead) {
  const category = introducerCategoryFromName(lead.company_name || "");
  const tone = category.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return `<span class="introducer-category introducer-category--${escapeHtml(tone)}">${escapeHtml(category)}</span>`;
}

function renderIntroducersView() {
  const body = $("#introducersBody");
  const insights = $("#introducerInsights");
  if (!body || !insights) return;

  const rows = sortLeads(queueScopedLeads(getFilteredLeads(), "introducers"));
  const active = rows.filter((lead) => (lead.assigned_to || "").trim()).length;
  const high = rows.filter((lead) => (Number(lead.score) || 0) >= SCORE_TIERS.high).length;
  const registryVerified = rows.filter((lead) => (lead.verify_url || "").trim()).length;
  const byCategory = rows.reduce((acc, lead) => {
    const cat = introducerCategoryFromName(lead.company_name || "");
    acc[cat] = (acc[cat] || 0) + 1;
    return acc;
  }, {});
  const topCategory = Object.entries(byCategory).sort((a, b) => b[1] - a[1])[0]?.[0] || "Legal / Advisory";

  insights.innerHTML = `
    <article class="insight-kpi"><p class="insight-kpi__label">Active Introducers</p><p class="insight-kpi__value">${active}</p></article>
    <article class="insight-kpi"><p class="insight-kpi__label">New Introducer Candidates</p><p class="insight-kpi__value">${rows.length}</p></article>
    <article class="insight-kpi"><p class="insight-kpi__label">High-Relevance Partners</p><p class="insight-kpi__value">${high}</p></article>
    <article class="insight-kpi"><p class="insight-kpi__label">Verified Professional Firms</p><p class="insight-kpi__value">${registryVerified}</p><p class="insight-kpi__meta">Top profile: ${escapeHtml(topCategory)}</p></article>
  `;

  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="5" class="empty-state-cell"><div class="table-empty-state table-empty-state--inline"><h3 class="table-empty-state__title">No introducer candidates for this operational date.</h3><p class="table-empty-state__text">Switch to Candidate Entities or choose another date.</p></div></td></tr>`;
    return;
  }

  body.innerHTML = rows
    .map((lead) => {
      const lid = leadKey(lead);
      const tierKey = tierFromScore(lead.score).key;
      const label = escapeHtml(lead.company_name || "Company");
      return `
        <tr class="lead-row lead-row--tier-${tierKey}" data-lead-id="${escapeHtml(lid)}" role="button" tabindex="0" aria-label="Review ${label}">
          <td>${companyCell(lead)}</td>
          <td>${introducerCategoryBadge(lead)}</td>
          <td>${tierBadge(lead.score)}</td>
          <td class="assign-cell">${assigneeSelectCell(lead, "introducers")}</td>
          <td class="col-chevron"><span class="row-open-label">Review</span></td>
        </tr>`;
    })
    .join("");

  wireAssignSelects(body);
  body.querySelectorAll(".lead-row").forEach((row) => {
    const open = () => openDetailPanel(row.dataset.leadId);
    row.addEventListener("click", (e) => {
      if (e.target.closest("select, a, button")) return;
      open();
    });
    row.addEventListener("keydown", (e) => {
      if (e.target.closest("select, a, button, textarea")) return;
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        open();
      }
    });
  });
}

function renderTable() {
  const body = $("#leadsBody");
  const queueRows = queueScopedLeads(allLeads);
  if (!appHasDates && !queueRows.length) {
    showTableEmptyState();
    return;
  }

  const filtered = sortLeads(queueScopedLeads(getFilteredLeads()));

  if (!filtered.length) {
    showFilteredEmptyState(queueRows.length > 0);
    updateExportButtonLabel();
    updateTablePanelSubtitle();
    return;
  }

  body.innerHTML = filtered
    .map((lead) => {
      const lid = leadKey(lead);
      const tierKey = tierFromScore(lead.score).key;
      const selected = openLeadId === lid ? " selected" : "";
      const label = escapeHtml(lead.company_name || "Company");
      return `
        <tr class="lead-row lead-row--tier-${tierKey}${selected}" data-lead-id="${escapeHtml(lid)}" role="button" tabindex="0" aria-label="Review ${label}">
          <td>${companyCell(lead)}</td>
          <td>${scoreDecisionCell(lead.score)}</td>
          <td class="prospect-reason-cell">${whyContactCell(lead)}</td>
          <td class="assign-cell">${assigneeSelectCell(lead, "direct_clients")}</td>
          <td class="col-chevron"><span class="row-open-label">Review</span></td>
        </tr>`;
    })
    .join("");

  wireAssignSelects(body);

  body.querySelectorAll(".lead-row").forEach((row) => {
    const open = () => openDetailPanel(row.dataset.leadId);
    row.addEventListener("click", (e) => {
      if (e.target.closest("select, a, button")) return;
      open();
    });
    row.addEventListener("keydown", (e) => {
      if (e.target.closest("select, a, button, textarea")) return;
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        open();
      }
    });
  });

  updateSortHeaders();
  updateTableScrollHint();
  updateExportButtonLabel();
  updateTablePanelSubtitle();
}

function showFilteredEmptyState(hasLeadsInSnapshot) {
  const body = $("#leadsBody");
  if (!hasLeadsInSnapshot) {
    showTableEmptyState();
    return;
  }
  body.innerHTML = `<tr><td colspan="${TABLE_COLSPAN}" class="empty-state-cell">
    <div class="table-empty-state table-empty-state--inline">
      <h3 class="table-empty-state__title">No candidate entities match the current filters.</h3>
      <p class="table-empty-state__text">Try clearing search or jurisdiction filters.</p>
      <button type="button" class="btn btn-secondary" id="emptyViewAll">Show candidate entities</button>
    </div>
  </td></tr>`;
  $("#emptyViewAll")?.addEventListener("click", () => applyViewMode("all"));
}

function updateTableScrollHint() {
  const wrap = document.querySelector(".table-wrap");
  if (!wrap) return;
  const canScrollX = wrap.scrollWidth > wrap.clientWidth + 2;
  const canScrollY = wrap.scrollHeight > wrap.clientHeight + 2;
  wrap.classList.toggle("is-scrollable", canScrollX || canScrollY);
  wrap.classList.toggle("is-scrollable-y", canScrollY);
  updateTablePanelSubtitle();
}

async function onAssign(leadId, patch, anchorEl) {
  const lead = allLeads.find((l) => leadKey(l) === leadId);
  if (!lead) return;
  if (patch.assigned_to !== undefined) lead.assigned_to = patch.assigned_to;
  if (patch.notes !== undefined) lead.notes = patch.notes;
  if (patch.status !== undefined) lead.status = patch.status;

  try {
    const res = await fetch(`/api/leads/${encodeURIComponent(leadId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error("Save failed");
    if (patch.assigned_to !== undefined) {
      if (anchorEl?.classList?.contains("assign-select--queue")) {
        showAssignSaved(anchorEl);
      } else {
        showFieldSaved(anchorEl, true, 1500);
      }
    } else {
      showFieldSaved(anchorEl, true);
    }
    if (detailLead && leadKey(detailLead) === leadId) {
      detailLead = { ...detailLead, ...patch };
      if (patch.assigned_to !== undefined) {
        const detailSel = $("#detailAssignee");
        if (detailSel) detailSel.value = patch.assigned_to || "";
      }
    }
    syncTableFromLead(lead);
  } catch {
    showFieldSaved(anchorEl, false);
    showToast("Could not save — contact operations if this continues", true);
  }
  renderIntroducersView();
  renderMetricsFromFiltered();
}

function syncTableFromLead(lead) {
  const lid = leadKey(lead);
  const row = document.querySelector(`tr[data-lead-id="${CSS.escape(lid)}"]`);
  if (!row) return;
  const queueView = row.closest("#introducersView") ? "introducers" : "direct_clients";
  const ownerCell = row.querySelector(".assign-cell");
  if (ownerCell) {
    ownerCell.innerHTML = assigneeSelectCell(lead, queueView);
    wireAssignSelects(ownerCell);
    const sel = ownerCell.querySelector(".assign-select--queue");
    if (sel) updateAssignPickerFace(sel);
  }
  const notesCellEl = row.querySelector(".notes-cell");
  if (notesCellEl) notesCellEl.innerHTML = notesCell(lead);
}

async function fetchMauritiusIfNeeded(payload, allowAuto = true, queueTab = activeQueueView) {
  if (
    !operatorRefreshAllowed ||
    !allowAuto ||
    !canFetchMauritius ||
    !payload?.meta?.mauritius_export_missing
  ) {
    return payload;
  }
  const date = getCurrentDate();
  if (!date) return payload;

  setLoading(true, "Loading Mauritius operational data…");
  const normalizedTab = queueTab || DEFAULT_QUEUE_TAB;
  const base = `incorporation_date=${encodeURIComponent(date)}&tab=${encodeURIComponent(normalizedTab)}`;
  try {
    const res = await fetch(`/api/refresh/mauritius?${base}`, { method: "POST" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showToast(err.detail || "Mauritius data could not be loaded for this date", true);
      return payload;
    }
    const updated = await res.json();
    await loadAvailableDates();
    showToast(`Mauritius register loaded — ${updated.count} candidates in view`);
    return updated;
  } catch {
    showToast("Mauritius data could not be loaded for this date", true);
    return payload;
  } finally {
    setLoading(false);
  }
}

async function fetchLeads(refresh = false, allowAutoFetch = true, queueTab = activeQueueView) {
  if (refresh && !operatorRefreshAllowed) {
    showToast(
      "Register data is prepared overnight. Try another date or contact operations.",
      true
    );
    return;
  }
  const date = getCurrentDate();
  if (!date) {
    renderMetricsZeroState();
    showTableEmptyState();
    fetchDataStatus();
    return;
  }
  hideQueueLoadError();
  setLoading(true, refresh ? "Loading operational data from registry…" : "Loading operational intelligence…");
  showTableLoadingState();
  const normalizedTab = queueTab || DEFAULT_QUEUE_TAB;
  const base = `incorporation_date=${encodeURIComponent(date)}&tab=${encodeURIComponent(normalizedTab)}`;
  const url = `/api/${refresh ? "refresh" : "leads"}?${base}`;
  try {
    let res = await fetch(url, { method: refresh ? "POST" : "GET" });
    if (refresh && res.ok) {
      await loadAvailableDates();
      res = await fetch(`/api/leads?${base}`);
    }
    if (
      !res.ok &&
      !refresh &&
      allowAutoFetch &&
      operatorRefreshAllowed &&
      res.status === 404 &&
      canFetchUk &&
      hasCompaniesHouseKey
    ) {
      const detail = dateDetail(date);
      if (!detail.has_snapshot && !detail.has_data) {
        return fetchLeads(true, false, normalizedTab);
      }
    }
    if (!res.ok && !refresh && res.status === 404 && availableDates.length) {
      const fallbackDate = nearestAvailableDate(date) || availableDates[0] || "";
      if (fallbackDate && fallbackDate !== date) {
        currentDate = fallbackDate;
        activeDateMessage = `Displaying latest validated operational intelligence from ${formatDisplayDate(fallbackDate)}.`;
        syncSnapshotControls();
        updateDateNavButtons();
        syncUrlDateParam(fallbackDate);
        return fetchLeads(false, false, normalizedTab);
      }
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText);
    }
    let data = await res.json();
    data = await fetchMauritiusIfNeeded(data, allowAutoFetch, normalizedTab);
    lastPayload = data;
    allLeads = data.leads || [];
    upsertDateDetailFromPayload(data);
    if (data.incorporation_date) {
      currentDate = data.incorporation_date;
      if (!availableDates.includes(data.incorporation_date)) {
        availableDates = [...new Set([data.incorporation_date, ...availableDates])].sort().reverse();
      }
      appHasDates = availableDates.length > 0;
      syncSnapshotControls();
      refreshDateSelectLabels();
      updateDateNavButtons();
      syncUrlDateParam(currentDate);
      persistOperationalUiState();
    }
    if ($("#dateSelect") && !$("#dateSelect").hidden) {
      $("#dateSelect").value = currentDate;
    }
    renderMetrics(data);
    if (!data.count && !(data.leads || []).length) {
      const detail = dateDetail(data.incorporation_date || date);
      if (detail.has_snapshot) showTableQuietDayState();
      else showTableEmptyState();
    } else {
      renderTable();
    }
    renderIntroducersView();
    renderMetricsFromFiltered();
    renderTrustStrip(lastDataStatus);
    if (openLeadId) {
      const still = allLeads.find((l) => leadKey(l) === openLeadId);
      if (still) openDetailPanel(openLeadId, true);
      else closeDetailPanel();
    }
    showToast(
      refresh
        ? `Operational data updated — ${data.count} candidates in view`
        : `Operational intelligence loaded — ${data.count} candidates`
    );
  } catch (e) {
    const msg = operatorSafeErrorMessage(e.message);
    showToast(msg, true);
    showQueueLoadError(msg);
    allLeads = [];
    lastPayload = null;
    renderMetricsZeroState();
    showTableErrorState();
    renderTrustStrip(lastDataStatus);
    fetchDataStatus();
  } finally {
    setLoading(false);
    fetchDataStatus();
  }
}

const EXPORT_PLACEHOLDERS = new Set(["", "—", "\u2014", "Pending enrichment"]);

function exportFieldValue(v) {
  let raw = Array.isArray(v) ? v.join(" | ") : v;
  const s = String(raw ?? "").trim();
  if (EXPORT_PLACEHOLDERS.has(s)) return "";
  if (/pending enrichment/i.test(s)) return "";
  return s;
}

function exportCsv() {
  const rows = sortLeads(queueScopedLeads(getFilteredLeads()));
  const btn = $("#exportBtn");
  if (btn?.disabled) return;
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Preparing export…";
  }
  if (!rows.length) {
    updateExportButtonLabel();
    showToast("Nothing to export for the current filters", true);
    return;
  }
  const snapshotDate = getCurrentDate() || "";
  const headers = [
    "snapshot_date",
    "incorporation_date",
    "company_name",
    "jurisdiction",
    "entity_type",
    "score",
    "priority",
    "lead_id",
    "company_number",
    "file_no",
    "source",
    "verify_url",
    "assigned_to",
    "status",
    "notes",
    "registry_facts",
    "intelligence_signals",
    "arie_relevance",
    "intelligence_summary",
    "strategic_hint",
    "prospect_reason",
  ];
  const esc = (v) => {
    const cleaned = exportFieldValue(v);
    return `"${cleaned.replace(/"/g, '""')}"`;
  };
  const lines = [
    headers.join(","),
    ...rows.map((r) =>
      headers
        .map((h) => (h === "snapshot_date" ? esc(snapshotDate) : esc(r[h])))
        .join(",")
    ),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `arie_leads_${getCurrentDate() || "export"}_${exportScopeSlug()}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
  showToast(`Exported ${rows.length} filtered candidate${rows.length === 1 ? "" : "s"}`);
  updateExportButtonLabel();
}

/* —— Intelligence panel —— */

function detailPanelFocusables() {
  const panel = $("#detailPanel");
  if (!panel) return [];
  return [...panel.querySelectorAll(
    'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
  )].filter((el) => el.offsetParent !== null);
}

function handleDetailPanelKeydown(e) {
  if (!openLeadId || e.key !== "Tab") return;
  const items = detailPanelFocusables();
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}

function openDetailPanel(leadId, skipAnim = false) {
  const lead = allLeads.find((l) => leadKey(l) === leadId);
  if (!lead) return;
  const row = document.querySelector(`tr[data-lead-id="${CSS.escape(leadId)}"]`);
  detailReturnFocus = row || document.activeElement;
  openLeadId = leadId;
  detailLead = lead;
  document.body.dataset.panelScrollLock = document.body.style.overflow || "";
  document.body.style.overflow = "hidden";
  $$(".lead-row").forEach((r) => r.classList.toggle("selected", r.dataset.leadId === leadId));

  $("#detailCompanyName").textContent = "Candidate Entity Profile";
  renderDetailShell(lead);
  $("#detailBackdrop").hidden = false;
  $("#detailPanel").hidden = false;
  document.body.classList.add("panel-open");
  if (!skipAnim) {
    requestAnimationFrame(() => {
      $("#detailBackdrop").classList.add("is-open");
      $("#detailPanel").classList.add("is-open");
    });
  } else {
    $("#detailBackdrop").classList.add("is-open");
    $("#detailPanel").classList.add("is-open");
  }
  loadDetailPeople(lead);
  loadExistingBrief(leadId);
  $("#detailClose")?.focus();
}

function closeDetailPanel() {
  openLeadId = null;
  detailLead = null;
  $$(".lead-row").forEach((r) => r.classList.remove("selected"));
  $("#detailBackdrop").classList.remove("is-open");
  $("#detailPanel").classList.remove("is-open");
  document.body.classList.remove("panel-open");
  document.body.style.overflow = document.body.dataset.panelScrollLock || "";
  delete document.body.dataset.panelScrollLock;
  const restore = detailReturnFocus;
  detailReturnFocus = null;
  setTimeout(() => {
    $("#detailBackdrop").hidden = true;
    $("#detailPanel").hidden = true;
    if (restore && typeof restore.focus === "function") restore.focus();
  }, 220);
}

function verifyLabel(lead) {
  return isMauritiusLead(lead) ? "MNS Registry" : "Companies House";
}

function normalizePanelStatus(status) {
  const raw = (status || "").trim();
  if (!raw) return "Monitor";
  const map = {
    "Not contacted": "Monitor",
    Contacted: "Monitor",
    "Follow-up": "Monitor",
    Interested: "High Relevance",
    Onboarding: "High Relevance",
    "Not fit": "Not Relevant",
  };
  return map[raw] || (PANEL_STATUSES.includes(raw) ? raw : "Monitor");
}

function renderDetailShell(lead) {
  const addr = (lead.registered_address || lead.address || "").trim();
  const verifyUrl = (lead.verify_url || "").trim();
  const statusVal = normalizePanelStatus(lead.status);
  const statusOpts = PANEL_STATUSES.map(
    (s) => `<option value="${escapeHtml(s)}" ${statusVal === s ? "selected" : ""}>${escapeHtml(s)}</option>`
  ).join("");

  $("#detailBody").innerHTML = `
    <section class="intel-section detail-company-header">
      <h3 class="detail-company-title">${escapeHtml(lead.company_name)}</h3>
      <p id="detailSummary" class="detail-summary muted">${escapeHtml(companyMetaLine(lead))} · ${provenanceLabel("heuristic")} · ${Number(lead.score) || 0}</p>
      <div class="lead-card-meta">
        ${tierBadge(lead.score)}
        <span class="jurisdiction-badge">${escapeHtml(lead.jurisdiction || "—")}</span>
        <span class="entity-badge">${escapeHtml(formatEntityTypeLabel(lead.entity_type, lead.jurisdiction))}</span>
        ${scoreWithBar(lead.score)}
      </div>
      <p class="detail-meta-line"><strong>Incorporated:</strong> ${escapeHtml(lead.incorporation_date || "—")}</p>
      ${addr ? `<p class="detail-meta-line"><strong>Registered address:</strong> ${escapeHtml(addr)}</p>` : ""}
      ${
        verifyUrl
          ? `<a class="btn btn-verify btn-block" href="${escapeHtml(verifyUrl)}" target="_blank" rel="noopener">Verify on ${escapeHtml(verifyLabel(lead))}</a> ${provenanceLabel("registry")}`
          : provenanceLabel("unavailable")
      }
    </section>

    ${renderWhyContactHtml(lead)}
    ${renderScoreBreakdownHtml(lead)}
    ${renderClassificationHtml(lead)}

    <section class="intel-section" id="detailOfficersSection">
      <h3>Directors &amp; Officers</h3>
      <p class="muted">Loading registry officers…</p>
    </section>

    <section class="intel-section" id="detailPscSection">
      <h3>Persons with Significant Control</h3>
      <p class="muted">Loading PSC records…</p>
    </section>

    <section class="intel-section">
      <h3>Notes &amp; review status</h3>
      <label class="detail-field field-with-save">
        <span class="detail-field__label">Assigned RM</span>
        <select id="detailAssignee" class="detail-select assign-select" data-lead-id="${escapeHtml(leadKey(lead))}" aria-label="Assign relationship manager">${assigneeOptions(lead)}</select>
        <p class="owner-suggestion__note muted">Internal workflow ownership only.</p>
      </label>
      <label class="detail-field field-with-save">
        <span>Notes</span>
        <textarea id="detailNotes" class="notes-area" rows="3" placeholder="Add note…">${escapeHtml(lead.notes || "")}</textarea>
      </label>
      <label class="detail-field field-with-save">
        <span>Status</span>
        <select id="detailStatus" class="detail-select">${statusOpts}</select>
      </label>
    </section>

    <section class="intel-section" id="detailBriefSection">
      <h3>AI Brief ${provenanceLabel("ai")}</h3>
      <p class="muted brief-disclaimer">AI-generated summary — verify Registry verified sources before review.</p>
      <div id="detailBriefContent"></div>
    </section>
  `;

  $("#detailAssignee")?.addEventListener("focus", (e) => {
    e.target.dataset.prevValue = e.target.value || "";
  });
  $("#detailAssignee")?.addEventListener("change", (e) =>
    handleAssigneeSelection(e.target, leadKey(lead))
  );
  $("#detailNotes").addEventListener("blur", (e) =>
    onAssign(leadKey(lead), { notes: e.target.value }, e.target)
  );
  $("#detailStatus").addEventListener("change", (e) =>
    onAssign(leadKey(lead), { status: e.target.value }, e.target)
  );
}

function renderEnrichmentInfoBox(message) {
  return (
    '<div class="enrichment-unavailable" role="status">' +
    `<p>ℹ ${escapeHtml(message)}</p>` +
    "</div>"
  );
}

function renderEnrichmentUnavailable(message, leadId) {
  return (
    '<div class="enrichment-unavailable" role="status">' +
    `<p>ℹ ${escapeHtml(message)}</p>` +
    `<button type="button" class="btn btn-secondary btn-sm enrichment-retry" data-lead-id="${escapeHtml(leadId)}">Retry</button>` +
    "</div>"
  );
}

async function loadDetailPeople(lead, options = {}) {
  const { refresh = false } = options;
  const lid = leadKey(lead);
  const date = getCurrentDate();
  const officersEl = $("#detailOfficersSection");
  const pscEl = $("#detailPscSection");

  if (isMauritiusLead(lead)) {
    const info = renderEnrichmentInfoBox(MU_DIRECTOR_MSG);
    const unavailable = provenanceLabel("unavailable");
    officersEl.innerHTML = `<h3>Directors &amp; Officers ${unavailable}</h3>${info}`;
    pscEl.innerHTML = `<h3>Persons with Significant Control ${unavailable}</h3>${info}`;
    return;
  }

  officersEl.innerHTML = `<h3>Directors &amp; Officers ${provenanceLabel("registry")}</h3><p class="muted">Loading registry officers…</p>`;
  pscEl.innerHTML = `<h3>Persons with Significant Control ${provenanceLabel("registry")}</h3><p class="muted">Loading PSC records…</p>`;

  try {
    const refreshParam = refresh ? "&refresh=true" : "";
    const res = await fetch(
      `/api/leads/${encodeURIComponent(lid)}/people?incorporation_date=${encodeURIComponent(date)}${refreshParam}`
    );
    const data = await res.json().catch(() => ({}));

    if (data.enrichment_status === "unavailable") {
      const msg =
        data.enrichment_message ||
        "Director data temporarily unavailable — click to retry";
      const box = renderEnrichmentUnavailable(msg, lid);
      officersEl.innerHTML = `<h3>Directors &amp; Officers</h3>${box}`;
      pscEl.innerHTML = `<h3>Persons with Significant Control</h3>${box}`;
      officersEl.querySelector(".enrichment-retry")?.addEventListener("click", () => {
        loadDetailPeople(lead, { refresh: true });
      });
      return;
    }

    if (!res.ok) {
      const msg = data.detail || "Director data temporarily unavailable — click to retry";
      const box = renderEnrichmentUnavailable(msg, lid);
      officersEl.innerHTML = `<h3>Directors &amp; Officers</h3>${box}`;
      pscEl.innerHTML = `<h3>Persons with Significant Control</h3>${box}`;
      officersEl.querySelector(".enrichment-retry")?.addEventListener("click", () => {
        loadDetailPeople(lead, { refresh: true });
      });
      return;
    }

    officersEl.innerHTML = `<h3>Directors &amp; Officers</h3>${renderOfficersTable(data.officers || [])}`;
    pscEl.innerHTML = `<h3>Persons with Significant Control</h3>${renderPscTable(data.psc || [])}`;
  } catch {
    const box = renderEnrichmentUnavailable(
      "Director data temporarily unavailable — click to retry",
      lid
    );
    officersEl.innerHTML = `<h3>Directors &amp; Officers</h3>${box}`;
    pscEl.innerHTML = `<h3>Persons with Significant Control</h3>${box}`;
    officersEl.querySelector(".enrichment-retry")?.addEventListener("click", () => {
      loadDetailPeople(lead, { refresh: true });
    });
  }
}

function renderOfficersTable(officers) {
  if (!officers.length) return `<p class="muted">No officers on record.</p>`;
  const rows = officers
    .map(
      (o) => `<tr>
        <td>${escapeHtml(o.name)}</td>
        <td>${escapeHtml(o.role || "—")}</td>
        <td>${escapeHtml(o.nationality || "—")}</td>
        <td>${escapeHtml(o.country_of_residence || "—")}</td>
        <td>${escapeHtml(o.appointed_on || "—")}</td>
      </tr>`
    )
    .join("");
  return `<div class="mini-table-wrap"><table class="mini-table">
    <thead><tr><th>Name</th><th>Role</th><th>Nationality</th><th>Country of Residence</th><th>Appointed</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

function renderPscTable(psc) {
  if (!psc.length) return `<p class="muted">No PSC records.</p>`;
  const rows = psc
    .map(
      (p) => `<tr>
        <td>${escapeHtml(p.name)}</td>
        <td>${escapeHtml(p.nationality || "—")}</td>
        <td>${escapeHtml(p.country_of_residence || "—")}</td>
        <td>${escapeHtml(p.natures_of_control || "—")}</td>
      </tr>`
    )
    .join("");
  return `<div class="mini-table-wrap"><table class="mini-table">
    <thead><tr><th>Name</th><th>Nationality</th><th>Country of Residence</th><th>Nature of Control</th></tr></thead>
    <tbody>${rows}</tbody></table></div>`;
}

function renderBriefSection() {
  const el = $("#detailBriefContent");
  if (!hasOpenaiKey) {
    el.innerHTML = `<p class="muted">AI brief available once OpenAI key is configured</p>`;
    return;
  }
  el.innerHTML = `
    <button type="button" class="btn btn-secondary btn-sm" id="generateBriefBtn">Generate Brief</button>
    <div id="briefOutput" class="brief-block" hidden></div>
  `;
  $("#generateBriefBtn").addEventListener("click", generateBrief);
}

async function loadExistingBrief(leadId) {
  renderBriefSection();
  if (!hasOpenaiKey) return;
  try {
    const res = await fetch(`/api/leads/${encodeURIComponent(leadId)}/brief`);
    if (!res.ok) return;
    const data = await res.json();
    showBriefContent(data.brief);
  } catch {
    /* no saved brief */
  }
}

async function generateBrief() {
  if (!detailLead || !hasOpenaiKey) return;
  const lid = leadKey(detailLead);
  const btn = $("#generateBriefBtn");
  btn.disabled = true;
  btn.textContent = "Generating…";
  try {
    const res = await fetch(
      `/api/leads/${encodeURIComponent(lid)}/brief?incorporation_date=${encodeURIComponent(getCurrentDate())}`,
      { method: "POST" }
    );
    if (!res.ok) throw new Error("Brief failed");
    const data = await res.json();
    showBriefContent(data.brief);
  } catch {
    showToast("Could not generate brief", true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Generate Brief";
  }
}

function showBriefContent(brief) {
  const out = $("#briefOutput");
  if (!out) return;
  const hook = brief?.hook || brief?.summary || "";
  const body = brief?.body || brief?.text || (typeof brief === "string" ? brief : JSON.stringify(brief, null, 2));
  out.hidden = false;
  out.innerHTML = hook ? `<p class="brief-hook">${escapeHtml(hook)}</p><p>${escapeHtml(body)}</p>` : `<p>${escapeHtml(body)}</p>`;
}

function applyEnvBadgeFallback() {
  const el = $("#envBadge");
  if (!el) return;
  const raw = (el.textContent || "").trim();
  if (!raw.includes("{{ENV_BADGE")) return;
  el.textContent = "LOCAL PREVIEW";
  el.classList.remove("env-badge--live");
  el.classList.remove("env-badge--demo");
  el.classList.remove("env-badge--hybrid");
  el.classList.add("env-badge--dev");
}

function showWrongOpenModeBanner() {
  if (window.__arieWrongOpenWarned) return;
  const badge = $("#envBadge");
  if (!badge?.textContent.includes("{{ENV_BADGE")) return;
  window.__arieWrongOpenWarned = true;
  const banner = document.createElement("div");
  banner.className = "queue-error-banner";
  banner.setAttribute("role", "alert");
  banner.innerHTML =
    "<p><strong>Open the app through the server.</strong> In your browser go to <code>http://127.0.0.1:8080</code> (not the HTML file directly). The queue cannot load otherwise.</p>";
  document.querySelector(".trust-strip")?.after(banner);
}

function init() {
  applyEnvBadgeFallback();
  showWrongOpenModeBanner();
  renderProvenancePanel();
  $("#reviewHighPriorityBtn")?.addEventListener("click", scrollToLeadQueue);
  $("#refreshBtn")?.addEventListener("click", () => fetchLeads(true));
  $("#exportBtn")?.addEventListener("click", exportCsv);
  $("#tabDirect")?.addEventListener("click", () => setQueueView("direct_clients"));
  $("#tabIntroducers")?.addEventListener("click", () => setQueueView("introducers"));

  $("#datePrev").addEventListener("click", () => navigateDate(-1));
  $("#dateNext").addEventListener("click", () => navigateDate(1));
  $("#dateSelect").addEventListener("change", () => setSelectedDate($("#dateSelect").value));

  $("#copyMuCmd")?.addEventListener("click", () => {
    const cmd = $("#muPipelineCmd")?.textContent;
    if (!cmd) return;
    navigator.clipboard.writeText(cmd).then(() => showToast("Command copied"));
  });

  $("#detailClose").addEventListener("click", closeDetailPanel);
  $("#detailBackdrop").addEventListener("click", closeDetailPanel);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && openLeadId) closeDetailPanel();
    handleDetailPanelKeydown(e);
  });

  const rerenderFromDom = () => {
    readFilterStateFromDom();
    commitFilterState();
  };
  $("#filtersForm")?.addEventListener("submit", (e) => e.preventDefault());
  $("#filtersForm")?.addEventListener("reset", (e) => {
    e.preventDefault();
    resetFilters();
  });
  document.querySelectorAll(".view-mode__btn[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => applyViewMode(btn.dataset.view));
  });
  $("#filterSearch")?.addEventListener("input", rerenderFromDom);
  $("#jurisdictionFilter")?.addEventListener("change", rerenderFromDom);
  document.querySelectorAll(".ui-mode-switch__btn[data-mode]").forEach((btn) => {
    btn.addEventListener("click", () => setUiViewMode(btn.dataset.mode));
  });

  $$("th.sortable").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (filterState.sortKey === key) {
        filterState.sortDir = filterState.sortDir === "asc" ? "desc" : "asc";
      } else {
        filterState.sortKey = key;
        filterState.sortDir = key === "score" ? "desc" : "asc";
      }
      commitFilterState();
    });
  });

  applyScoreTierLabels();
  applyFilterStateToDom();
  applyUiViewModeToDom();

  const header = $(".header");
  const tableWrap = document.querySelector(".table-wrap");
  const restoredQueueTab = restorePersistedQueueTab();
  let scrollPersistTicking = false;

  function queueScrollPersist() {
    if (scrollPersistTicking) return;
    scrollPersistTicking = true;
    window.requestAnimationFrame(() => {
      persistScrollState();
      scrollPersistTicking = false;
    });
  }

  function handleScroll() {
    const scrolled =
      window.scrollY > 60 || (tableWrap && tableWrap.scrollTop > 60);
    header?.classList.toggle("header--compact", scrolled);
    queueScrollPersist();
  }

  window.addEventListener("scroll", handleScroll, { passive: true });

  if (tableWrap) {
    tableWrap.addEventListener("scroll", handleScroll, { passive: true });
  }

  loadMeta()
    .then(() => loadAvailableDates())
    .then((date) => {
      updateTabGuidance();
      fetchDataStatus();
      if (!date) {
        renderMetricsZeroState();
        showTableEmptyState();
        restoreScrollState();
        return;
      }
      return fetchLeads(false).then(() => {
        if (restoredQueueTab === "introducers") setQueueView("introducers");
        restoreScrollState();
      });
    })
    .catch((e) => {
      console.error(e);
      showToast("Could not connect to the app — please retry", true);
      showConnectivityFailure();
    });

  window.addEventListener("offline", () => {
    showToast("You appear to be offline", true);
    showConnectivityFailure();
  });

  window.addEventListener("beforeunload", () => {
    persistOperationalUiState();
    persistScrollState();
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      persistOperationalUiState();
      persistScrollState();
    }
  });
}

init();
