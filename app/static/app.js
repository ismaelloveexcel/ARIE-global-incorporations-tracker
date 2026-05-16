const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const PANEL_STATUSES = ["New", "Contacted", "Not Interested", "Converted"];
const MU_DIRECTOR_MSG =
  "Director and PSC data is not yet available for Mauritius companies. This will be added when MNS API access is confirmed.";

let team = [];
let allLeads = [];
let activeTab = "direct_clients";
let sortKey = "score";
let sortDir = "desc";
let lastPayload = null;
let hasOpenaiKey = false;
let availableDates = [];
let dateDetails = [];
let currentDate = "";
let openLeadId = null;
let detailLead = null;
let bannerHideTimer = null;

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
  $("#loadingOverlay").hidden = !on;
  $("#refreshBtn").disabled = on;
  if (text) $("#loadingText").textContent = text;
}

function formatRefreshed(iso) {
  if (!iso) return "Not refreshed this session";
  try {
    const d = new Date(iso);
    return `Last refreshed: ${d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`;
  } catch {
    return `Last refreshed: ${iso}`;
  }
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

async function loadMeta() {
  const res = await fetch("/api/meta");
  const data = await res.json();
  team = data.team || [];
  hasOpenaiKey = !!data.has_openai_key;
  const assignedFilter = $("#filterAssigned");
  team.forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    assignedFilter.appendChild(opt);
  });
}

async function loadAvailableDates() {
  const demo = $("#demoMode").checked;
  const res = await fetch(`/api/available-dates?demo=${demo}`);
  const data = await res.json();
  availableDates = data.dates || [];
  dateDetails = data.date_details || [];
  const recommended = data.recommended || availableDates[0] || "";
  currentDate = recommended;
  renderDateSelect();
  updateDateNavButtons();
  return recommended;
}

function dateDetail(date) {
  return dateDetails.find((d) => d.date === date) || { date, uk_count: 0, mauritius_count: 0 };
}

function dateOptionLabel(d) {
  const info = dateDetail(d);
  const uk = info.uk_count ?? 0;
  const mu = info.mauritius_count ?? 0;
  const muLabel = mu > 0 ? String(mu) : "none";
  return `${formatDisplayDate(d)} — UK: ${uk} · MU: ${muLabel}`;
}

function renderDateSelect() {
  const sel = $("#dateSelect");
  sel.innerHTML = "";
  const list = availableDates.length ? availableDates : dateDetails.map((d) => d.date);
  list.forEach((d) => {
    const opt = document.createElement("option");
    opt.value = d;
    opt.textContent = dateOptionLabel(d);
    sel.appendChild(opt);
  });
  if (currentDate && list.includes(currentDate)) {
    sel.value = currentDate;
  } else if (list.length) {
    sel.value = list[0];
    currentDate = list[0];
  }
}

function updateDateNavButtons() {
  const idx = availableDates.indexOf(getCurrentDate());
  $("#datePrev").disabled = idx < 0 || idx >= availableDates.length - 1;
  $("#dateNext").disabled = idx <= 0;
}

function navigateDate(delta) {
  const idx = availableDates.indexOf(getCurrentDate());
  if (idx < 0) return;
  const next = idx - delta;
  if (next < 0 || next >= availableDates.length) return;
  setSelectedDate(availableDates[next]);
}

function setSelectedDate(date) {
  currentDate = date;
  $("#dateSelect").value = date;
  updateDateNavButtons();
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

function renderMetrics(payload) {
  const m = payload.metrics || {};
  const meta = payload.meta || {};
  $("#metrics").innerHTML = `
    <div class="metric-card"><strong>${m.total_leads ?? 0}</strong><span>Total leads</span></div>
    <div class="metric-card accent"><strong>${m.high_priority ?? 0}</strong><span>High priority</span></div>
    <div class="metric-card"><strong>${m.assigned_count ?? 0}</strong><span>Assigned</span></div>
    <div class="metric-card"><strong>${m.unassigned_count ?? 0}</strong><span>Unassigned</span></div>
    <p class="metric-jurisdiction">UK: ${m.uk_count ?? 0} · Mauritius: ${m.mauritius_count ?? 0}</p>
  `;
  $("#lastRefreshed").textContent = formatRefreshed(payload.last_refreshed);
  const tabLabel = activeTab === "introducers" ? "Introducers" : "Direct Clients";
  $("#panelTitle").textContent = tabLabel;
  $("#panelSubtitle").textContent = `${payload.count ?? 0} leads · ${payload.incorporation_date}`;
  $("#ukIntroducerNotice").hidden = activeTab !== "introducers";

  const sourceSub = $("#dataSourceSubtitle");
  if (activeTab === "direct_clients") {
    sourceSub.hidden = false;
    sourceSub.textContent = "UK: top 25 by score · Mauritius: all";
  } else {
    sourceSub.hidden = true;
  }

  $("#mauritiusMissingNotice").hidden = true;
}

let copyCmdTimer = null;

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
  if (banner.show_alerts_link) {
    actions += ` <a class="data-status-link" href="/dev#alerts" target="_blank" rel="noopener">Open Alerts →</a>`;
  }
  if (banner.pipeline_command) {
    const cmd = escapeHtml(banner.pipeline_command);
    actions += ` <span class="data-status-cmd-wrap"><code class="data-status-cmd">${cmd}</code> <button type="button" class="data-status-copy">Copy</button></span>`;
  }

  el.innerHTML = `<p class="data-status-text">${icon} ${escapeHtml(banner.message)}${actions}</p>`;

  const copyBtn = el.querySelector(".data-status-copy");
  if (copyBtn) {
    copyBtn.addEventListener("click", async () => {
      const raw = banner.pipeline_command;
      try {
        await navigator.clipboard.writeText(raw);
        copyBtn.textContent = "Copied ✓";
        clearTimeout(copyCmdTimer);
        copyCmdTimer = setTimeout(() => {
          copyBtn.textContent = "Copy";
        }, 2000);
      } catch {
        showToast("Could not copy", true);
      }
    });
  }

  if (banner.auto_hide_seconds) {
    bannerHideTimer = setTimeout(() => {
      el.hidden = true;
      bannerHideTimer = null;
    }, banner.auto_hide_seconds * 1000);
  }
}

async function fetchDataStatus() {
  const date = getCurrentDate();
  if (!date) return;
  const demo = $("#demoMode").checked;
  try {
    const res = await fetch(
      `/api/data-status?date=${encodeURIComponent(date)}&demo=${demo}`
    );
    if (!res.ok) return;
    const data = await res.json();
    renderDataStatusBanner(data);
  } catch {
    /* banner is non-blocking */
  }
}

function scoreBadge(score) {
  const s = Number(score) || 0;
  let cls = "score-low";
  if (s >= 70) cls = "score-high";
  else if (s >= 40) cls = "score-med";
  return `<span class="score-badge ${cls}">${s}</span>`;
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

function applySortFromControl() {
  const [key, dir] = ($("#filterSort").value || "score-desc").split("-");
  sortKey = key;
  sortDir = dir;
  updateSortHeaders();
}

function getFilteredLeads() {
  const q = ($("#filterSearch").value || "").trim().toLowerCase();
  const priority = $("#filterPriority").value;
  const assigned = $("#filterAssigned").value;
  const jurisdiction = $("#filterJurisdiction").value;

  return allLeads.filter((l) => {
    if (q && !(l.company_name || "").toLowerCase().includes(q)) return false;
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
    if (th.dataset.sort === sortKey) {
      th.classList.add(sortDir === "asc" ? "sorted-asc" : "sorted-desc");
    }
  });
  const sortSelect = $("#filterSort");
  if (sortSelect) {
    const val = `${sortKey}-${sortDir}`;
    if ([...sortSelect.options].some((o) => o.value === val)) {
      sortSelect.value = val;
    }
  }
}

function assignedOptions(lead, selected) {
  const val = selected ?? lead.assigned_to ?? "";
  return team
    .map(
      (t) =>
        `<option value="${escapeHtml(t)}" ${val === t ? "selected" : ""}>${escapeHtml(t)}</option>`
    )
    .join("");
}

function verifyCell(lead) {
  const url = (lead.verify_url || "").trim();
  if (!url) return "—";
  return `<a class="btn btn-verify" href="${escapeHtml(url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Verify</a>`;
}

function renderTable() {
  const body = $("#leadsBody");
  const filtered = sortLeads(getFilteredLeads());

  if (!filtered.length) {
    body.innerHTML = `<tr><td colspan="10" class="empty">No leads match your filters.</td></tr>`;
    return;
  }

  body.innerHTML = filtered
    .map((lead) => {
      const lid = leadKey(lead);
      const selected = openLeadId === lid ? " selected" : "";
      return `
        <tr class="lead-row${selected}" data-lead-id="${escapeHtml(lid)}">
          <td><span class="company-name">${escapeHtml(lead.company_name)}</span></td>
          <td>${escapeHtml(lead.jurisdiction || "—")}</td>
          <td>${escapeHtml(lead.entity_type || "—")}</td>
          <td>${scoreBadge(lead.score)}</td>
          <td>${priorityText(lead.priority)}</td>
          <td>${displaySic(lead)}</td>
          <td>${escapeHtml(lead.incorporation_date || "—")}</td>
          <td class="assign-cell field-with-save">
            <select class="assign-select" data-lead-id="${escapeHtml(lid)}">
              <option value="">—</option>${assignedOptions(lead)}
            </select>
          </td>
          <td>
            <input type="text" class="notes-input" data-lead-id="${escapeHtml(lid)}"
              value="${escapeHtml(lead.notes || "")}" placeholder="Add note…" />
          </td>
          <td>${verifyCell(lead)}</td>
        </tr>`;
    })
    .join("");

  body.querySelectorAll(".lead-row").forEach((row) => {
    row.addEventListener("click", (e) => {
      if (e.target.closest("select, input, a, button")) return;
      openDetailPanel(row.dataset.leadId);
    });
  });

  body.querySelectorAll(".assign-select").forEach((sel) => {
    sel.addEventListener("click", (e) => e.stopPropagation());
    sel.addEventListener("change", () => onAssign(sel.dataset.leadId, { assigned_to: sel.value }, sel));
  });

  body.querySelectorAll(".notes-input").forEach((inp) => {
    inp.addEventListener("click", (e) => e.stopPropagation());
    inp.addEventListener("change", () => onAssign(inp.dataset.leadId, { notes: inp.value }, inp));
  });

  updateSortHeaders();
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
  const sel = row.querySelector(".assign-select");
  if (sel) sel.value = lead.assigned_to || "";
  const notes = row.querySelector(".notes-input");
  if (notes) notes.value = lead.notes || "";
}

function renderMetricsFromFiltered() {
  if (!lastPayload) return;
  const filtered = getFilteredLeads();
  const { uk, mu } = countUkMu(filtered);
  renderMetrics({
    ...lastPayload,
    metrics: {
      total_leads: filtered.length,
      high_priority: filtered.filter((l) => (Number(l.score) || 0) >= 70).length,
      assigned_count: filtered.filter((l) => (l.assigned_to || "").trim()).length,
      unassigned_count: filtered.filter((l) => !(l.assigned_to || "").trim()).length,
      uk_count: uk,
      mauritius_count: mu,
    },
  });
}

async function fetchLeads(refresh = false) {
  const date = getCurrentDate();
  const demo = $("#demoMode").checked;
  if (!date) return;
  setLoading(true, refresh ? "Fetching UK from Companies House…" : "Loading leads…");
  const base = `incorporation_date=${encodeURIComponent(date)}&demo=${demo}&tab=${encodeURIComponent(activeTab)}`;
  const url = `/api/${refresh ? "refresh" : "leads"}?${base}`;
  try {
    let res = await fetch(url, { method: refresh ? "POST" : "GET" });
    if (refresh && res.ok) {
      await loadAvailableDates();
      res = await fetch(`/api/leads?${base}`);
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText);
    }
    const data = await res.json();
    lastPayload = data;
    allLeads = data.leads || [];
    currentDate = data.incorporation_date;
    $("#dateSelect").value = currentDate;
    renderMetrics(data);
    renderTable();
    await fetchDataStatus();
    if (openLeadId) {
      const still = allLeads.find((l) => leadKey(l) === openLeadId);
      if (still) openDetailPanel(openLeadId, true);
      else closeDetailPanel();
    }
    showToast(refresh ? `Refreshed — ${data.count} leads in view` : `Loaded ${data.count} leads`);
  } catch (e) {
    showToast(e.message || "Failed to load", true);
    $("#leadsBody").innerHTML = `<tr><td colspan="10" class="empty">${escapeHtml(e.message)}</td></tr>`;
  } finally {
    setLoading(false);
  }
}

function switchTab(tab) {
  activeTab = tab;
  $$(".tab-btn").forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tab));
  fetchLeads(false);
}

function exportCsv() {
  const rows = sortLeads(getFilteredLeads());
  if (!rows.length) {
    showToast("Nothing to export", true);
    return;
  }
  const headers = [
    "company_name",
    "jurisdiction",
    "entity_type",
    "score",
    "priority",
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
  a.download = `arie-${activeTab}-${getCurrentDate() || "export"}.csv`;
  a.click();
  showToast(`Exported ${rows.length} leads`);
}

/* —— Intelligence panel —— */

function openDetailPanel(leadId, skipAnim = false) {
  const lead = allLeads.find((l) => leadKey(l) === leadId);
  if (!lead) return;
  openLeadId = leadId;
  detailLead = lead;
  $$(".lead-row").forEach((r) => r.classList.toggle("selected", r.dataset.leadId === leadId));

  $("#detailCompanyName").textContent = lead.company_name || "Company";
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
}

function closeDetailPanel() {
  openLeadId = null;
  detailLead = null;
  $$(".lead-row").forEach((r) => r.classList.remove("selected"));
  $("#detailBackdrop").classList.remove("is-open");
  $("#detailPanel").classList.remove("is-open");
  document.body.classList.remove("panel-open");
  setTimeout(() => {
    $("#detailBackdrop").hidden = true;
    $("#detailPanel").hidden = true;
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
      <div class="lead-card-meta">
        <span class="jurisdiction-badge">${escapeHtml(lead.jurisdiction || "—")}</span>
        <span class="entity-badge">${escapeHtml(lead.entity_type || "—")}</span>
        ${scoreBadge(lead.score)}
      </div>
      <p class="detail-meta-line"><strong>Incorporated:</strong> ${escapeHtml(lead.incorporation_date || "—")}</p>
      ${addr ? `<p class="detail-meta-line"><strong>Registered address:</strong> ${escapeHtml(addr)}</p>` : ""}
      ${
        verifyUrl
          ? `<a class="btn btn-verify btn-block" href="${escapeHtml(verifyUrl)}" target="_blank" rel="noopener">Verify on ${escapeHtml(verifyLabel(lead))}</a>`
          : ""
      }
    </section>

    <section class="intel-section" id="detailOfficersSection">
      <h3>Directors &amp; Officers</h3>
      <p class="muted">Loading…</p>
    </section>

    <section class="intel-section" id="detailPscSection">
      <h3>Persons with Significant Control</h3>
      <p class="muted">Loading…</p>
    </section>

    <section class="intel-section">
      <h3>Assignment &amp; Notes</h3>
      <label class="detail-field field-with-save">
        <span>Assigned to</span>
        <select id="detailAssign" class="detail-select">
          <option value="">—</option>${assignedOptions(lead, lead.assigned_to)}
        </select>
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
      <h3>AI Brief</h3>
      <div id="detailBriefContent"></div>
    </section>
  `;

  $("#detailAssign").addEventListener("change", (e) =>
    onAssign(leadKey(lead), { assigned_to: e.target.value }, e.target)
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
  const demo = $("#demoMode").checked;
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
      `/api/leads/${encodeURIComponent(lid)}/brief?incorporation_date=${encodeURIComponent(getCurrentDate())}&demo=${$("#demoMode").checked}`,
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
  $("#refreshBtn").addEventListener("click", () => fetchLeads(true));
  $("#demoMode").addEventListener("change", async () => {
    await loadAvailableDates();
    fetchLeads(false);
  });
  $("#exportBtn").addEventListener("click", exportCsv);

  $("#datePrev").addEventListener("click", () => navigateDate(-1));
  $("#dateNext").addEventListener("click", () => navigateDate(1));
  $("#dateSelect").addEventListener("change", () => setSelectedDate($("#dateSelect").value));

  $("#copyMuCmd").addEventListener("click", () => {
    const cmd = $("#muPipelineCmd").textContent;
    navigator.clipboard.writeText(cmd).then(() => showToast("Command copied"));
  });

  $("#detailClose").addEventListener("click", closeDetailPanel);
  $("#detailBackdrop").addEventListener("click", closeDetailPanel);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && openLeadId) closeDetailPanel();
  });

  $$(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  const rerender = () => {
    renderTable();
    renderMetricsFromFiltered();
  };
  $("#filterSearch").addEventListener("input", rerender);
  $("#filterPriority").addEventListener("change", rerender);
  $("#filterAssigned").addEventListener("change", rerender);
  $("#filterJurisdiction").addEventListener("change", rerender);

  $("#filterSort").addEventListener("change", () => {
    applySortFromControl();
    rerender();
  });

  $$("th.sortable").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (sortKey === key) sortDir = sortDir === "asc" ? "desc" : "asc";
      else {
        sortKey = key;
        sortDir = key === "score" ? "desc" : "asc";
      }
      updateSortHeaders();
      renderTable();
    });
  });

  applySortFromControl();
  loadMeta()
    .then(() => loadAvailableDates())
    .then(() => fetchLeads(false));
}

init();
