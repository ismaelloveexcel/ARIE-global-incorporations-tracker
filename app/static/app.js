const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const PANEL_STATUSES = ["New", "Contacted", "Not Interested", "Converted"];
const MU_DIRECTOR_MSG =
  "Director and PSC data is not yet available for Mauritius companies. This will be added when MNS API access is confirmed.";

let team = [];
let assignmentPools = {};
let allLeads = [];
const QUEUE_TAB = "direct_clients";
let sortKey = "score";
let sortDir = "desc";
let lastPayload = null;
let hasOpenaiKey = false;
let hasCompaniesHouseKey = false;
let canFetchUk = false;
let canFetchMauritius = false;
let snapshotDates = [];
let availableDates = [];
let dateDetails = [];
let currentDate = "";
let openLeadId = null;
let detailLead = null;
let bannerHideTimer = null;
let isProductionMode = false;
let operatorRefreshAllowed = true;
let lastDataStatus = null;
let detailReturnFocus = null;
const TABLE_COLSPAN = 5;
const SCORE_TIERS = { pursue: 70, strong: 40, monitor: 0 };
const DEFAULT_MIN_SCORE = SCORE_TIERS.pursue;

const VIEW_MODES = {
  pursue: { minScore: SCORE_TIERS.pursue, label: "High priority" },
  strong: { minScore: SCORE_TIERS.strong, label: "Strong" },
  all: { minScore: 0, label: "All" },
};

function createDefaultFilterState() {
  return {
    search: "",
    viewMode: "pursue",
    minScore: SCORE_TIERS.pursue,
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

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function isDemoCapEnabled() {
  return !!$("#demoMode")?.checked;
}

function pipelineCommandToday() {
  return `python main.py --date ${todayISO()} --skip-difc`;
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
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
  const mode = VIEW_MODES[filterState.viewMode] || VIEW_MODES.pursue;
  filterState.minScore = mode.minScore;
  syncViewModeButtons();
  syncSortGlobalsFromFilterState();
  updateSortHeaders();
}

function readFilterStateFromDom() {
  filterState.search = ($("#filterSearch")?.value || "").trim();
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
  renderTable();
  renderQueueFromFiltered();
}

function setFilterState(partial) {
  filterState = { ...filterState, ...partial };
  commitFilterState();
}

function applyScoreTierLabels() {
  const heroBtn = $("#reviewHighPriorityBtn");
  if (heroBtn) heroBtn.textContent = "Review pursue-now leads";
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

function exportScopeSlug() {
  const mode = filterState.viewMode;
  if (mode === "pursue") return "pursue";
  if (mode === "strong") return "strong";
  return "all";
}

function exportScopeLabel() {
  const mode = filterState.viewMode;
  if (mode === "pursue") return "pursue-now";
  if (mode === "strong") return "strong";
  return "all";
}

function updateExportButtonLabel() {
  const btn = $("#exportBtn");
  if (!btn) return;
  const n = getFilteredLeads().length;
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

function reviewHighPriorityLeads() {
  applyViewMode("pursue");
  const n = getFilteredLeads().length;
  if (!n) showToast("No pursue-now leads in this snapshot", true);
  document.querySelector(".table-wrap")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function formatDisplayDate(iso) {
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

function getCurrentDate() {
  return $("#dateSelect")?.value || currentDate;
}

function isMauritiusLead(lead) {
  const source = (lead?.source || "").toLowerCase();
  return source === "mauritius_mns" || (lead?.jurisdiction || "").trim() === "Mauritius";
}

function leadKey(lead) {
  return lead?.lead_id || lead?.company_number || "";
}

function applyOperationalMode(meta) {
  isProductionMode = !!meta?.is_production;
  operatorRefreshAllowed = meta?.operator_refresh_allowed !== false;

  const demoBox = $("#demoMode");
  if (demoBox && !demoBox.dataset.userTouched) {
    demoBox.checked = !!meta?.default_demo_cap;
  }

  const devLink = $("#devOpsLink");
  if (devLink) devLink.hidden = meta?.show_dev_link === false;

  const refreshBtn = $("#refreshBtn");
  if (refreshBtn) {
    refreshBtn.hidden = !operatorRefreshAllowed;
    refreshBtn.disabled = !operatorRefreshAllowed;
    refreshBtn.title = operatorRefreshAllowed
      ? "Refresh register data"
      : "Register data is prepared overnight — contact operations if a date is missing";
  }

  const badge = $("#envBadge");
  if (badge && meta?.is_production !== undefined) {
    badge.textContent = meta.is_production ? "LIVE SNAPSHOT" : "DEV MODE";
    badge.classList.toggle("env-badge--live", !!meta.is_production);
    badge.classList.toggle("env-badge--dev", !meta.is_production);
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
  const demo = isDemoCapEnabled();
  try {
    const res = await fetch(`/api/available-dates?demo=${demo}`);
    datesApiOk = res.ok;
    if (!res.ok) {
      availableDates = [];
      dateDetails = [];
      appHasDates = false;
      syncSnapshotControls();
      updateDateNavButtons();
      return currentDate || "";
    }
    const data = await res.json();
    availableDates = data.dates || [];
    snapshotDates = data.snapshot_dates || [];
    dateDetails = data.date_details || [];
    canFetchUk = !!data.can_fetch_uk;
    canFetchMauritius = !!data.can_fetch_mauritius;
    const recommended = data.recommended || availableDates[0] || "";
    if (recommended) currentDate = recommended;
    appHasDates = availableDates.length > 0;
    syncSnapshotControls();
    updateDateNavButtons();
    return appHasDates ? recommended : currentDate || "";
  } catch {
    datesApiOk = false;
    availableDates = [];
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

function poolMembersForTab() {
  const members = assignmentPools.direct_clients;
  if (Array.isArray(members) && members.length) return members;
  return ["Ismael", "Tasneem"];
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
      ? "Date list unavailable — refresh the page"
      : "Snapshot list unavailable — check that the app server is up to date";
    if (nav) nav.classList.add("header-date-nav--disabled");
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
}

function renderHeroTierStats(statsEl, tierRows) {
  if (!statsEl) return;
  const tiers = countTiersFromRows(tierRows);
  statsEl.innerHTML = `
    <p class="decision-metric decision-metric--pursue">
      <span class="decision-metric__value">${tiers.pursue}</span>
      <span class="decision-metric__label">pursue-now leads</span>
    </p>
    <p class="decision-metric decision-metric--strong">
      <span class="decision-metric__value">${tiers.month}</span>
      <span class="decision-metric__label">strong leads</span>
    </p>
  `;
}

function heroTierRows(payload, rowsForTiers) {
  if (rowsForTiers !== undefined) return rowsForTiers;
  const activeDate = payload?.incorporation_date || getCurrentDate();
  if (
    !allLeads.length ||
    !lastPayload?.incorporation_date ||
    lastPayload.incorporation_date !== activeDate ||
    activeDate !== getCurrentDate()
  ) {
    return [];
  }
  return allLeads;
}

function renderQueueHero(payload, rowsForTiers) {
  const dateEl = $("#queueHeroDate");
  const refreshedEl = $("#queueHeroRefreshed");
  const statsEl = $("#queueHeroStats");
  if (!dateEl) return;

  const d = payload?.incorporation_date || getCurrentDate();
  const tierRows = heroTierRows(payload, rowsForTiers);

  if (!d) {
    dateEl.textContent = appHasDates ? "Choose a snapshot date" : "No snapshot loaded yet";
    if (refreshedEl) {
      refreshedEl.textContent = appHasDates
        ? "Pick a date in the header to load leads"
        : isProductionMode
          ? "Choose a snapshot date — contact operations if data is missing"
          : "Run the daily pipeline or refresh register data in Settings";
    }
    renderHeroTierStats(statsEl, []);
    return;
  }

  dateEl.textContent = formatDisplayDate(d);
  renderHeroTierStats(statsEl, tierRows);
  const mixEl = $("#queueHeroMix");
  if (mixEl) {
    const counts =
      lastPayload?.incorporation_date === d && lastPayload?.metrics
        ? lastPayload.metrics
        : null;
    const ukN = counts ? counts.uk_count ?? 0 : countUkMu(tierRows).uk;
    const muN = counts ? counts.mauritius_count ?? 0 : countUkMu(tierRows).mu;
    if (ukN > 0 || muN > 0) {
      mixEl.hidden = false;
      mixEl.textContent = `${ukN} UK · ${muN} Mauritius`;
    } else {
      mixEl.hidden = true;
      mixEl.textContent = "";
    }
  }
  if (refreshedEl) {
    refreshedEl.textContent = payload?.last_refreshed
      ? formatRefreshedShort(payload.last_refreshed)
      : "Sorted by opportunity score";
  }
  syncSnapshotControls();
}

function updateTabGuidance() {
  const el = $("#tabGuidance");
  if (!el) return;
  const n = getFilteredLeads().length;
  const mode = VIEW_MODES[filterState.viewMode] || VIEW_MODES.pursue;
  const min = mode.minScore;
  const modePhrase =
    filterState.viewMode === "pursue" ? "pursue-now" : mode.label.toLowerCase();
  const search = filterState.search.trim();
  if (!allLeads.length) {
    el.textContent = "";
    return;
  }
  if (n === 0) {
    el.textContent = search
      ? `No ${modePhrase} leads match “${search}” — try Strong or All.`
      : `No leads in ${modePhrase} view (score ≥${min}) — try Strong or All.`;
    return;
  }
  el.textContent = search
    ? `Showing ${n} ${modePhrase} leads matching “${search}” (score ≥${min})`
    : `Showing ${n} ${modePhrase} leads (score ≥${min}) · sorted by score`;
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

/** Prev/next move along prepared snapshots only (availableDates), never calendar padding. */
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
  if ($("#dateSelect") && !$("#dateSelect").hidden) {
    $("#dateSelect").value = date;
  }
  allLeads = [];
  lastPayload = null;
  hideQueueLoadError();
  renderQueueHero({ incorporation_date: date }, []);
  renderTable();
  updateTabGuidance();
  updateDateNavButtons();
  fetchDataStatus();
  fetchLeads(false);
}

function showFieldSaved(anchorEl, success = true) {
  if (!anchorEl) return;
  const wrap = anchorEl.closest(".field-with-save") || anchorEl.parentElement;
  let indicator = wrap.querySelector(".save-feedback");
  if (!indicator) {
    indicator = document.createElement("span");
    indicator.className = "save-feedback";
    anchorEl.insertAdjacentElement("afterend", indicator);
  }
  indicator.textContent = success ? "Saved ✓" : "Save failed ✗";
  indicator.classList.toggle("save-ok", success);
  indicator.classList.toggle("save-fail", !success);
  clearTimeout(indicator._t);
  indicator._t = setTimeout(() => {
    indicator.textContent = "";
    indicator.classList.remove("save-ok", "save-fail");
  }, 3000);
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
  el.hidden = !msg;
}

function renderQueueZeroState() {
  renderQueueHero({ incorporation_date: getCurrentDate() || null }, []);
  setPanelSubtitle(appHasDates ? "" : "No snapshot data in this environment");
  updateTabGuidance();
}

function renderMetricsZeroState() {
  renderQueueZeroState();
}

function renderQueue(payload) {
  renderQueueHero(payload);
  setPanelSubtitle("");
  const notice = $("#mauritiusMissingNotice");
  if (notice) notice.hidden = true;
  updateTabGuidance();
}

function renderMetrics(payload) {
  renderQueue(payload);
}

function renderQueueFromFiltered() {
  if (!lastPayload) return;
  const filtered = getFilteredLeads();
  const { uk, mu } = countUkMu(filtered);
  renderQueueHero(
    {
      ...lastPayload,
      metrics: {
        total_leads: filtered.length,
        high_priority: filtered.filter((l) => (Number(l.score) || 0) >= 70).length,
        assigned_count: filtered.filter((l) => (l.assigned_to || "").trim()).length,
        unassigned_count: filtered.filter((l) => !(l.assigned_to || "").trim()).length,
        uk_count: uk,
        mauritius_count: mu,
      },
    },
    filtered
  );
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
      '<p class="data-status-text">⚠ No incorporation snapshot is available in this environment yet. Try another date or contact operations.</p>';
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

function exportAgeHours(iso) {
  if (!iso) return null;
  try {
    return (Date.now() - new Date(iso).getTime()) / 3_600_000;
  } catch {
    return null;
  }
}

const TRUST_STALE_HOURS = 30;

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
  const ukCount = loaded?.metrics?.uk_count ?? uk.row_count ?? 0;
  const muCount = loaded?.metrics?.mauritius_count ?? mu.row_count ?? 0;
  const inView = loaded?.count ?? (allLeads.length || ukCount + muCount);
  const generatedIso = uk.file_modified || mu.file_modified;
  const snapshotFile = date ? `exports/${date}.csv` : "—";

  let health = "healthy";
  let healthLabel = "Healthy";
  if ($("#queueErrorBanner") && !$("#queueErrorBanner").hidden) {
    health = "error";
    healthLabel = "Error";
  } else if (!date) {
    health = "unknown";
    healthLabel = "Pick a date";
  } else if (!uk.exists && !mu.exists) {
    health = "missing";
    healthLabel = "No snapshot";
  } else if (uk.exists && !mu.exists) {
    health = "partial";
    healthLabel = "Partial";
  } else if (statusData?.banner?.type === "red") {
    health = "error";
    healthLabel = "Issue";
  } else if (statusData?.banner?.type === "amber") {
    health = "partial";
    healthLabel = "Check";
  }

  const ageH = exportAgeHours(generatedIso);
  if (health === "healthy" && ageH != null && ageH > TRUST_STALE_HOURS) {
    health = "stale";
    healthLabel = "Stale";
  }

  const snapshotLabel = date ? formatDisplayDate(date) : "—";
  el.innerHTML = `
    <span class="trust-strip__item trust-strip__item--snapshot">Snapshot: <strong>${escapeHtml(snapshotLabel)}</strong> · Generated ${formatTrustGenerated(generatedIso)}</span>
    <span class="trust-strip__sep" aria-hidden="true">|</span>
    <span class="trust-strip__item">UK: <strong>Updated ${formatTrustUtc(uk.file_modified)}</strong> · ${ukCount} leads</span>
    <span class="trust-strip__sep" aria-hidden="true">|</span>
    <span class="trust-strip__item">Mauritius: <strong>Updated ${formatTrustUtc(mu.file_modified)}</strong> · ${muCount} leads</span>
    <span class="trust-strip__sep" aria-hidden="true">|</span>
    <span class="trust-strip__item">Queue: <span class="trust-strip__health trust-strip__health--${health}">${healthLabel}</span>${inView ? ` · ${inView} in view` : ""}</span>
  `;
}

function hideQueueLoadError() {
  const el = $("#queueErrorBanner");
  if (el) el.hidden = true;
}

function showQueueLoadError(message) {
  const el = $("#queueErrorBanner");
  if (!el) return;
  el.hidden = false;
  el.innerHTML = `<p><strong>Unable to load snapshot data.</strong> ${escapeHtml(
    message || "Please retry or contact operations."
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
  renderTableStateCell("Loading queue…", "Fetching incorporation snapshot for the selected date.");
}

function showTableQuietDayState() {
  const dateLabel = formatDisplayDate(getCurrentDate());
  renderTableStateCell(
    "Quiet day",
    `The ${dateLabel} snapshot exists but has no direct-client leads in this queue.`
  );
}

function showTableErrorState() {
  renderTableStateCell(
    "Unable to load snapshot data",
    "Please retry or contact operations if this continues."
  );
}

function showTableEmptyState() {
  const date = getCurrentDate();
  const detail = dateDetail(date);
  const canLoad =
    operatorRefreshAllowed && canFetchUk && hasCompaniesHouseKey && date && !detail.has_snapshot;
  let title = "No prepared snapshots available";
  if (date && detail.has_snapshot) {
    title = "Quiet day — no leads in this queue";
  } else if (date) {
    title = "No snapshot for this date";
  }
  let text;
  let primaryBtn = "";
  let secondaryLink = "";
  if (!appHasDates && !date) {
    text =
      "No incorporation snapshots are available yet. Contact operations if you expected yesterday's queue.";
  } else if (isProductionMode) {
    text =
      "Try another date using the date menu. If you expected yesterday's queue, contact operations.";
  } else if (canLoad) {
    text = "Use the date menu to pick another day, or load UK register data for this date.";
    primaryBtn = `<button type="button" class="btn btn-primary" id="emptyRefreshData">Load UK data for this date</button>`;
    secondaryLink = `<a class="btn btn-ghost" href="/dev#health" target="_blank" rel="noopener">Operations health →</a>`;
  } else {
    text = "Choose another date, refresh register data, or run the daily pipeline for this environment.";
    primaryBtn = `<button type="button" class="btn btn-secondary" id="emptyRefreshData">Refresh register data</button>`;
    secondaryLink = `<a class="btn btn-ghost" href="/dev#health" target="_blank" rel="noopener">Operations health →</a>`;
  }

  body.innerHTML = `<tr><td colspan="${TABLE_COLSPAN}" class="empty-state-cell">
    <div class="table-empty-state">
      <span class="table-empty-state__mark" aria-hidden="true">A</span>
      <p class="brand-eyebrow table-empty-state__eyebrow">Arie Finance</p>
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
  const demo = isDemoCapEnabled();
  try {
    const res = await fetch(
      `/api/data-status?date=${encodeURIComponent(date)}&demo=${demo}`
    );
    if (!res.ok) {
      if (!appHasDates && !hasQueue) renderNoEnvironmentDataBanner();
      return;
    }
    const data = await res.json();
    lastDataStatus = data;
    renderTrustStrip(data);
    if (!appHasDates && (!data.banner || data.banner.type === "none") && !hasQueue) {
      renderNoEnvironmentDataBanner();
      return;
    }
    renderDataStatusBanner(data);
  } catch {
    if (!appHasDates && !hasQueue) renderNoEnvironmentDataBanner();
    renderTrustStrip(lastDataStatus);
  }
}

function tierFromScore(score) {
  const s = Number(score) || 0;
  if (s >= SCORE_TIERS.pursue) return { key: "a", label: "Pursue now" };
  if (s >= SCORE_TIERS.strong) return { key: "b", label: "This month" };
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

function jurisdictionPill(lead) {
  const j = (lead.jurisdiction || "").trim();
  if (!j) return "";
  const key = j === "Mauritius" ? "mu" : "uk";
  return `<span class="jurisdiction-pill jurisdiction-pill--${key}">${escapeHtml(j)}</span>`;
}

function companyCell(lead) {
  const entity = (lead.entity_type || "").trim();
  return `<div class="company-cell">
    <div class="company-cell__head">
      <span class="company-name">${escapeHtml(lead.company_name)}</span>
      ${jurisdictionPill(lead)}
    </div>
    ${entity ? `<span class="company-sub">${escapeHtml(entity)}</span>` : ""}
  </div>`;
}

function whyContactCell(lead) {
  const reason = (lead.prospect_reason || lead.why_summary || "").trim();
  if (!reason) return `<span class="why-contact-empty">—</span>`;
  const short = reason.length > 110 ? `${reason.slice(0, 107)}…` : reason;
  const tags = (lead.why_tags || [])
    .slice(0, 2)
    .map((t) => `<span class="why-tag why-tag--inline">${escapeHtml(t)}</span>`)
    .join("");
  return `<div class="why-contact-snippet">
    <p class="why-contact-snippet__text">${escapeHtml(short)}</p>
    ${tags ? `<div class="why-contact-snippet__tags">${tags}</div>` : ""}
  </div>`;
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

function getFilteredLeads() {
  const q = filterState.search.toLowerCase();
  const minScore = filterState.minScore;
  const { priority, assigned, jurisdiction } = filterState;

  return allLeads.filter((l) => {
    if (q && !(l.company_name || "").toLowerCase().includes(q)) return false;
    if (minScore > 0 && (Number(l.score) || 0) < minScore) return false;
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

function suggestedOwnerDisplayName(lead) {
  const name = (lead?.assigned_to || "").trim();
  if (name) return name;
  const pool = poolMembersForTab();
  return pool.length ? pool[0] : "—";
}

function suggestedOwnerCell(lead) {
  const name = suggestedOwnerDisplayName(lead);
  return `<span class="owner-suggestion" title="Suggested for triage — not saved as an assignment yet">
    <span class="owner-suggestion__label">Suggested:</span>
    <span class="owner-suggestion__name">${escapeHtml(name)}</span>
  </span>`;
}

function assignedOptions(lead, selected) {
  const val = selected ?? lead?.assigned_to ?? "";
  const members = [...poolMembersForTab()];
  if (val && !members.includes(val)) members.push(val);
  return members
    .map(
      (t) =>
        `<option value="${escapeHtml(t)}" ${val === t ? "selected" : ""}>${escapeHtml(t)}</option>`
    )
    .join("");
}

function renderWhyContactHtml(lead) {
  const reason = (lead.prospect_reason || lead.why_summary || "").trim();
  const tags = (lead.why_tags || [])
    .map((t) => `<span class="why-tag">${escapeHtml(t)}</span>`)
    .join("");
  const strengths = (lead.strengths || [])
    .slice(0, 4)
    .map((s) => `<li>${escapeHtml(s)}</li>`)
    .join("");

  return `
    <section class="intel-section why-contact-section why-contact-section--featured">
      <h3>Why contact</h3>
      <div class="why-contact-card">
      <p class="why-contact-lead">${escapeHtml(reason || "Review registry profile for fit.")}</p>
      ${tags ? `<div class="why-tags">${tags}</div>` : ""}
      ${
        strengths
          ? `<ul class="why-contact-strengths">${strengths}</ul>`
          : ""
      }
      </div>
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
      <h3>Why this score? <span class="score-explainer__total">${escapeHtml(String(bd.total))}</span></h3>
      <p class="score-explainer__summary">${escapeHtml(bd.summary || "")}</p>
      <p class="score-explainer__priority">Tier: <strong>${escapeHtml(tierFromScore(lead.score).label)}</strong> (Pursue now ≥ ${SCORE_TIERS.pursue} · This month ≥ ${SCORE_TIERS.strong})</p>
      <ul class="score-components">${bars}</ul>
    </section>`;
}

function renderClassificationHtml(lead) {
  const leadType = (lead.lead_type || "direct").toLowerCase();
  const typeNote =
    leadType === "introducer"
      ? "Name suggests a professional / fiduciary firm — still in the main queue; tag introducer relationships manually if relevant."
      : "Onboarding candidate from registry data.";

  const tags = (lead.why_tags || []).map((t) => `<span class="why-tag">${escapeHtml(t)}</span>`).join("");
  const strengths = (lead.strengths || [])
    .slice(0, 4)
    .map((s) => `<li>${escapeHtml(s)}</li>`)
    .join("");
  const cautions = (lead.cautions || [])
    .slice(0, 3)
    .map((c) => `<li>${escapeHtml(c)}</li>`)
    .join("");

  return `
    <section class="intel-section classification-explainer">
      <h3>Classification</h3>
      <p class="classification-explainer__reason">${escapeHtml(lead.lead_type_reason || typeNote)}</p>
      ${tags ? `<div class="why-tags">${tags}</div>` : ""}
      ${
        strengths
          ? `<div class="signal-block signal-block--strength"><h4>Strengths</h4><ul>${strengths}</ul></div>`
          : ""
      }
      ${
        cautions
          ? `<div class="signal-block signal-block--caution"><h4>Review points</h4><ul>${cautions}</ul></div>`
          : ""
      }
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

function renderTable() {
  const body = $("#leadsBody");
  if (!appHasDates && !allLeads.length) {
    showTableEmptyState();
    return;
  }

  const filtered = sortLeads(getFilteredLeads());

  if (!filtered.length) {
    showFilteredEmptyState(allLeads.length > 0);
    updateExportButtonLabel();
    return;
  }

  body.innerHTML = filtered
    .map((lead) => {
      const lid = leadKey(lead);
      const tierKey = tierFromScore(lead.score).key;
      const selected = openLeadId === lid ? " selected" : "";
      const label = escapeHtml(lead.company_name || "Company");
      return `
        <tr class="lead-row lead-row--tier-${tierKey}${selected}" data-lead-id="${escapeHtml(lid)}" role="button" tabindex="0" aria-label="Open ${label} lead profile">
          <td>${companyCell(lead)}</td>
          <td>${scoreDecisionCell(lead.score)}</td>
          <td class="prospect-reason-cell">${whyContactCell(lead)}</td>
          <td class="assign-cell">${suggestedOwnerCell(lead)}</td>
          <td class="col-chevron"><span class="row-open-label">Open</span><span class="row-chevron" aria-hidden="true">›</span></td>
        </tr>`;
    })
    .join("");

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
}

function showFilteredEmptyState(hasLeadsInSnapshot) {
  const body = $("#leadsBody");
  if (!hasLeadsInSnapshot) {
    showTableEmptyState();
    return;
  }
  body.innerHTML = `<tr><td colspan="${TABLE_COLSPAN}" class="empty-state-cell">
    <div class="table-empty-state table-empty-state--inline">
      <h3 class="table-empty-state__title">${escapeHtml(
        filterState.search.trim()
          ? "No leads match your search"
          : filterState.viewMode === "pursue"
            ? "No pursue-now leads for this snapshot"
            : filterState.viewMode === "strong"
              ? "No strong leads for this snapshot"
              : "No leads match current filters"
      )}</h3>
      <p class="table-empty-state__text">${escapeHtml(
        filterState.search.trim()
          ? `Nothing matches “${filterState.search.trim()}”. Try another term or switch to All view.`
          : filterState.viewMode === "pursue"
            ? "Try Strong or All to see more of the queue, or pick another prepared date."
            : filterState.viewMode === "strong"
              ? "Try All view to see the full queue for this date."
              : "Try Strong or All, or clear your search."
      )}</p>
      <button type="button" class="btn btn-secondary" id="emptyViewAll">Show all leads</button>
    </div>
  </td></tr>`;
  $("#emptyViewAll")?.addEventListener("click", () => applyViewMode("all"));
}

function updateTableScrollHint() {
  const wrap = document.querySelector(".table-wrap");
  if (!wrap) return;
  wrap.classList.toggle("is-scrollable", wrap.scrollWidth > wrap.clientWidth + 2);
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
    showFieldSaved(anchorEl, true);
    if (detailLead && leadKey(detailLead) === leadId) {
      detailLead = { ...detailLead, ...patch };
    }
    syncTableFromLead(lead);
  } catch {
    showFieldSaved(anchorEl, false);
    showToast("Could not save — try again", true);
  }
  renderMetricsFromFiltered();
}

function syncTableFromLead(lead) {
  const lid = leadKey(lead);
  const row = document.querySelector(`tr[data-lead-id="${CSS.escape(lid)}"]`);
  if (!row) return;
  const ownerCell = row.querySelector(".assign-cell");
  if (ownerCell) ownerCell.innerHTML = suggestedOwnerCell(lead);
  const notesCellEl = row.querySelector(".notes-cell");
  if (notesCellEl) notesCellEl.innerHTML = notesCell(lead);
}

async function fetchMauritiusIfNeeded(payload, allowAuto = true) {
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

  setLoading(true, "Loading Mauritius register data…");
  const demo = isDemoCapEnabled();
  const base = `incorporation_date=${encodeURIComponent(date)}&demo=${demo}&tab=${encodeURIComponent(QUEUE_TAB)}`;
  try {
    const res = await fetch(`/api/refresh/mauritius?${base}`, { method: "POST" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showToast(err.detail || "Mauritius data could not be loaded for this date", true);
      return payload;
    }
    const updated = await res.json();
    await loadAvailableDates();
    showToast(`Mauritius register loaded — ${updated.count} leads in view`);
    return updated;
  } catch {
    showToast("Mauritius data could not be loaded for this date", true);
    return payload;
  } finally {
    setLoading(false);
  }
}

async function fetchLeads(refresh = false, allowAutoFetch = true) {
  if (refresh && !operatorRefreshAllowed) {
    showToast(
      "Register data is prepared overnight. Try another date or contact operations.",
      true
    );
    return;
  }
  const date = getCurrentDate();
  const demo = isDemoCapEnabled();
  if (!date) {
    renderMetricsZeroState();
    showTableEmptyState();
    fetchDataStatus();
    return;
  }
  hideQueueLoadError();
  setLoading(true, refresh ? "Loading UK register data…" : "Loading queue…");
  showTableLoadingState();
  const base = `incorporation_date=${encodeURIComponent(date)}&demo=${demo}&tab=${encodeURIComponent(QUEUE_TAB)}`;
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
        return fetchLeads(true, false);
      }
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText);
    }
    let data = await res.json();
    data = await fetchMauritiusIfNeeded(data, allowAutoFetch);
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
    renderTrustStrip(lastDataStatus);
    if (openLeadId) {
      const still = allLeads.find((l) => leadKey(l) === openLeadId);
      if (still) openDetailPanel(openLeadId, true);
      else closeDetailPanel();
    }
    showToast(refresh ? `Refreshed — ${data.count} leads in view` : `Loaded ${data.count} leads`);
  } catch (e) {
    const msg = e.message || "Failed to load";
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

function exportCsv() {
  const rows = sortLeads(getFilteredLeads());
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
  const headers = [
    "company_name",
    "jurisdiction",
    "entity_type",
    "score",
    "priority",
    "prospect_reason",
    "why_summary",
    "incorporation_date",
    "assigned_to",
    "notes",
    "lead_id",
    "source",
  ];
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const lines = [headers.join(","), ...rows.map((r) => headers.map((h) => esc(r[h])).join(","))];
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `arie_leads_${getCurrentDate() || "export"}_${exportScopeSlug()}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
  showToast(`Exported ${rows.length} filtered lead${rows.length === 1 ? "" : "s"}`);
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

  $("#detailCompanyName").textContent = "Lead profile";
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

function renderDetailShell(lead) {
  const addr = (lead.registered_address || lead.address || "").trim();
  const verifyUrl = (lead.verify_url || "").trim();
  const statusVal = lead.status || "New";
  const statusOpts = PANEL_STATUSES.map(
    (s) => `<option value="${escapeHtml(s)}" ${statusVal === s ? "selected" : ""}>${escapeHtml(s)}</option>`
  ).join("");

  $("#detailBody").innerHTML = `
    <section class="intel-section detail-company-header">
      <h3 class="detail-company-title">${escapeHtml(lead.company_name)}</h3>
      <p id="detailSummary" class="detail-summary muted">${escapeHtml(lead.jurisdiction || "—")} · Score ${Number(lead.score) || 0}</p>
      <div class="lead-card-meta">
        ${tierBadge(lead.score)}
        <span class="jurisdiction-badge">${escapeHtml(lead.jurisdiction || "—")}</span>
        <span class="entity-badge">${escapeHtml(lead.entity_type || "—")}</span>
        ${scoreWithBar(lead.score)}
      </div>
      <p class="detail-meta-line"><strong>Incorporated:</strong> ${escapeHtml(lead.incorporation_date || "—")}</p>
      ${addr ? `<p class="detail-meta-line"><strong>Registered address:</strong> ${escapeHtml(addr)}</p>` : ""}
      ${
        verifyUrl
          ? `<a class="btn btn-verify btn-block" href="${escapeHtml(verifyUrl)}" target="_blank" rel="noopener">Verify on ${escapeHtml(verifyLabel(lead))}</a>`
          : ""
      }
    </section>

    ${renderWhyContactHtml(lead)}
    ${renderScoreBreakdownHtml(lead)}
    ${renderClassificationHtml(lead)}

    <section class="intel-section" id="detailOfficersSection">
      <h3>Directors &amp; Officers</h3>
      <p class="muted">Loading…</p>
    </section>

    <section class="intel-section" id="detailPscSection">
      <h3>Persons with Significant Control</h3>
      <p class="muted">Loading…</p>
    </section>

    <section class="intel-section">
      <h3>Notes &amp; status</h3>
      <div class="detail-field">
        <span class="detail-field__label">Suggested owner</span>
        ${suggestedOwnerCell(lead)}
        <p class="owner-suggestion__note">For triage only — not saved as an assignment until claim is available.</p>
      </div>
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
      <h3>AI Brief</h3>
      <div id="detailBriefContent"></div>
    </section>
  `;

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
  const demo = isDemoCapEnabled();
  const officersEl = $("#detailOfficersSection");
  const pscEl = $("#detailPscSection");

  if (isMauritiusLead(lead)) {
    const info = renderEnrichmentInfoBox(MU_DIRECTOR_MSG);
    officersEl.innerHTML = `<h3>Directors &amp; Officers</h3>${info}`;
    pscEl.innerHTML = `<h3>Persons with Significant Control</h3>${info}`;
    return;
  }

  officersEl.innerHTML = `<h3>Directors &amp; Officers</h3><p class="muted">Loading…</p>`;
  pscEl.innerHTML = `<h3>Persons with Significant Control</h3><p class="muted">Loading…</p>`;

  try {
    const refreshParam = refresh ? "&refresh=true" : "";
    const res = await fetch(
      `/api/leads/${encodeURIComponent(lid)}/people?incorporation_date=${encodeURIComponent(date)}&demo=${demo}${refreshParam}`
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
      `/api/leads/${encodeURIComponent(lid)}/brief?incorporation_date=${encodeURIComponent(getCurrentDate())}&demo=${isDemoCapEnabled()}`,
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

function init() {
  $("#reviewHighPriorityBtn")?.addEventListener("click", reviewHighPriorityLeads);
  $("#refreshBtn")?.addEventListener("click", () => fetchLeads(true));
  $("#demoMode")?.addEventListener("change", async () => {
    const demoBox = $("#demoMode");
    if (demoBox) demoBox.dataset.userTouched = "1";
    await loadAvailableDates();
    fetchDataStatus();
    if (!appHasDates) {
      renderMetricsZeroState();
      showTableEmptyState();
      return;
    }
    fetchLeads(false);
  });
  $("#exportBtn").addEventListener("click", exportCsv);

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

  const header = $(".header");
  const tableWrap = document.querySelector(".table-wrap");

  function handleScroll() {
    const scrolled =
      window.scrollY > 60 || (tableWrap && tableWrap.scrollTop > 60);
    header?.classList.toggle("header--compact", scrolled);
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
        return;
      }
      return fetchLeads(false);
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
}

init();
