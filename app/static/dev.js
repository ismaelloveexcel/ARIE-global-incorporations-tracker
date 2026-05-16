const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

let config = null;

function yesterdayISO() {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

async function loadConfig() {
  const res = await fetch("/api/dev/config");
  config = await res.json();
  renderRoadmap();
  renderPools();
  renderImplLog();
}

async function saveConfig(partial) {
  const res = await fetch("/api/dev/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(partial),
  });
  config = await res.json();
}

function showSection(name) {
  $$(".dev-section").forEach((s) => s.classList.remove("active"));
  $$(".dev-nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.section === name));
  $(`#section-${name}`).classList.add("active");
  const titles = {
    overview: "Overview",
    health: "System Health",
    alerts: "Pipeline Alerts",
    roadmap: "Jurisdiction Roadmap",
    team: "Team & Assignment",
    controls: "Manual Controls",
    log: "Implementation Log",
  };
  $("#devSectionTitle").textContent = titles[name] || name;
  if (name === "health") runHealth();
  if (name === "overview") loadOverview();
  if (name === "alerts") loadAlerts();
}

function formatRunWhen(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toISOString().replace("T", " ").slice(0, 16);
}

function runResultLabel(run) {
  if (!run) return "—";
  if (run.status === "in_progress" || run.status === "queued") return "Running…";
  if (run.conclusion === "success") return "Success";
  if (run.conclusion === "failure") return "Failed";
  if (run.conclusion === "cancelled") return "Cancelled";
  return run.conclusion || run.status || "—";
}

function runResultClass(run) {
  if (!run) return "";
  if (run.conclusion === "success") return "ok";
  if (run.conclusion === "failure") return "error";
  if (run.status === "in_progress" || run.status === "queued") return "warning";
  return "warning";
}

async function loadAlerts() {
  const res = await fetch("/api/dev/pipeline-alerts");
  const data = await res.json();
  const setup = data.setup || {};

  $("#alertsSummary").textContent = setup.summary || "";

  $("#alertsNotifLink").href = data.links?.notification_settings || "#";
  $("#alertsActionsLink").href = data.links?.actions || "#";

  const latest = data.latest;
  const lastOk = data.last_success;
  const lastFail = data.last_failure;
  let banner = "";
  if (!data.api_ok) {
    banner = `<p><strong>Could not load runs from GitHub.</strong> Open Actions manually — the setup steps below still apply.</p>`;
  } else if (latest?.conclusion === "failure") {
    banner = `<p class="banner-fail"><strong>Latest run failed</strong> — ${esc(formatRunWhen(latest.created_at))}. GitHub should email you if notifications are on. <a href="${esc(latest.html_url)}" target="_blank" rel="noopener">View run</a></p>`;
  } else if (latest?.conclusion === "success") {
    banner = `<p class="banner-ok"><strong>Latest run succeeded</strong> — ${esc(formatRunWhen(latest.created_at))}.</p>`;
  } else if (latest) {
    banner = `<p><strong>Latest run:</strong> ${esc(runResultLabel(latest))} (${esc(formatRunWhen(latest.created_at))}).</p>`;
  }
  if (lastOk && lastFail && lastOk.id !== lastFail.id) {
    banner += `<p class="muted">Last success: ${esc(formatRunWhen(lastOk.created_at))} · Last failure: ${esc(formatRunWhen(lastFail.created_at))}</p>`;
  }
  $("#alertStatusBanner").innerHTML = banner;

  $("#alertSetupSteps").innerHTML = (setup.steps || [])
    .map(
      (step, i) => `
    <article class="alert-step">
      <span class="alert-step-num">${i + 1}</span>
      <div>
        <strong>${esc(step.title)}</strong>
        <p>${esc(step.detail)}</p>
        <a href="${esc(step.url)}" target="_blank" rel="noopener">Open in GitHub →</a>
      </div>
    </article>`
    )
    .join("");

  const runs = data.runs || [];
  if (!runs.length) {
    $("#pipelineRunsBody").innerHTML = `<tr><td colspan="5" class="muted">No recent runs found.</td></tr>`;
    return;
  }
  $("#pipelineRunsBody").innerHTML = runs
    .map((run) => {
      const cls = runResultClass(run);
      return `<tr>
        <td>${esc(formatRunWhen(run.created_at))}</td>
        <td>${esc(run.name || data.workflow_name)}</td>
        <td>${esc(run.event || "—")}</td>
        <td><span class="run-pill ${cls}">${esc(runResultLabel(run))}</span></td>
        <td>${run.html_url ? `<a href="${esc(run.html_url)}" target="_blank" rel="noopener">Log</a>` : ""}</td>
      </tr>`;
    })
    .join("");
}

function statusClass(st) {
  if (st === "ok") return "ok";
  if (st === "error") return "error";
  if (st === "pending" || st === "warning") return "warning";
  return "warning";
}

async function runHealth() {
  const date = $("#devDate").value;
  const res = await fetch(`/api/dev/health?incorporation_date=${encodeURIComponent(date)}`);
  const data = await res.json();
  $("#healthGrid").innerHTML = (data.checks || [])
    .map(
      (c) => `
    <article class="health-card ${statusClass(c.status)}">
      <strong>${esc(c.name)}</strong>
      <span>${esc(c.message)}</span>
      ${c.ago ? `<span class="muted">${esc(c.ago)}</span>` : ""}
    </article>`
    )
    .join("");

  const fixes = (data.checks || []).filter((c) => c.fix).map((c) => `<p>${esc(c.fix)}</p>`);
  $("#healthFixes").innerHTML = fixes.join("");
}

async function loadOverview() {
  const date = $("#devDate").value;
  const res = await fetch(`/api/dev/stats?incorporation_date=${encodeURIComponent(date)}&demo=true`);
  const data = await res.json();
  const stats = data.assignment_stats || {};
  let html = `
    <div class="dev-stat"><strong>${data.direct_clients_count ?? 0}</strong><span>Direct Clients</span></div>
    <div class="dev-stat"><strong>${data.introducers_count ?? 0}</strong><span>Introducers</span></div>
    <div class="dev-stat"><strong>${data.unassigned ?? 0}</strong><span>Unassigned</span></div>`;
  Object.entries(stats).forEach(([name, count]) => {
    html += `<div class="dev-stat"><strong>${count}</strong><span>${esc(name)}</span></div>`;
  });
  $("#overviewStats").innerHTML = html;
}

function renderRoadmap() {
  const body = $("#roadmapBody");
  body.innerHTML = (config.roadmap || [])
    .map(
      (row, i) => `
    <tr data-idx="${i}">
      <td contenteditable data-field="jurisdiction">${esc(row.jurisdiction)}</td>
      <td contenteditable data-field="type">${esc(row.type)}</td>
      <td contenteditable data-field="status">${esc(row.status_icon || "")} ${esc(row.status)}</td>
      <td contenteditable data-field="source">${esc(row.source)}</td>
      <td contenteditable data-field="notes">${esc(row.notes)}</td>
    </tr>`
    )
    .join("");

  body.querySelectorAll("td[contenteditable]").forEach((cell) => {
    cell.addEventListener("blur", async () => {
      const tr = cell.closest("tr");
      const idx = parseInt(tr.dataset.idx, 10);
      const field = cell.dataset.field;
      const roadmap = [...config.roadmap];
      let val = cell.textContent.trim();
      if (field === "status") {
        const icons = { Live: "✅", Pending: "🔄", Planned: "📋", Blocked: "❌" };
        for (const [k, icon] of Object.entries(icons)) {
          if (val.includes(k)) {
            roadmap[idx].status = k;
            roadmap[idx].status_icon = icon;
            cell.textContent = `${icon} ${k}`;
            await saveConfig({ roadmap });
            return;
          }
        }
      }
      roadmap[idx][field] = val;
      await saveConfig({ roadmap });
    });
  });
}

function renderPools() {
  const pools = config.assignment_pools || {};
  const render = (el, key) => {
    el.innerHTML = (pools[key] || [])
      .map(
        (name) =>
          `<span class="pool-tag">${esc(name)}<button type="button" data-pool="${key}" data-name="${esc(name)}">×</button></span>`
      )
      .join("");
    el.querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const pool = [...config.assignment_pools[btn.dataset.pool]];
        const idx = pool.indexOf(btn.dataset.name);
        if (idx >= 0) pool.splice(idx, 1);
        config.assignment_pools[btn.dataset.pool] = pool;
        await saveConfig({ assignment_pools: config.assignment_pools });
        renderPools();
      });
    });
  };
  render($("#poolDirect"), "direct_clients");
  render($("#poolIntro"), "introducers");
}

async function addToPool(poolKey, inputId) {
  const name = $(inputId).value.trim();
  if (!name) return;
  const pools = { ...config.assignment_pools };
  pools[poolKey] = [...(pools[poolKey] || []), name];
  $(inputId).value = "";
  await saveConfig({ assignment_pools: pools });
  renderPools();
}

const STATUS_CYCLE = ["Planned", "Pending", "Live", "Blocked"];

function renderImplLog() {
  const log = config.implementation_log || {};
  const phases = [
    ["phase_1", "Phase 1"],
    ["phase_2", "Phase 2"],
    ["phase_3", "Phase 3"],
    ["phase_4", "Phase 4"],
  ];
  $("#implLog").innerHTML = phases
    .map(([key, label]) => {
      const items = log[key] || [];
      return `<div class="impl-phase"><h3>${label}</h3>${items
        .map(
          (item, i) =>
            `<div class="impl-item" data-phase="${key}" data-idx="${i}">
              <span>${item.status_icon || "📋"}</span>
              <span>${esc(item.item)} — <em>${esc(item.status)}</em></span>
            </div>`
        )
        .join("")}</div>`;
    })
    .join("");

  $$(".impl-item").forEach((el) => {
    el.addEventListener("click", async () => {
      const phase = el.dataset.phase;
      const idx = parseInt(el.dataset.idx, 10);
      const items = [...config.implementation_log[phase]];
      const cur = items[idx].status;
      const next = STATUS_CYCLE[(STATUS_CYCLE.indexOf(cur) + 1) % STATUS_CYCLE.length];
      const icons = { Live: "✅", Pending: "🔄", Planned: "📋", Blocked: "❌" };
      items[idx].status = next;
      items[idx].status_icon = icons[next] || "📋";
      config.implementation_log[phase] = items;
      await saveConfig({ implementation_log: config.implementation_log });
      renderImplLog();
    });
  });
}

async function refreshUk() {
  const date = $("#devDate").value;
  $("#pipelineLog").textContent = "Refreshing UK from Companies House…\n";
  const res = await fetch(`/api/dev/refresh/uk?incorporation_date=${encodeURIComponent(date)}&demo=true`, {
    method: "POST",
  });
  const data = await res.json();
  $("#pipelineLog").textContent = `UK refresh complete — ${data.count} leads loaded.\n`;
}

async function refreshMu() {
  const date = $("#devDate").value;
  $("#pipelineLog").textContent = `Running: python main.py --date ${date} --skip-difc\n\n`;
  const res = await fetch(`/api/dev/refresh/mauritius?incorporation_date=${encodeURIComponent(date)}`, {
    method: "POST",
  });
  const data = await res.json();
  $("#pipelineLog").textContent += data.stdout || "";
  if (data.stderr) $("#pipelineLog").textContent += "\n" + data.stderr;
  $("#pipelineLog").textContent += `\nExit code: ${data.returncode}\n`;
}

function init() {
  $("#devDate").value = yesterdayISO();
  $("#devDate").addEventListener("change", () => {
    if ($("#section-overview").classList.contains("active")) loadOverview();
  });

  $$(".dev-nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => showSection(btn.dataset.section));
  });

  $("#runHealthBtn").addEventListener("click", runHealth);
  $("#refreshUkBtn").addEventListener("click", refreshUk);
  $("#refreshMuBtn").addEventListener("click", refreshMu);
  $("#refreshAlertsBtn").addEventListener("click", loadAlerts);

  $$(".pool-add .dev-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const pool = btn.dataset.pool;
      addToPool(pool, pool === "direct_clients" ? "#addDirect" : "#addIntro");
    });
  });

  loadConfig().then(() => {
    showSection("overview");
  });
}

init();
