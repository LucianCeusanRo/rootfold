/* Rootfold operator console — vanilla JS, no build step. */
(() => {
  const TOKEN_KEY = "rootfold_token";
  const CHECKS = [
    "Ping / ICMP to the far end",
    "Checked the maintenance calendar",
    "Looked at recent changes",
    "Traceroute / path check",
    "Customer or vendor ticket opened",
  ];
  const LAYOUT = {
    "bcu-dc": [48, 40],
    "bcu-pop": [48, 52],
    "rmn": [62, 32],
    "pnt": [72, 22],
    "bcz": [82, 14],
    "ons": [38, 64],
    "drm": [24, 58],
    "cms": [14, 50],
    "toc": [28, 76],
    "adj": [46, 80],
    "fcs": [58, 90],
  };

  const state = {
    token: localStorage.getItem(TOKEN_KEY),
    me: null,
    route: location.hash || "#/incidents",
    incidents: [],
    filter: "open",
    pending: null,
    error: "",
    notice: "",
    clock: "",
  };

  function $(sel, root = document) { return root.querySelector(sel); }

  async function api(path, opts = {}) {
    const headers = { ...(opts.headers || {}) };
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    if (opts.body && typeof opts.body === "object" && !(opts.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
      opts = { ...opts, body: JSON.stringify(opts.body) };
    }
    const res = await fetch(path, { ...opts, headers });
    if (res.status === 401) {
      logout(false);
      throw new Error("Please log in");
    }
    const text = await res.text();
    let data = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = text; }
    if (!res.ok) {
      const detail = data && data.detail;
      const msg = typeof detail === "string" ? detail
        : detail && detail.message ? detail.message
        : `HTTP ${res.status}`;
      const err = new Error(msg);
      err.status = res.status;
      err.detail = detail;
      throw err;
    }
    return data;
  }

  function logout(redirect = true) {
    state.token = null;
    state.me = null;
    localStorage.removeItem(TOKEN_KEY);
    if (redirect) location.hash = "#/login";
    render();
  }

  async function login(username, password) {
    const data = await api("/api/auth/login", { method: "POST", body: { username, password } });
    state.token = data.access_token;
    localStorage.setItem(TOKEN_KEY, state.token);
    state.me = await api("/api/auth/me");
    const sites = await api("/api/topology/sites");
    if (!sites.length) await api("/api/topology/import-example", { method: "POST" });
    await refreshPending();
    location.hash = "#/incidents";
  }

  function pill(text, extra) {
    const cls = (extra || String(text).toLowerCase()).replace(/\s+/g, "_");
    return `<span class="pill ${cls}">${esc(text)}</span>`;
  }
  function esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }
  function when(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    return d.toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
  }

  function layout() {
    const pending = state.pending
      ? `<a class="tag warn" data-testid="pending-handover" href="#/handover">${esc(state.pending.public_ref)} needs ack</a>`
      : "";
    return `
      <div class="app">
        <header class="topbar">
          <div class="brand">ROOT<span>FOLD</span></div>
          <span class="tag">Lab</span>
          ${pending}
          <nav>
            <a href="#/incidents" class="${active('#/incidents')}" data-testid="nav-incidents">Incidents</a>
            <a href="#/topology" class="${active('#/topology')}" data-testid="nav-topology">Topology</a>
            <a href="#/handover" class="${active('#/handover')}" data-testid="nav-handover">Handover</a>
            <a href="#/reports" class="${active('#/reports')}" data-testid="nav-reports">Reports</a>
            <a href="#/lab" class="${active('#/lab')}" data-testid="nav-lab">Lab</a>
          </nav>
          <div class="spacer"></div>
          <div class="clock" data-testid="clock">${esc(state.clock)}</div>
          <div class="who">${esc(state.me?.username || "")}</div>
          <button class="btn ghost" type="button" id="btn-logout">Log out</button>
        </header>
        <div class="shell"><main class="main" id="main"></main></div>
        <nav class="bottom-nav">
          <a href="#/incidents" class="${active('#/incidents')}">Incidents</a>
          <a href="#/topology" class="${active('#/topology')}">Topology</a>
          <a href="#/handover" class="${active('#/handover')}">Handover</a>
          <a href="#/reports" class="${active('#/reports')}">Reports</a>
          <a href="#/lab" class="${active('#/lab')}">Lab</a>
        </nav>
      </div>`;
  }
  function active(prefix) {
    const r = state.route;
    if (prefix === "#/incidents") return r === "#/incidents" || r.startsWith("#/incidents/") ? "active" : "";
    if (prefix === "#/reports") return r === "#/reports" || r.startsWith("#/reports") ? "active" : "";
    return r === prefix ? "active" : "";
  }

  function loginView() {
    return `
      <div class="login">
        <form class="card login-card" id="login-form" data-testid="login-form">
          <div class="tag">Operator console</div>
          <h1>Rootfold</h1>
          <p class="muted">Sign in to the simulated regional-carrier lab.</p>
          ${state.error ? `<div class="flash err">${esc(state.error)}</div>` : ""}
          <div class="field">
            <label for="user">Username</label>
            <input id="user" name="username" autocomplete="username" data-testid="login-user" required/>
          </div>
          <div class="field">
            <label for="pass">Password</label>
            <input id="pass" name="password" type="password" autocomplete="current-password" data-testid="login-pass" required/>
          </div>
          <button class="btn primary" type="submit" data-testid="login-submit">Log in</button>
          <p class="disclaimer">
            Honest disclaimer: this inventory is a simulated lab, not a production network.
            Lab users: <code>admin</code> / <code>night</code>, password <code>changeme</code>.
          </p>
        </form>
      </div>`;
  }

  function flash() {
    if (state.error) return `<div class="flash err">${esc(state.error)}</div>`;
    if (state.notice) return `<div class="flash ok">${esc(state.notice)}</div>`;
    return "";
  }

  function listView() {
    const rows = state.incidents.filter((i) => {
      if (state.filter === "all") return true;
      if (state.filter === "leftover") return i.kind === "leftover";
      if (state.filter === "open") return ["open", "sweep_pending", "escalated"].includes(i.status);
      return i.status === state.filter;
    });
    const chips = ["open", "sweep_pending", "escalated", "leftover", "resolved", "all"].map((f) =>
      `<button type="button" class="btn ${state.filter === f ? "on" : ""}" data-filter="${f}">${f.replace("_", " ")}</button>`
    ).join("");
    return `
      <h1>Incidents</h1>
      ${flash()}
      <div class="filters">${chips}</div>
      <div class="grid" data-testid="incident-list">
        ${rows.length ? rows.map(incidentCard).join("") : `<p class="muted">No incidents in this filter.</p>`}
      </div>`;
  }
  function incidentCard(i) {
    return `
      <article class="card clickable ${i.status !== "resolved" ? "down" : ""}" data-id="${i.id}" data-testid="incident-row">
        <div class="incident-meta">
          ${pill(i.public_ref)}
          ${pill(i.status)}
          ${pill(i.severity)}
          ${i.kind === "leftover" ? pill("leftover") : ""}
        </div>
        <strong>${esc(i.title)}</strong>
        <p class="muted">${esc(i.root_type || "unmapped")} ${esc(i.root_slug || "")} · ${i.alert_count} alert(s) · ${when(i.opened_at)}</p>
      </article>`;
  }

  function detailView(inc, books, exp) {
    if (!inc) return `<p class="muted">Loading…</p>`;
    const bookList = books || [];
    const checkList = [...new Set([...CHECKS, ...bookList.flatMap((b) => b.checks || [])])];
    const checks = checkList.map((c) => {
      const on = (inc.checks || []).includes(c);
      return `<label><input type="checkbox" name="checks" value="${esc(c)}" data-testid="gate-check" ${on ? "checked" : ""}/> ${esc(c)}</label>`;
    }).join("");
    const radius = inc.blast_radius || {};
    const chips = [
      ...(radius.sites || []).map((s) => `<span>site:${esc(s)}</span>`),
      ...(radius.circuits || []).map((s) => `<span>circuit:${esc(s)}</span>`),
      ...(radius.customers || []).map((s) => `<span>customer:${esc(s)}</span>`),
    ].join("");
    const alerts = (inc.alerts || []).map((a) =>
      `<tr><td>${esc(a.name)}</td><td>${pill(a.status)}</td><td>${esc(a.object_slug || "—")}</td><td>${when(a.last_seen_at)}</td></tr>`
    ).join("");
    const kids = (inc.children || []).map((c) =>
      `<a href="#/incidents/${c.id}">${esc(c.public_ref)}</a> ${esc(c.title)}`
    ).join("<br/>") || `<span class="muted">None</span>`;
    const timeline = (inc.timeline || []).map((e) =>
      `<li><div class="when">${when(e.at)} · ${esc(e.actor)}</div><div>${esc(e.message)}</div></li>`
    ).join("");
    const blocked = !inc.gate_complete;
    return `
      <p><a href="#/incidents">← Incidents</a></p>
      <div class="card" data-testid="incident-detail">
        <div class="incident-meta">
          ${pill(inc.public_ref)} ${pill(inc.status)} ${pill(inc.severity)} ${inc.kind === "leftover" ? pill("leftover") : ""}
        </div>
        <h1>${esc(inc.title)}</h1>
        <p class="muted">${esc(inc.root_type || "")} ${esc(inc.root_slug || "")} · opened ${when(inc.opened_at)}</p>
        ${flash()}
        <h2>Blast radius</h2>
        <div class="blast">${chips || `<span class="muted">Empty</span>`}</div>
        <h2>Child incidents</h2>
        <p>${kids}</p>
        <h2>Alerts</h2>
        <table><thead><tr><th>Name</th><th>Status</th><th>Object</th><th>Last seen</th></tr></thead>
        <tbody>${alerts}</tbody></table>
        <h2>Timeline</h2>
        <ol class="timeline">${timeline || "<li class=muted>No events yet</li>"}</ol>
      </div>
      <div class="card" style="margin-top:1rem">
        <h2>L1 quality gate</h2>
        <p class="muted">You cannot escalate or resolve until impact, urgency, at least one check, and notes are filled.</p>
        <form id="gate-form">
          <div class="row">
            <div class="field" style="flex:1">
              <label>Impact</label>
              <select name="impact" data-testid="gate-impact">
                ${opt(inc.impact, ["", "site-down", "degraded", "customer-impact", "no-customer-impact"])}
              </select>
            </div>
            <div class="field" style="flex:1">
              <label>Urgency</label>
              <select name="urgency" data-testid="gate-urgency">
                ${opt(inc.urgency, ["", "high", "medium", "low"])}
              </select>
            </div>
          </div>
          <div class="checks">${checks}</div>
          <div class="field">
            <label>Notes</label>
            <textarea name="notes" data-testid="gate-notes">${esc(inc.l1_notes || "")}</textarea>
          </div>
          <div class="row">
            <button class="btn primary" type="submit" data-testid="gate-save">Save gate</button>
            <button class="btn" type="button" id="btn-escalate" data-testid="btn-escalate" ${blocked ? "disabled" : ""}>Escalate</button>
            <button class="btn ok" type="button" id="btn-resolve" data-testid="btn-resolve" ${blocked ? "disabled" : ""}>Resolve</button>
          </div>
        </form>
      </div>
      ${runbookBlock(bookList, inc)}
      ${exportBlock(exp || {})}`;
  }
  function runbookBlock(books, inc) {
    if (!books.length) {
      return `<div class="card" style="margin-top:1rem"><h2>Runbook</h2><p class="muted">No runbook matched this alert.</p></div>`;
    }
    return books.map((b) => `
      <div class="card runbook" data-testid="runbook" data-id="${esc(b.id)}" style="margin-top:1rem">
        <div class="incident-meta">${b.primary ? pill("suggested") : ""} ${pill(b.id)}</div>
        <h2>${esc(b.title)}</h2>
        <p class="muted">${esc(b.summary)}</p>
        <div class="checks">
          ${(b.checks || []).map((c) => {
            const on = (inc.checks || []).includes(c);
            return `<label><input type="checkbox" class="runbook-check" data-testid="runbook-check" value="${esc(c)}" ${on ? "checked" : ""}/> ${esc(c)}</label>`;
          }).join("")}
        </div>
        <details><summary>Open runbook</summary><div class="runbook-body">${esc(b.body).replace(/\n/g, "<br/>")}</div></details>
      </div>`).join("");
  }
  function exportBlock(exp) {
    const ready = !!(exp.jira_configured || exp.servicenow_configured);
    return `
      <div class="card" id="export-panel" data-testid="export-panel" style="margin-top:1rem">
        <h2>Export ticket</h2>
        <p class="muted">${ready
          ? "A ticket backend is configured. Preview the payload, then send."
          : "Jira and ServiceNow are not configured, so Export only shows a dry-run preview of the payload."}</p>
        <div class="row">
          <select data-testid="export-backend" id="export-backend">
            <option value="jira">Jira</option>
            <option value="servicenow">ServiceNow</option>
          </select>
          <button class="btn primary" type="button" data-testid="btn-export" id="btn-export">Export</button>
          <button class="btn" type="button" data-testid="btn-export-send" id="btn-export-send" ${ready ? "" : "disabled"}>Send</button>
        </div>
        <pre class="payload" data-testid="export-preview" id="export-preview" hidden></pre>
      </div>`;
  }
  function opt(current, values) {
    return values.map((v) =>
      `<option value="${esc(v)}" ${v === (current || "") ? "selected" : ""}>${v || "— choose —"}</option>`
    ).join("");
  }

  const SHORT = {
    "bcu-dc": "Bacău DC",
    "bcu-pop": "Bacău Metro",
    "rmn": "Roman",
    "pnt": "Piatra Neamț",
    "bcz": "Bicaz",
    "ons": "Onești",
    "drm": "Dărmănești",
    "cms": "Comănești",
    "toc": "Târgu Ocna",
    "adj": "Adjud",
    "fcs": "Focșani",
  };
  function pt(slug) {
    const p = LAYOUT[slug] || [50, 50];
    return [p[0] * 10, p[1] * 10];
  }
  function topologyView(graph) {
    const sites = (graph.nodes || []).filter((n) => n.type === "site");
    const edges = (graph.edges || []).filter((e) => e.kind === "circuit");
    const lines = edges.map((e) => {
      const a = pt(e.from.replace("site:", ""));
      const b = pt(e.to.replace("site:", ""));
      const color = e.status === "down" ? "var(--down)" : (e.media === "microwave" ? "var(--mw)" : "var(--fiber)");
      const width = e.status === "down" ? 5 : 3;
      return `<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="${color}" stroke-width="${width}" data-slug="${esc(e.slug)}"/>`;
    }).join("");
    const dots = sites.map((n) => {
      const p = pt(n.slug);
      const fill = n.status === "down" ? "#f07178" : "#3dcf8e";
      const label = SHORT[n.slug] || n.name;
      return `<g data-slug="${esc(n.slug)}">
        <circle cx="${p[0]}" cy="${p[1]}" r="12" fill="${fill}" stroke="#0b1220" stroke-width="3"/>
        <text x="${p[0]}" y="${p[1] - 22}" fill="#e8eef7" font-size="22" text-anchor="middle" font-family="ui-sans-serif, system-ui, sans-serif">${esc(label)}</text>
      </g>`;
    }).join("");
    return `
      <h1>Lab topology</h1>
      <p class="muted">Carpathian Carrier (simulated). Green is up, red is in the blast radius of an open incident.</p>
      <div class="legend">
        <span><i class="swatch fiber"></i>Fiber</span>
        <span><i class="swatch mw"></i>Microwave</span>
        <span><i class="swatch down"></i>Down</span>
      </div>
      <svg id="topology-map" viewBox="0 0 1000 1000" preserveAspectRatio="xMidYMid meet" data-testid="topology-map">
        ${lines}${dots}
      </svg>`;
  }

  function handoverView(list) {
    const pending = state.pending;
    const rows = (list || []).map((h) => `
      <article class="card">
        <div class="incident-meta">${pill(h.public_ref)} ${pill(h.status)}</div>
        <p>Closed by ${esc(h.created_by)} at ${when(h.created_at)}</p>
        <p class="muted">${esc(h.outgoing_notes || "No outgoing notes.")} · ${h.snapshot?.count ?? 0} open incident(s)</p>
        ${(h.snapshot?.incidents || []).map((i) => `${esc(i.public_ref)} ${esc(i.title)}`).join("<br/>")}
        ${h.status === "pending_ack" ? `
          <form class="ack-form" data-id="${h.id}" style="margin-top:.7rem">
            <div class="field"><label>Ack notes</label><textarea name="notes" data-testid="handover-ack-notes"></textarea></div>
            <button class="btn primary" type="submit" data-testid="handover-ack">Acknowledge handover</button>
          </form>` : `<p class="muted">Acked by ${esc(h.acked_by)} at ${when(h.acked_at)}</p>`}
      </article>`).join("");
    return `
      <h1>Shift handover</h1>
      ${flash()}
      ${pending ? `<div class="flash warn" data-testid="pending-banner">${esc(pending.public_ref)} is waiting for the incoming shift to acknowledge.</div>` : ""}
      <div class="card">
        <h2>Close this shift</h2>
        <form id="handover-close">
          <div class="field"><label>Notes for the next shift</label>
            <textarea name="notes" data-testid="handover-notes"></textarea></div>
          <button class="btn primary" type="submit" data-testid="handover-close">Build handover from open incidents</button>
        </form>
      </div>
      <div class="grid" style="margin-top:1rem">${rows || `<p class="muted">No handovers yet.</p>`}</div>`;
  }


  function reportsView(data, year, month) {
    const rows = (data.rows || []).map((r) => `
      <tr data-testid="report-row" class="${r.sla_breach ? "breach" : ""}">
        <td>${esc(r.scope)}</td>
        <td class="mono">${esc(r.slug)}</td>
        <td>${esc(r.name)}</td>
        <td>${r.incident_count}</td>
        <td>${Number(r.uptime_percent).toFixed(4)}%</td>
        <td>${r.mttr_seconds == null ? "—" : r.mttr_seconds}</td>
        <td>${r.sla_breach ? pill("breach") : pill("ok", "up")}</td>
      </tr>`).join("");
    return `
      <h1>Monthly availability</h1>
      ${flash()}
      <p class="muted">Uptime is 100% minus the union of incident downtime in the calendar month (UTC). The SLA threshold is ${esc(data.sla_percent)}%. Print this page to get a PDF.</p>
      <form id="report-filter" class="row" style="margin:.6rem 0 1rem">
        <div class="field"><label>Year</label><input name="year" type="number" value="${year}" data-testid="report-year"/></div>
        <div class="field"><label>Month</label><input name="month" type="number" min="1" max="12" value="${month}" data-testid="report-month"/></div>
        <button class="btn primary" type="submit" data-testid="report-load">Load</button>
        <button class="btn" type="button" id="btn-report-csv" data-testid="btn-report-csv">Download CSV</button>
        <button class="btn" type="button" id="btn-report-print" data-testid="btn-report-print">Print / PDF</button>
      </form>
      <p class="muted">${data.incident_count} incident(s) overlapping the month · ${data.breach_count} SLA breach(es)</p>
      <div class="card" style="overflow:auto">
        <table data-testid="report-table">
          <thead><tr><th>Scope</th><th>Slug</th><th>Name</th><th>Incidents</th><th>Uptime</th><th>MTTR (s)</th><th>SLA</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="7" class="muted">No inventory to report.</td></tr>`}</tbody>
        </table>
      </div>`;
  }

  function labView(scenarios) {
    const cards = (scenarios || []).map((s) => `
      <article class="card scenario">
        <h3>${esc(s.title)}</h3>
        <p class="muted">${esc(s.summary)}</p>
        <button class="btn primary" type="button" data-inject="${esc(s.id)}" data-testid="btn-inject-${esc(s.id)}">Inject scenario</button>
      </article>`).join("");
    return `
      <h1>Lab controls</h1>
      ${flash()}
      <p class="muted">These buttons fire simulated alerts against the Carpathian Carrier inventory. They are not a real network.</p>
      <div class="grid">${cards}</div>
      <p style="margin-top:1rem">
        <button class="btn danger" type="button" id="btn-reset" data-testid="btn-reset-lab">Reset lab</button>
      </p>`;
  }

  async function render() {
    const app = $("#app");
    const route = location.hash || (state.token ? "#/incidents" : "#/login");
    state.route = route;
    if (!state.token && route !== "#/login") {
      location.hash = "#/login";
      return;
    }
    if (route === "#/login") {
      app.innerHTML = loginView();
      $("#login-form").addEventListener("submit", async (ev) => {
        ev.preventDefault();
        state.error = "";
        const fd = new FormData(ev.target);
        try { await login(fd.get("username"), fd.get("password")); }
        catch (e) { state.error = e.message; render(); }
      });
      return;
    }
    await refreshPending();
    app.innerHTML = layout();
    $("#btn-logout").addEventListener("click", () => logout());
    const main = $("#main");
    try {
      if (route === "#/incidents") {
        const all = await api("/api/incidents");
        state.incidents = all;
        main.innerHTML = listView();
        main.querySelectorAll("[data-filter]").forEach((b) => b.addEventListener("click", () => {
          state.filter = b.dataset.filter;
          render();
        }));
        main.querySelectorAll("[data-id]").forEach((el) => el.addEventListener("click", () => {
          location.hash = `#/incidents/${el.dataset.id}`;
        }));
      } else if (route.startsWith("#/incidents/")) {
        const id = route.split("/")[2];
        const inc = await api(`/api/incidents/${id}`);
        const rb = await api(`/api/incidents/${id}/runbooks`);
        const exp = await api(`/api/incidents/${id}/export`);
        main.innerHTML = detailView(inc, rb.runbooks || [], exp);
        bindDetail(id, inc, rb.runbooks || [], exp);
      } else if (route === "#/reports" || route.startsWith("#/reports")) {
        const params = new URLSearchParams((route.split("?")[1] || ""));
        const now = new Date();
        const year = Number(params.get("year") || now.getUTCFullYear());
        const month = Number(params.get("month") || (now.getUTCMonth() + 1));
        const data = await api(`/api/reports/availability?year=${year}&month=${month}`);
        main.innerHTML = reportsView(data, year, month);
        bindReports(year, month);
      } else if (route === "#/topology") {
        const graph = await api("/api/topology/graph");
        main.innerHTML = topologyView(graph);
      } else if (route === "#/handover") {
        const list = await api("/api/handover");
        main.innerHTML = handoverView(list);
        bindHandover();
      } else if (route === "#/lab") {
        const scenarios = await api("/api/lab/scenarios");
        main.innerHTML = labView(scenarios);
        bindLab();
      } else {
        location.hash = "#/incidents";
      }
    } catch (e) {
      main.innerHTML = `<div class="flash err">${esc(e.message)}</div>`;
    }
  }

  function bindDetail(id, inc, books, exp) {
    const form = $("#gate-form");
    form?.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const fd = new FormData(form);
      const checks = [...form.querySelectorAll("input[name=checks]:checked")].map((c) => c.value);
      try {
        await api(`/api/incidents/${id}/gate`, {
          method: "PUT",
          body: { impact: fd.get("impact"), urgency: fd.get("urgency"), checks, notes: fd.get("notes") },
        });
        state.error = "";
        state.notice = "Quality gate saved.";
        render();
      } catch (e) { state.error = e.message; state.notice = ""; render(); }
    });
    $("#btn-escalate")?.addEventListener("click", () => act(id, "escalate"));
    $("#btn-resolve")?.addEventListener("click", () => act(id, "resolve"));
    document.querySelectorAll(".runbook-check").forEach((box) => {
      box.addEventListener("change", async () => {
        if (!box.checked) return;
        try {
          await api(`/api/incidents/${id}/checks`, { method: "POST", body: { checks: [box.value] } });
          state.notice = "Check added to the L1 gate.";
          state.error = "";
          render();
        } catch (e) { state.error = e.message; render(); }
      });
    });
    const preview = $("#export-preview");
    const backendSel = $("#export-backend");
    const showPayload = (row, notice) => {
      if (!preview) return;
      preview.hidden = false;
      preview.textContent = JSON.stringify(row.payload, null, 2);
      let flash = document.getElementById("export-flash");
      if (!flash) {
        flash = document.createElement("div");
        flash.id = "export-flash";
        flash.className = "flash ok";
        flash.dataset.testid = "export-flash";
        preview.before(flash);
      }
      flash.textContent = notice || (row.dry_run ? "Dry-run preview. Nothing was sent." : "Exported.");
    };
    $("#btn-export")?.addEventListener("click", async () => {
      try {
        const row = await api(`/api/incidents/${id}/export`, {
          method: "POST",
          body: { backend: backendSel.value, dry_run: true },
        });
        state.error = "";
        state.notice = row.dry_run ? "Dry-run preview. Nothing was sent." : "Exported.";
        showPayload(row);
      } catch (e) { state.error = e.message; render(); }
    });
    $("#btn-export-send")?.addEventListener("click", async () => {
      try {
        const row = await api(`/api/incidents/${id}/export`, {
          method: "POST",
          body: { backend: backendSel.value, dry_run: false },
        });
        state.error = "";
        state.notice = `Sent to ${row.backend} as ${row.external_key || "ticket"}.`;
        showPayload(row);
      } catch (e) { state.error = e.message; render(); }
    });
  }
  function bindReports(year, month) {
    $("#report-filter")?.addEventListener("submit", (ev) => {
      ev.preventDefault();
      const fd = new FormData(ev.target);
      location.hash = `#/reports?year=${fd.get("year")}&month=${fd.get("month")}`;
    });
    $("#btn-report-csv")?.addEventListener("click", async () => {
      const res = await fetch(`/api/reports/availability?year=${year}&month=${month}&format=csv`, {
        headers: { Authorization: `Bearer ${state.token}` },
      });
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `rootfold-availability-${year}-${String(month).padStart(2, "0")}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    });
    $("#btn-report-print")?.addEventListener("click", () => window.print());
  }
  async function act(id, action) {
    try {
      await api(`/api/incidents/${id}/${action}`, { method: "POST" });
      state.error = "";
      state.notice = action === "escalate" ? "Incident escalated." : "Incident resolved.";
      render();
    } catch (e) { state.error = e.message; state.notice = ""; render(); }
  }
  function bindHandover() {
    $("#handover-close")?.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      try {
        await api("/api/handover/close", { method: "POST", body: { notes: new FormData(ev.target).get("notes") } });
        state.notice = "Handover opened. The incoming shift must acknowledge it.";
        state.error = "";
        await refreshPending();
        render();
      } catch (e) { state.error = e.message; render(); }
    });
    document.querySelectorAll(".ack-form").forEach((form) => {
      form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        try {
          await api(`/api/handover/${form.dataset.id}/ack`, {
            method: "POST",
            body: { notes: new FormData(form).get("notes") },
          });
          state.notice = "Handover acknowledged.";
          state.error = "";
          await refreshPending();
          render();
        } catch (e) { state.error = e.message; render(); }
      });
    });
  }
  function bindLab() {
    document.querySelectorAll("[data-inject]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          const res = await api(`/api/lab/inject/${btn.dataset.inject}`, { method: "POST" });
          state.notice = `Injected: ${res.title}`;
          state.error = "";
          const id = (res.incident_ids || [])[0];
          location.hash = id ? `#/incidents/${id}` : "#/incidents";
          render();
        } catch (e) { state.error = e.message; render(); }
      });
    });
    $("#btn-reset")?.addEventListener("click", async () => {
      if (!confirm("Clear incidents, alerts, and handovers, and reload the lab topology?")) return;
      try {
        await api("/api/lab/reset", { method: "POST" });
        state.notice = "Lab reset.";
        state.error = "";
        location.hash = "#/incidents";
        render();
      } catch (e) { state.error = e.message; render(); }
    });
  }

  async function refreshPending() {
    if (!state.token) { state.pending = null; return; }
    try { state.pending = await api("/api/handover/pending"); }
    catch { state.pending = null; }
  }
  async function tickClock() {
    try {
      const h = await fetch("/healthz").then((r) => r.json());
      state.clock = (h.time || "").replace("T", " ").replace(/\.\d+.*$/, " UTC");
      const el = $("[data-testid=clock]");
      if (el) el.textContent = state.clock;
    } catch { /* offline is fine */ }
  }

  async function boot() {
    if (state.token) {
      try {
        state.me = await api("/api/auth/me");
        const sites = await api("/api/topology/sites");
        if (!sites.length) await api("/api/topology/import-example", { method: "POST" });
        await refreshPending();
      } catch { logout(false); }
    }
    await tickClock();
    render();
  }
  window.addEventListener("hashchange", () => { state.error = ""; state.notice = ""; render(); });
  setInterval(tickClock, 15000);
  boot();
})();
