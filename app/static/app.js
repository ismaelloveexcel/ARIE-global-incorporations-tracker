const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const LS_KEY = "arie_lead_assignments";

let team = [];
let allLeads = [];
let sortKey = "score";
let sortDir = "desc";
let lastPayload = null;
let activePreset = null;
let filterFintechOnly = false;
let selectedCompany = null;
let workflowStatuses = [];
let hasOpenAiKey = false;

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

function normalizeTags(lead) {
  if (Array.isArray(lead.why_tags)) return lead.why_tags;
  return [];
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

function setLoading(on) {
  $("#loadingOverlay").hidden = !on;
  $("#refreshBtn").disabled = on;
}

function loadLocalAssignments() {
  try {
    return JSON.parse(localStorage.getItem(LS_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveLocalAssignment(companyNumber, data) {
  const all = loadLocalAssignments();
  all[companyNumber] = { ...all[companyNumber], ...data };
  localStorage.setItem(LS_KEY, JSON.stringify(all));
}

function mergeLocalAssignments(leads) {
  const local = loadLocalAssignments();
  return leads.map((l) => {
    const extra = local[l.company_number];
    if (!extra) return l;
    return {
      ...l,
      assigned_to: l.assigned_to || extra.assigned_to || "",
      notes: l.notes || extra.notes || "",
      status: l.status || extra.status || "Not contacted",
      contacted_at: l.contacted_at || extra.contacted_at || "",
      follow_up_at: l.follow_up_at || extra.follow_up_at || "",
    };
  });
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

function jurisdictionStatusLabel(status) {
  const map = { live: "Live", pending: "API onboarding", planned: "Evaluation" };
  return map[status] || status;
}

async function loadMeta() {
  const res = await fetch("/api/meta");
  const data = await res.json();
  team = data.team || [];
  workflowStatuses = data.workflow_statuses || [];
  hasOpenAiKey = !!data.has_openai_key;
  $("#positioningBar").textContent = data.positioning || "";

  $("#roadmapGrid").innerHTML = (data.jurisdictions || [])
    .map(
      (j) => `
      <article class="roadmap-card ${j.status}">
        <span class="roadmap-code">${escapeHtml(j.code)}</span>
        <h3>${escapeHtml(j.name)}</h3>
        <p class="roadmap-status">${escapeHtml(jurisdictionStatusLabel(j.status))}</p>
        <p class="roadmap-source">${escapeHtml(j.source)}</p>
      </article>`
    )
    .join("");

  const assignedFilter = $("#filterAssigned");
  team.forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    assignedFilter.appendChild(opt);
  });
}

function renderMetrics(payload) {
  const m = payload.metrics || {};
  const unassigned = Math.max(0, (m.total_companies ?? 0) - (m.assigned_leads ?? 0));
  $("#metrics").innerHTML = `
    <div class="metric-card"><strong>${m.total_companies ?? 0}</strong><span>In view</span></div>
    <div class="metric-card accent"><strong>${m.high_priority ?? 0}</strong><span>High priority</span></div>
    <div class="metric-card"><strong>${unassigned}</strong><span>Unassigned</span></div>
  `;

  $("#lastRefreshed").textContent = formatRefreshed(payload.last_refreshed);
  const sub = payload.demo
    ? `Top ${payload.count} by score (demo) · ${payload.incorporation_date}`
    : `${payload.count} leads · ${payload.incorporation_date}`;
  $("#panelSubtitle").textContent = sub;
}

function priorityBadge(priority) {
  const p = priority || "Low";
  const cls = p === "High" ? "badge-high" : p === "Medium" ? "badge-medium" : "badge-low";
  return `<span class="badge ${cls}">${escapeHtml(p)}</span>`;
}

function leadBadge(leadType) {
  const t = (leadType || "direct").toLowerCase();
  const cls = t === "introducer" ? "badge-lead-introducer" : "badge-lead-direct";
  return `<span class="badge ${cls}">${escapeHtml(t)}</span>`;
}

function scoreCell(score, isTop) {
  const s = Number(score) || 0;
  const star = isTop ? '<span class="top-lead" title="Top lead">★</span>' : "";
  return `
    <div class="score-wrap">${star}<span class="score-num">${s}</span>
    <div class="score-bar" aria-hidden="true"><div class="score-fill" style="width:${Math.min(s, 100)}%"></div></div>
    </div>`;
}

function whyTagsHtml(lead) {
  const tags = normalizeTags(lead);
  if (!tags.length) return `<span class="placeholder">${escapeHtml(lead.why_summary || "—")}</span>`;
  return tags.map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("");
}

function getFilteredLeads() {
  const q = ($("#filterSearch").value || "").trim().toLowerCase();
  const minScore = parseFloat($("#filterMinScore").value);
  const priority = $("#filterPriority").value;
  const leadType = $("#filterLeadType").value;
  const assigned = $("#filterAssigned").value;

  return allLeads.filter((l) => {
    if (q && !(l.company_name || "").toLowerCase().includes(q)) return false;
    if (!Number.isNaN(minScore) && $("#filterMinScore").value !== "" && (Number(l.score) || 0) < minScore)
      return false;
    if (priority && l.priority !== priority) return false;
    if (leadType && (l.lead_type || "").toLowerCase() !== leadType) return false;
    if (assigned === "__unassigned__" && (l.assigned_to || "").trim()) return false;
    if (assigned && assigned !== "__unassigned__" && l.assigned_to !== assigned) return false;
    if (filterFintechOnly && !l.is_fintech_payment) return false;
    return true;
  });
}

function sortLeads(rows) {
  const key = sortKey;
  const dir = sortDir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    let av = a[key];
    let bv = b[key];
    if (key === "score" || key === "incorporation_age_days") {
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
}

function sourceBadge(kind) {
  const map = {
    verified: { label: "VERIFIED", cls: "badge-verified" },
    ai: { label: "AI GENERATED", cls: "badge-ai" },
    researched: { label: "RESEARCHED", cls: "badge-researched" },
    unverified: { label: "UNVERIFIED", cls: "badge-unverified" },
    pattern: { label: "PATTERN MATCH", cls: "badge-pattern" },
  };
  const b = map[kind] || map.unverified;
  return `<span class="source-badge ${b.cls}">${b.label}</span>`;
}

function parseListField(val) {
  if (Array.isArray(val)) return val;
  if (!val || typeof val !== "string") return [];
  try {
    const parsed = JSON.parse(val);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return val.split("|").map((s) => s.trim()).filter(Boolean);
  }
}

function signalListHtml(items, type) {
  const list = parseListField(items);
  if (!list.length) return "";
  return `<ul class="signal-list signal-${type}">${list.map((i) => `<li>${escapeHtml(i)}</li>`).join("")}</ul>`;
}

function renderSignalStrip(strengths, cautions) {
  const s = signalListHtml(strengths, "strength");
  const c = signalListHtml(cautions, "caution");
  if (!s && !c) return `<p class="muted">Signals appear after registry data loads.</p>`;
  return `${s}${c}`;
}

function directorProfileLine(profile) {
  if (!profile) return "";
  const parts = [];
  const active = profile.active_appointments ?? 0;
  const dissolved = profile.dissolved_appointments ?? 0;
  parts.push(`${active} active`);
  if (dissolved) parts.push(`${dissolved} dissolved`);
  if (profile.first_appointment_year) parts.push(`since ${profile.first_appointment_year}`);
  if (profile.multiple_current_companies) parts.push("multi-entity");
  return parts.join(" · ");
}

function renderOfficerRow(o) {
  const stats = directorProfileLine(o.director_profile);
  const statsHtml = stats
    ? `<span class="director-stats">${escapeHtml(stats)} ${sourceBadge("verified")}</span>`
    : "";
  return `<li>
    <strong>${escapeHtml(o.name)}</strong>
    <span class="muted"> · ${escapeHtml(o.role || "officer")}</span>
    ${statsHtml ? `<br>${statsHtml}` : ""}
  </li>`;
}

function buildDetailHtml(lead, tags, assignedOpts, statusOpts) {
  return `
    <article class="lead-card">
      <header class="lead-card-head">
        <div class="lead-card-meta">
          <span class="lead-score">${escapeHtml(String(lead.score))}</span>
          ${priorityBadge(lead.priority)}
          ${leadBadge(lead.lead_type)}
        </div>
        <p class="lead-why">${escapeHtml(lead.why_summary || "")}</p>
        ${tags.length ? `<div class="detail-tags">${tags.map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("")}</div>` : ""}
      </header>

      <section class="lead-block" aria-label="Signals">
        <div id="signalStrip" class="signal-strip">${renderSignalStrip(lead.strengths, lead.cautions)}</div>
      </section>

      <section class="lead-block verified-block" aria-label="Verified registry">
        <p class="block-label">Verified · Companies House</p>
        <p class="registry-line">
          ${escapeHtml(lead.company_number)} · ${escapeHtml(lead.incorporation_date)}
          · ${escapeHtml(lead.incorporation_age_label || "")} · ${escapeHtml(lead.sic_codes || "—")}
        </p>
        <a class="btn btn-verify btn-block" href="${escapeHtml(lead.verify_url)}" target="_blank" rel="noopener">Open register record</a>
        <div id="peopleSection" class="people-loading muted">Loading officers…</div>
      </section>

      <details class="lead-block ai-block">
        <summary>Outreach brief ${sourceBadge("ai")}</summary>
        <div class="ai-block-body">
          <div id="briefSection"></div>
          <button type="button" class="btn btn-secondary btn-sm" id="generateBriefBtn" ${hasOpenAiKey ? "" : "disabled title='Add OPENAI_API_KEY to .env'"}>Generate brief</button>
        </div>
      </details>

      <section class="lead-block workflow-block" aria-label="Workflow">
        <p class="block-label">Workflow</p>
        <div class="workflow-grid">
          <label class="detail-field"><span>Status</span>
            <select class="assign-select" id="detailStatus">${statusOpts}</select>
          </label>
          <label class="detail-field"><span>Assigned</span>
            <select class="assign-select" id="detailAssign"><option value="">—</option>${assignedOpts}</select>
          </label>
          <label class="detail-field"><span>Follow-up</span>
            <input type="date" id="detailFollowUp" value="${escapeHtml((lead.follow_up_at || "").slice(0, 10))}" />
          </label>
        </div>
        <label class="detail-field"><span>Notes</span>
          <textarea class="notes-area" id="detailNotes" rows="2">${escapeHtml(lead.notes || "")}</textarea>
        </label>
      </section>
    </article>
  `;
}

function openDetail(lead) {
  selectedCompany = lead.company_number;
  const tags = normalizeTags(lead);
  const assignedOpts = team
    .map(
      (t) =>
        `<option value="${escapeHtml(t)}" ${lead.assigned_to === t ? "selected" : ""}>${escapeHtml(t)}</option>`
    )
    .join("");
  const statusOpts = (workflowStatuses.length ? workflowStatuses : ["Not contacted", "Contacted", "Follow-up", "Interested", "Onboarding", "Not fit"])
    .map(
      (s) =>
        `<option value="${escapeHtml(s)}" ${(lead.status || "Not contacted") === s ? "selected" : ""}>${escapeHtml(s)}</option>`
    )
    .join("");

  $("#detailTitle").textContent = lead.company_name || "Lead detail";
  $("#detailBody").innerHTML = buildDetailHtml(lead, tags, assignedOpts, statusOpts);

  $("#detailAssign").addEventListener("change", (e) => onAssign(lead.company_number, { assigned_to: e.target.value }));
  $("#detailNotes").addEventListener("change", (e) => onAssign(lead.company_number, { notes: e.target.value }));
  $("#detailStatus").addEventListener("change", (e) => {
    const patch = { status: e.target.value };
    if (e.target.value === "Contacted") patch.contacted_at = new Date().toISOString();
    onAssign(lead.company_number, patch);
  });
  $("#detailFollowUp").addEventListener("change", (e) =>
    onAssign(lead.company_number, { follow_up_at: e.target.value ? `${e.target.value}T00:00:00` : "" })
  );
  $("#generateBriefBtn")?.addEventListener("click", () => generateLeadBrief(lead));
  loadCachedBrief(lead.company_number);
  loadLeadPeople(lead);

  $("#detailPanel").hidden = false;
  $("#detailBackdrop").hidden = false;
  document.body.classList.add("panel-open");
}

async function loadLeadPeople(lead) {
  const box = $("#peopleSection");
  if (!box) return;
  box.innerHTML = `<p class="muted">Loading from Companies House…</p>`;
  try {
    const q = lead.incorporation_date ? `?incorporation_date=${encodeURIComponent(lead.incorporation_date)}` : "";
    const res = await fetch(`/api/leads/${encodeURIComponent(lead.company_number)}/people${q}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText);
    }
    const data = await res.json();
    if (data.strengths || data.cautions) {
      lead.strengths = data.strengths;
      lead.cautions = data.cautions;
      $("#signalStrip").innerHTML = renderSignalStrip(data.strengths, data.cautions);
    }
    const officers = data.officers || [];
    const psc = data.psc || [];
    const officersHtml = officers.length
      ? `<ul class="people-list">${officers.map(renderOfficerRow).join("")}</ul>`
      : `<p class="muted">No officers listed.</p>`;
    const pscHtml = psc.length
      ? `<ul class="people-list people-list-compact">${psc.map((p) => `<li><strong>${escapeHtml(p.name)}</strong> <span class="muted">${escapeHtml(p.natures_of_control || "")}</span></li>`).join("")}</ul>`
      : "";
    box.innerHTML = `${officersHtml}${psc.length ? `<p class="block-label" style="margin-top:0.75rem">PSC</p>${pscHtml}` : ""}`;
  } catch (err) {
    box.innerHTML = `<p class="muted">Could not load people: ${escapeHtml(err.message)}</p>`;
    showToast(err.message, true);
  }
}

function renderBrief(brief) {
  const el = $("#briefSection");
  if (!brief) {
    el.innerHTML = "";
    return;
  }
  const strengths = (brief.strengths || []).map((s) => escapeHtml(s)).join("; ") || "—";
  const cautions = (brief.cautions || []).map((s) => escapeHtml(s)).join("; ") || "—";
  el.innerHTML = `
    <div class="brief-block">
      <p class="brief-hook">${escapeHtml(brief.outreach_angle || brief.why_arie || "")}</p>
      <p class="brief-line">${escapeHtml(brief.opening_line || "")}</p>
      <details class="brief-more">
        <summary>Full brief</summary>
        <p><strong>Business</strong> ${escapeHtml(brief.business_summary || "")}</p>
        <p><strong>Why Arie</strong> ${escapeHtml(brief.why_arie || "")}</p>
        <p><strong>Likely need</strong> ${escapeHtml(brief.likely_need || "")}</p>
        <p><strong>Strengths</strong> ${strengths}</p>
        <p><strong>Caution</strong> ${cautions}</p>
      </details>
      <p class="brief-disclaimer">${escapeHtml(brief.disclaimer || "")}</p>
    </div>
  `;
}

async function loadCachedBrief(companyNumber) {
  try {
    const res = await fetch(`/api/leads/${encodeURIComponent(companyNumber)}/brief`);
    if (res.ok) {
      const data = await res.json();
      renderBrief(data.brief);
    }
  } catch {
    /* no cached brief */
  }
}

async function generateLeadBrief(lead) {
  const btn = $("#generateBriefBtn");
  if (!btn) return;
  const aiBlock = document.querySelector(".ai-block");
  if (aiBlock && !aiBlock.open) aiBlock.open = true;
  btn.disabled = true;
  $("#briefSection").innerHTML = `<p class="muted">Generating brief…</p>`;
  try {
    const q = lead.incorporation_date ? `?incorporation_date=${encodeURIComponent(lead.incorporation_date)}` : "";
    const res = await fetch(`/api/leads/${encodeURIComponent(lead.company_number)}/brief${q}`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Brief failed");
    renderBrief(data.brief);
    showToast("Brief generated");
  } catch (err) {
    $("#briefSection").innerHTML = "";
    showToast(err.message, true);
  } finally {
    btn.disabled = false;
  }
}

function closeDetail() {
  $("#detailPanel").hidden = true;
  $("#detailBackdrop").hidden = true;
  document.body.classList.remove("panel-open");
  selectedCompany = null;
}

function renderTable() {
  const body = $("#leadsBody");
  const filtered = sortLeads(getFilteredLeads());

  if (!filtered.length) {
    body.innerHTML = `<tr><td colspan="8" class="empty">No leads match your filters.</td></tr>`;
    return;
  }

  body.innerHTML = filtered
    .map((lead, idx) => {
      const score = Number(lead.score) || 0;
      const isTop = idx < 3 && sortKey === "score" && sortDir === "desc";
      const assignedOpts = team
        .map(
          (t) =>
            `<option value="${escapeHtml(t)}" ${lead.assigned_to === t ? "selected" : ""}>${escapeHtml(t)}</option>`
        )
        .join("");
      const verify = lead.verify_url
        ? `<a class="btn btn-verify" href="${escapeHtml(lead.verify_url)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">Verify</a>`
        : "—";

      return `
        <tr class="lead-row ${selectedCompany === lead.company_number ? "selected" : ""}" data-company="${escapeHtml(lead.company_number)}">
          <td>${scoreCell(score, isTop)}</td>
          <td>${priorityBadge(lead.priority)}</td>
          <td><span class="company-name">${escapeHtml(lead.company_name)}</span></td>
          <td><span class="age-pill">${escapeHtml(lead.incorporation_age_label || "—")}</span></td>
          <td class="why-cell">${whyTagsHtml(lead)}</td>
          <td>${leadBadge(lead.lead_type)}</td>
          <td>${verify}</td>
          <td>
            <select class="assign-select" data-company="${escapeHtml(lead.company_number)}" onclick="event.stopPropagation()">
              <option value="">—</option>${assignedOpts}
            </select>
          </td>
        </tr>`;
    })
    .join("");

  body.querySelectorAll(".lead-row").forEach((row) => {
    row.addEventListener("click", () => {
      const lead = allLeads.find((l) => l.company_number === row.dataset.company);
      if (lead) openDetail(lead);
    });
  });

  body.querySelectorAll(".assign-select").forEach((sel) => {
    sel.addEventListener("change", (e) => {
      e.stopPropagation();
      onAssign(sel.dataset.company, { assigned_to: sel.value });
    });
  });

  updateSortHeaders();
}

function renderMetricsFromLeads() {
  if (!lastPayload) return;
  const filtered = getFilteredLeads();
  renderMetrics({
    ...lastPayload,
    metrics: {
      total_companies: filtered.length,
      high_priority: filtered.filter((l) => l.priority === "High").length,
      fintech_payment_leads: filtered.filter((l) => l.is_fintech_payment).length,
      assigned_leads: filtered.filter((l) => (l.assigned_to || "").trim()).length,
    },
  });
}

async function onAssign(companyNumber, patch) {
  const lead = allLeads.find((l) => l.company_number === companyNumber);
  if (!lead) return;
  if (patch.assigned_to !== undefined) lead.assigned_to = patch.assigned_to;
  if (patch.notes !== undefined) lead.notes = patch.notes;
  if (patch.status !== undefined) lead.status = patch.status;
  if (patch.contacted_at !== undefined) lead.contacted_at = patch.contacted_at;
  if (patch.follow_up_at !== undefined) lead.follow_up_at = patch.follow_up_at;
  saveLocalAssignment(companyNumber, {
    assigned_to: lead.assigned_to,
    notes: lead.notes,
    status: lead.status,
    contacted_at: lead.contacted_at,
    follow_up_at: lead.follow_up_at,
  });
  try {
    const res = await fetch(`/api/leads/${encodeURIComponent(companyNumber)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error("Server save failed");
  } catch {
    /* local backup ok */
  }
  renderMetricsFromLeads();
  renderTable();
  if (selectedCompany === companyNumber) openDetail(lead);
}

function applyPreset(preset) {
  activePreset = preset === "clear" ? null : preset;
  filterFintechOnly = preset === "fintech";
  $$(".chip").forEach((c) => c.classList.toggle("active", c.dataset.preset === preset));
  $("#filterSearch").value = "";
  $("#filterMinScore").value = "";
  $("#filterPriority").value = "";
  $("#filterLeadType").value = "";
  $("#filterAssigned").value = "";

  if (preset === "high") $("#filterPriority").value = "High";
  else if (preset === "introducer") $("#filterLeadType").value = "introducer";
  else if (preset === "unassigned") $("#filterAssigned").value = "__unassigned__";
  else if (preset === "clear") filterFintechOnly = false;

  renderTable();
  renderMetricsFromLeads();
}

function exportCsv() {
  const rows = sortLeads(getFilteredLeads());
  if (!rows.length) {
    showToast("Nothing to export", true);
    return;
  }
  const headers = [
    "company_name",
    "company_number",
    "incorporation_date",
    "incorporation_age_label",
    "score",
    "priority",
    "why_summary",
    "why_tags",
    "lead_type",
    "assigned_to",
    "sic_codes",
    "verify_url",
    "website_domain",
    "notes",
  ];
  const esc = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const lines = [
    headers.join(","),
    ...rows.map((r) =>
      headers
        .map((h) => {
          if (h === "why_tags") return esc((normalizeTags(r) || []).join("; "));
          return esc(r[h]);
        })
        .join(",")
    ),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `arie-leads-${$("#dateInput").value || "export"}.csv`;
  a.click();
  showToast(`Exported ${rows.length} leads`);
}

async function fetchLeads(refresh = false) {
  const date = $("#dateInput").value;
  const demo = $("#demoMode").checked;
  setLoading(refresh);
  const url = `/api/${refresh ? "refresh" : "leads"}?incorporation_date=${encodeURIComponent(date)}&demo=${demo}`;
  try {
    const res = await fetch(url, { method: refresh ? "POST" : "GET" });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || res.statusText);
    }
    const data = await res.json();
    lastPayload = data;
    allLeads = mergeLocalAssignments(data.leads || []);
    renderMetrics(data);
    renderTable();
    showToast(refresh ? `Loaded ${data.count} companies from Companies House` : `Showing ${data.count} companies`);
  } catch (e) {
    showToast(e.message || "Failed to load", true);
    $("#leadsBody").innerHTML = `<tr><td colspan="8" class="empty">${escapeHtml(e.message)}</td></tr>`;
  } finally {
    setLoading(false);
  }
}

function init() {
  $("#dateInput").value = yesterdayISO();
  $("#refreshBtn").addEventListener("click", () => fetchLeads(true));
  $("#dateInput").addEventListener("change", () => fetchLeads(false));
  $("#demoMode").addEventListener("change", () => fetchLeads(false));
  $("#exportBtn").addEventListener("click", exportCsv);
  $("#detailClose").addEventListener("click", closeDetail);
  $("#detailBackdrop").addEventListener("click", closeDetail);

  const rerender = () => {
    renderTable();
    renderMetricsFromLeads();
  };
  $("#filterSearch").addEventListener("input", rerender);
  $("#filterMinScore").addEventListener("input", rerender);
  $("#filterPriority").addEventListener("change", rerender);
  $("#filterLeadType").addEventListener("change", rerender);
  $("#filterAssigned").addEventListener("change", rerender);

  $$(".chip").forEach((chip) => {
    chip.addEventListener("click", () => applyPreset(chip.dataset.preset));
  });

  $$("th.sortable").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (sortKey === key) sortDir = sortDir === "asc" ? "desc" : "asc";
      else {
        sortKey = key;
        sortDir = key === "score" || key === "incorporation_age_days" ? "desc" : "asc";
      }
      renderTable();
    });
  });

  loadMeta().then(() => fetchLeads(false));
}

init();

