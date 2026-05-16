const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let team = [];
let allLeads = [];
let activeTab = "direct_clients";
let sortKey = "score";
let sortDir = "desc";
let lastPayload = null;

function yesterdayISO() {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
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

async function loadMeta() {
  const res = await fetch("/api/meta");
  const data = await res.json();
  team = data.team || [];
  const assignedFilter = $("#filterAssigned");
  team.forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    assignedFilter.appendChild(opt);
  });
}

function countUkMu(rows) {
  let uk = 0;
  let mu = 0;
  for (const r of rows) {
    const source = (r.source || "").toLowerCase();
    const jurisdiction = (r.jurisdiction || "").trim();
    if (source === "mauritius_mns" || jurisdiction === "Mauritius") mu += 1;
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

  const muNotice = $("#mauritiusMissingNotice");
  if (meta.mauritius_export_missing) {
    muNotice.textContent = `⚠ Mauritius data not available for ${payload.incorporation_date} — run the pipeline for this date to include Mauritius leads`;
    muNotice.hidden = false;
  } else {
    muNotice.hidden = true;
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
  if ((lead.source || "").toLowerCase() === "mauritius_mns") return "—";
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

function assignedOptions(lead) {
  return team
    .map(
      (t) =>
        `<option value="${escapeHtml(t)}" ${lead.assigned_to === t ? "selected" : ""}>${escapeHtml(t)}</option>`
    )
    .join("");
}

function verifyCell(lead) {
  const url = (lead.verify_url || "").trim();
  if (!url) return "—";
  return `<a class="btn btn-verify" href="${escapeHtml(url)}" target="_blank" rel="noopener">Verify</a>`;
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
      const lid = lead.lead_id || lead.company_number;
      return `
        <tr data-lead-id="${escapeHtml(lid)}">
          <td><span class="company-name">${escapeHtml(lead.company_name)}</span></td>
          <td>${escapeHtml(lead.jurisdiction || "—")}</td>
          <td>${escapeHtml(lead.entity_type || "—")}</td>
          <td>${scoreBadge(lead.score)}</td>
          <td>${priorityText(lead.priority)}</td>
          <td>${displaySic(lead)}</td>
          <td>${escapeHtml(lead.incorporation_date || "—")}</td>
          <td class="assign-cell">
            <select class="assign-select" data-lead-id="${escapeHtml(lid)}">
              <option value="">—</option>${assignedOptions(lead)}
            </select>
            <span class="saved-indicator" data-for="${escapeHtml(lid)}" hidden>Saved ✓</span>
          </td>
          <td>
            <input type="text" class="notes-input" data-lead-id="${escapeHtml(lid)}"
              value="${escapeHtml(lead.notes || "")}" placeholder="Add note…" />
          </td>
          <td>${verifyCell(lead)}</td>
        </tr>`;
    })
    .join("");

  body.querySelectorAll(".assign-select").forEach((sel) => {
    sel.addEventListener("change", () => onAssign(sel.dataset.leadId, { assigned_to: sel.value }, sel));
  });

  body.querySelectorAll(".notes-input").forEach((inp) => {
    inp.addEventListener("change", () => onAssign(inp.dataset.leadId, { notes: inp.value }));
  });

  updateSortHeaders();
}

function showSaved(leadId) {
  const el = document.querySelector(`.saved-indicator[data-for="${CSS.escape(leadId)}"]`);
  if (!el) return;
  el.hidden = false;
  clearTimeout(el._t);
  el._t = setTimeout(() => {
    el.hidden = true;
  }, 2000);
}

async function onAssign(leadId, patch, selectEl) {
  const lead = allLeads.find((l) => (l.lead_id || l.company_number) === leadId);
  if (!lead) return;
  if (patch.assigned_to !== undefined) lead.assigned_to = patch.assigned_to;
  if (patch.notes !== undefined) lead.notes = patch.notes;

  try {
    const res = await fetch(`/api/leads/${encodeURIComponent(leadId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error("Save failed");
    if (patch.assigned_to !== undefined) showSaved(leadId);
  } catch {
    showToast("Could not save — try again", true);
  }
  renderMetricsFromFiltered();
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
  const date = $("#dateInput").value;
  const demo = $("#demoMode").checked;
  setLoading(true, refresh ? "Fetching UK from Companies House…" : "Loading leads…");
  const base = `incorporation_date=${encodeURIComponent(date)}&demo=${demo}&tab=${encodeURIComponent(activeTab)}`;
  const url = `/api/${refresh ? "refresh" : "leads"}?${base}`;
  try {
    let res = await fetch(url, { method: refresh ? "POST" : "GET" });
    if (refresh && res.ok) {
      res = await fetch(`/api/leads?${base}`);
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText);
    }
    const data = await res.json();
    lastPayload = data;
    allLeads = data.leads || [];
    renderMetrics(data);
    renderTable();
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
  a.download = `arie-${activeTab}-${$("#dateInput").value || "export"}.csv`;
  a.click();
  showToast(`Exported ${rows.length} leads`);
}

function init() {
  $("#dateInput").value = yesterdayISO();
  $("#refreshBtn").addEventListener("click", () => fetchLeads(true));
  $("#dateInput").addEventListener("change", () => fetchLeads(false));
  $("#demoMode").addEventListener("change", () => fetchLeads(false));
  $("#exportBtn").addEventListener("click", exportCsv);

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
  loadMeta().then(() => fetchLeads(false));
}

init();
