"use strict";
// Cashflow Planner front end. Plain JavaScript, no build step.

const $app = document.getElementById("app");
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const gbp = (v) => (v == null ? "–" : (v < 0 ? "-£" : "£") + Math.round(Math.abs(v)).toLocaleString("en-GB"));
const pct = (v) => (v == null ? "" : +(v * 100).toFixed(4));
const POT_TYPES = ["current_account", "cash", "isa", "gia", "pension", "other"];
const POT_LABELS = { current_account: "Current account", cash: "Cash", isa: "ISA", gia: "GIA", pension: "Pension", other: "Other" };
const FREQS = ["weekly", "monthly", "quarterly", "annual", "one_off"];
const COLOURS = ["#1f5f8b", "#3d9970", "#e0a030", "#8e5ea2", "#c0504d", "#4bacc6", "#7f7f7f", "#9bbb59"];

async function api(path, opts = {}) {
  const init = { method: opts.method || (opts.body ? "POST" : "GET"), headers: {} };
  if (opts.body instanceof FormData) init.body = opts.body;
  else if (opts.body !== undefined) { init.body = JSON.stringify(opts.body); init.headers["Content-Type"] = "application/json"; }
  const res = await fetch(path, init);
  if (res.status === 401) { location.hash = "#/unlock"; throw new Error("Locked"); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function nav(items) {
  document.getElementById("nav").innerHTML = items.map(([href, label, on]) =>
    `<a href="${href}" class="${on ? "on" : ""}">${esc(label)}</a>`).join("");
}

// ---------------------------------------------------------------- routing
async function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  const st = await api("/api/status");
  document.getElementById("lock").hidden = !st.unlocked;
  if (!st.unlocked && parts[0] !== "unlock") { location.hash = "#/unlock"; return; }
  try {
    if (parts[0] === "unlock") return unlockView(st);
    if (parts[0] === "client" && parts[2] === "compare") return compareView(parts[1]);
    if (parts[0] === "client" && parts[2] === "audit") return auditView(parts[1]);
    if (parts[0] === "client") return planView(parts[1], parts[3] || "Baseline");
    if (parts[0] === "review") return reviewView();
    return clientsView();
  } catch (e) { $app.innerHTML = `<div class="warn">${esc(e.message)}</div>`; }
}
window.addEventListener("hashchange", route);
document.getElementById("lock").onclick = async () => { await api("/api/lock", { body: {} }); location.hash = "#/unlock"; };

// ---------------------------------------------------------------- unlock
function unlockView(st) {
  nav([]);
  $app.innerHTML = `<div class="center panel">
    <h1>${st.db_exists ? "Unlock client records" : "Set up client records"}</h1>
    <p class="muted">${st.db_exists ? "Enter your passphrase." :
      "Choose a passphrase. It encrypts every client record on this computer. It can't be recovered if you forget it."}</p>
    <form id="f"><label>Passphrase</label><input type="password" id="pw" autofocus minlength="8" required>
    ${st.db_exists ? "" : `<label style="margin-top:8px">Confirm passphrase</label><input type="password" id="pw2" required>`}
    <p id="err" class="neg"></p><button>Unlock</button></form>
    <p class="muted" style="font-size:12px">Records file: ${esc(st.db_path)}</p></div>`;
  document.getElementById("f").onsubmit = async (e) => {
    e.preventDefault();
    const pw = document.getElementById("pw").value;
    const pw2 = document.getElementById("pw2");
    if (pw2 && pw2.value !== pw) { document.getElementById("err").textContent = "The passphrases don't match"; return; }
    try { await api("/api/unlock", { body: { passphrase: pw } }); location.hash = "#/clients"; }
    catch (err) { document.getElementById("err").textContent = err.message; }
  };
}

// ---------------------------------------------------------------- clients
async function clientsView() {
  nav([["#/clients", "Clients", true]]);
  const clients = await api("/api/clients");
  $app.innerHTML = `<h1>Clients</h1>
  <div class="grid2">
    <div class="panel"><h2>Client records</h2>
      ${clients.length ? `<table class="list"><tr><th>Name</th><th>Created</th></tr>${clients.map((c) =>
        `<tr><td><a href="#/client/${c.id}/plan/Baseline">${esc(c.name)}</a></td><td>${esc(c.created_at.slice(0, 10))}</td></tr>`).join("")}</table>`
        : `<p class="muted">No clients yet.</p>`}
    </div>
    <div>
      <div class="panel"><h2>Import a fact find</h2>
        <p class="muted">CashCalc PDF exports are supported. You'll review everything before it's saved.</p>
        <input type="file" id="pdf" accept="application/pdf"><p id="ierr" class="neg"></p>
        <button id="imp">Read fact find</button></div>
      <div class="panel"><h2>New client</h2>
        <form id="nc"><div class="row">
          <div><label>Name</label><input name="name" required></div>
          <div><label>Date of birth</label><input type="date" name="date_of_birth" required></div>
          <div><label>Retirement age</label><input type="number" name="retirement_age"></div>
        </div><p></p><button>Create</button></form></div>
    </div></div>`;
  document.getElementById("imp").onclick = async () => {
    const f = document.getElementById("pdf").files[0];
    if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    try { sessionStorage.setItem("review", JSON.stringify(await api("/api/import", { body: fd }))); location.hash = "#/review"; }
    catch (e) { document.getElementById("ierr").textContent = e.message; }
  };
  document.getElementById("nc").onsubmit = async (e) => {
    e.preventDefault();
    const d = Object.fromEntries(new FormData(e.target));
    d.retirement_age = d.retirement_age ? +d.retirement_age : null;
    const r = await api("/api/clients", { body: d });
    location.hash = `#/client/${r.id}/plan/Baseline`;
  };
}

// ---------------------------------------------------------------- import review
function reviewView() {
  nav([["#/clients", "Clients", false], ["#/review", "Review import", true]]);
  const data = JSON.parse(sessionStorage.getItem("review") || "null");
  if (!data) { location.hash = "#/clients"; return; }
  const ff = data.fact_find, d = data.defaults;
  const c = ff.clients[0] || {};
  const per = (i) => i.amount * ({ weekly: 52, monthly: 12, quarterly: 4, annual: 1, one_off: 1 }[i.frequency]);
  $app.innerHTML = `<h1>Review fact find: ${esc(c.name)}</h1>
  ${ff.warnings.length ? `<div class="warn"><b>Please check:</b><ul>${ff.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
  <div class="grid2">
    <div class="panel"><h2>Client</h2><div class="row">
      <div><label>Name</label><input id="r_name" value="${esc(c.name)}"></div>
      <div><label>Date of birth</label><input type="date" id="r_dob" value="${esc(c.date_of_birth || "")}" required></div>
      <div><label>Retirement age</label><input type="number" id="r_ret" value="${esc(c.retirement_age ?? "")}"></div>
      <div><label>Forecast start date</label><input type="date" id="r_start" value="${new Date().toISOString().slice(0, 10)}"></div></div>
      <p class="muted">Source: ${esc(ff.source)}${ff.completed_on ? `, completed ${esc(ff.completed_on)}` : ""}.
      ${c.health ? `Health: ${esc(c.health)}.` : ""} ${c.marital_status ? `Marital status: ${esc(c.marital_status)}.` : ""}</p>
      ${ff.objectives.length ? `<h2>Objectives</h2>${ff.objectives.map((o) => `<p>${esc(o)}</p>`).join("")}` : ""}
    </div>
    <div class="panel"><h2>Starting assumptions</h2>
      <p class="muted">The fact find has no growth or charge assumptions. These apply to every imported pot, and you can change each pot afterwards.</p>
      <div class="row"><div><label>Inflation %</label><input type="number" step="0.01" id="d_infl" value="${pct(d.inflation)}"></div>
      <div><label>Plan to age</label><input type="number" id="d_end" value="${d.end_age}"></div></div>
      <table class="edit"><tr><th>Type</th><th>Growth %</th><th>Charges %</th><th>Withdrawal tax %</th></tr>
      ${["pension", "isa", "gia", "cash", "other"].map((k) => `<tr><td>${POT_LABELS[k]}</td>
        <td><input type="number" step="0.01" data-g="${k}" value="${pct(d.growth[k] ?? 0)}"></td>
        <td><input type="number" step="0.01" data-c="${k}" value="${pct(d.charges[k] ?? 0)}"></td>
        <td><input type="number" step="0.01" data-t="${k}" value="${pct(d.tax[k] ?? 0)}"></td></tr>`).join("")}</table></div>
  </div>
  <div class="grid2">
    <div class="panel"><h2>Pensions, savings and investments</h2><table>
      <tr><th>Type</th><th>Name</th><th class="num">Value</th></tr>
      ${ff.holdings.map((h) => `<tr><td>${esc(POT_LABELS[h.kind] || h.kind)}</td><td>${esc(h.name)}</td><td class="num">${gbp(h.value)}</td></tr>`).join("")}
      <tr><th colspan="2">Total</th><th class="num">${gbp(ff.holdings.reduce((a, h) => a + h.value, 0))}</th></tr></table>
      ${ff.other_assets.length ? `<h2 style="margin-top:12px">Other assets (not in the forecast)</h2><table>${ff.other_assets.map((a) =>
        `<tr><td>${esc(a.description)}</td><td class="num">${gbp(a.value)}</td></tr>`).join("")}</table>` : ""}</div>
    <div class="panel"><h2>Income and expenditure</h2><table>
      <tr><th>Item</th><th>Type</th><th class="num">Amount</th><th>Frequency</th><th class="num">Per year</th></tr>
      ${ff.incomes.map((i) => `<tr><td>${esc(i.name)}</td><td>Income</td><td class="num">${gbp(i.amount)}</td><td>${esc(i.frequency)}</td><td class="num">${gbp(per(i))}</td></tr>`).join("")}
      ${ff.expenses.map((i) => `<tr><td>${esc(i.name)}</td><td>${esc(i.priority || "Expense")}</td><td class="num">${gbp(i.amount)}</td><td>${esc(i.frequency)}</td><td class="num">${gbp(per(i))}</td></tr>`).join("")}
      <tr><th colspan="4">Total expenditure</th><th class="num">${gbp(ff.expenses.reduce((a, i) => a + per(i), 0))}</th></tr></table></div>
  </div>
  <p id="err" class="neg"></p><button id="ok">Create client and baseline forecast</button>`;
  document.getElementById("ok").onclick = async () => {
    const num = (sel) => Object.fromEntries([...document.querySelectorAll(`[${sel}]`)].map((i) => [i.getAttribute(sel), +i.value / 100]));
    ff.clients[0].name = document.getElementById("r_name").value;
    const ret = document.getElementById("r_ret").value; ff.clients[0].retirement_age = ret ? +ret : null;
    const defaults = { ...d, inflation: +document.getElementById("d_infl").value / 100, end_age: +document.getElementById("d_end").value,
      growth: { ...d.growth, ...num("data-g") }, charges: { ...d.charges, ...num("data-c") }, tax: { ...d.tax, ...num("data-t") } };
    try {
      const r = await api("/api/import/confirm", { body: { fact_find: ff, defaults,
        date_of_birth: document.getElementById("r_dob").value || null, start_date: document.getElementById("r_start").value } });
      sessionStorage.removeItem("review");
      location.hash = `#/client/${r.id}/plan/Baseline`;
    } catch (e) { document.getElementById("err").textContent = e.message; }
  };
}

// ---------------------------------------------------------------- plan editor
const ITEM_COLS = [
  ["name", "Description", "text"], ["amount", "Amount £", "num"], ["frequency", "Frequency", FREQS],
  ["start_age", "From age", "int"], ["end_age", "To age", "int?"], ["inflation", "Inflation %", "pct?"], ["category", "Category", "text?"]];
const SPECS = {
  pots: { title: "Pensions, savings and investments", cols: [["name", "Name", "text"], ["type", "Type", POT_TYPES], ["value", "Value £", "num"],
    ["growth_rate", "Growth %", "pct"], ["charge_rate", "Charges %", "pct"], ["tax_rate", "Withdrawal tax %", "pct"]],
    blank: () => ({ id: "pot" + Date.now().toString(36), name: "New pot", type: "isa", value: 0, growth_rate: 0.05, charge_rate: 0.0075, tax_rate: 0, owner: null }) },
  incomes: { title: "Income", cols: ITEM_COLS, blank: (p) => ({ name: "Income", amount: 0, frequency: "annual", start_age: startAge(p), end_age: null, inflation: null, category: null }) },
  expenses: { title: "Expenditure", cols: ITEM_COLS, blank: (p) => ({ name: "Expense", amount: 0, frequency: "monthly", start_age: startAge(p), end_age: null, inflation: null, category: null }) },
  contributions: { title: "Contributions", cols: [...ITEM_COLS.slice(0, 6), ["pot_id", "Into", "pot"], ["external", "From outside plan", "bool"]],
    blank: (p) => ({ name: "Contribution", amount: 0, frequency: "monthly", start_age: startAge(p), end_age: p.client.retirement_age, inflation: null, category: null, pot_id: p.pots[0]?.id, external: false }) },
  withdrawals: { title: "Planned withdrawals (net)", cols: [...ITEM_COLS.slice(0, 6), ["pot_id", "From", "pot"]],
    blank: (p) => ({ name: "Withdrawal", amount: 0, frequency: "monthly", start_age: p.client.retirement_age || startAge(p), end_age: null, inflation: null, category: null, pot_id: p.pots.find((x) => x.type === "pension")?.id || p.pots[0]?.id }) },
  one_off_charges: { title: "One-off charges", cols: [["name", "Description", "text"], ["pot_id", "From", "pot"], ["rate", "Rate %", "pct"], ["age", "At age", "int"]],
    blank: (p) => ({ name: "Initial advice fee", pot_id: p.pots[0]?.id, rate: 0.03, age: startAge(p) }) },
};
function startAge(p) {
  const dob = new Date(p.client.date_of_birth), s = new Date(p.start_date);
  let a = s.getFullYear() - dob.getFullYear();
  if (s.getMonth() < dob.getMonth() || (s.getMonth() === dob.getMonth() && s.getDate() < dob.getDate())) a--;
  return a;
}

let charts = {};
function chart(id, cfg) { charts[id]?.destroy(); charts[id] = new Chart(document.getElementById(id), cfg); return charts[id]; }

async function planView(cid, name) {
  const client = await api(`/api/clients/${cid}`);
  const { plan, versions } = await api(`/api/clients/${cid}/plans/${encodeURIComponent(name)}`);
  nav([["#/clients", "Clients", false], [`#/client/${cid}/plan/Baseline`, client.name, true],
       [`#/client/${cid}/compare`, "Compare scenarios", false], [`#/client/${cid}/audit`, "Audit trail", false]]);
  let tab = "pots", selected = null, forecast = null, timer = null;
  const base = JSON.parse(JSON.stringify(plan));

  $app.innerHTML = `<div class="row" style="align-items:center;margin-bottom:8px">
      <div style="flex:3"><h1 style="margin:0">${esc(client.name)}</h1></div>
      <div><label>Forecast</label><select id="planSel">${client.plans.map((n) => `<option ${n === name ? "selected" : ""}>${esc(n)}</option>`).join("")}</select></div>
    </div>
    ${client.details?.warnings?.length ? `<div class="warn"><b>From the import:</b><ul>${client.details.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
    <div class="layout">
      <div>
        <div class="panel"><h2>Client and assumptions</h2><div class="row">
          <div><label>Date of birth</label><input type="date" data-k="client.date_of_birth"></div>
          <div><label>Retirement age</label><input type="number" data-k="client.retirement_age" data-t="int?"></div>
          <div><label>Start date</label><input type="date" data-k="start_date"></div></div>
          <div class="row" style="margin-top:8px">
          <div><label>Inflation: <b id="inflOut"></b></label><input type="range" min="0" max="8" step="0.1" data-k="assumptions.inflation" data-t="pct"></div>
          <div><label>Plan to age</label><input type="number" data-k="assumptions.end_age" data-t="int"></div></div>
          <div class="row" style="margin-top:8px">
          <div><label>Surplus saved %</label><input type="number" step="1" data-k="assumptions.surplus_to_save" data-t="pct"></div>
          <div><label>Save surplus into</label><select data-k="assumptions.surplus_pot_id" data-t="pot"></select></div></div>
          <div style="margin-top:8px"><label>All growth rates: <b id="gOut">±0%</b> (what-if: included in whatever you save next)</label>
          <input type="range" id="gAdj" min="-4" max="4" step="0.25" value="0"></div>
        </div>
        <div class="panel">
          <div class="tabs">${Object.entries(SPECS).map(([k, s]) => `<button data-tab="${k}">${esc(s.title.split(" (")[0])}</button>`).join("")}<button data-tab="order">Withdrawal order</button></div>
          <div id="tabBody" class="scroll"></div>
        </div>
        <div class="panel"><h2>Save</h2><div class="row">
          <div style="flex:3"><label>Note for the audit trail</label><input id="note" placeholder="What changed and why"></div>
          <div><button id="save">Save ${esc(name)}</button></div></div>
          <div class="row" style="margin-top:10px">
          <div style="flex:3"><label>Or save as a new scenario</label><input id="scName" placeholder="e.g. Increased withdrawals"></div>
          <div><button class="ghost" id="saveAs">Save as scenario</button></div></div>
          <p class="muted" style="margin-top:10px">Quick scenarios from this forecast:
            <button class="small ghost" data-q="care">Care costs £60k from 85</button>
            <button class="small ghost" data-q="infl">Inflation 4%</button>
            <button class="small ghost" data-q="ret">Returns 2% lower</button></p>
          <p id="msg" class="muted"></p>
          <p class="muted" style="font-size:12px">Saved versions: ${versions.map((v) => `v${v.version} ${esc(v.saved_at.slice(0, 10))}${v.note ? " – " + esc(v.note) : ""}`).join("; ")}</p>
        </div>
      </div>
      <div class="sticky">
        <div class="panel"><div class="kpis" id="kpis"></div>
          <div class="tabs"><button data-ch="wealth" class="on">Total wealth</button><button data-ch="pension">Pensions</button><button data-ch="ie">Income vs expenditure</button></div>
          <div class="chart"><canvas id="ch"></canvas></div>
          <p class="muted" style="font-size:12px;margin:6px 0 0">Click a year on the chart or in the table to see its figures.</p></div>
        <div class="panel" id="detail"><p class="muted">Select a year.</p></div>
        <div class="panel"><h2>Year by year</h2><div class="years"><table id="years"></table></div></div>
      </div>
    </div>`;

  document.getElementById("planSel").onchange = (e) => (location.hash = `#/client/${cid}/plan/${encodeURIComponent(e.target.value)}`);

  // Bind simple fields.
  const get = (k) => k.split(".").reduce((o, p) => o?.[p], plan);
  const set = (k, v) => { const ps = k.split("."); const last = ps.pop(); ps.reduce((o, p) => o[p], plan)[last] = v; };
  const read = (el, t) => {
    const v = el.value;
    if (t === "pct" || t === "pct?") return v === "" ? (t === "pct?" ? null : 0) : +v / 100;
    if (t === "int" || t === "int?") return v === "" ? (t === "int?" ? null : 0) : parseInt(v, 10);
    if (t === "num") return +v || 0;
    if (t === "bool") return el.checked;
    if (t === "pot") return v || null;
    return v === "" && t === "text?" ? null : v;
  };
  function bindFields() {
    document.querySelectorAll("[data-k]").forEach((el) => {
      const k = el.dataset.k, t = el.dataset.t;
      if (t === "pot") el.innerHTML = `<option value="">(none)</option>` + plan.pots.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("");
      const v = get(k);
      el.value = t === "pct" ? pct(v) : v ?? "";
      el.oninput = () => { set(k, read(el, t)); refresh(); };
    });
  }
  bindFields();
  const gAdj = document.getElementById("gAdj");
  gAdj.oninput = () => { document.getElementById("gOut").textContent = (gAdj.value > 0 ? "+" : gAdj.value < 0 ? "" : "±") + gAdj.value + "%"; refresh(); };

  // Tables.
  function renderTab() {
    document.querySelectorAll("[data-tab]").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
    const body = document.getElementById("tabBody");
    if (tab === "order") {
      const order = plan.withdrawal_order;
      plan.pots.forEach((p) => { if (!order.includes(p.id)) order.push(p.id); });
      plan.withdrawal_order = order.filter((id) => plan.pots.some((p) => p.id === id));
      body.innerHTML = `<p class="muted">Pots are drawn in this order to cover any shortfall between income and spending.</p>
        <ol class="order">${plan.withdrawal_order.map((id, i) => { const p = plan.pots.find((x) => x.id === id);
          return `<li><span style="flex:1">${esc(p.name)} <span class="muted">(${POT_LABELS[p.type]})</span></span>
          <button class="small ghost" data-up="${i}" ${i ? "" : "disabled"}>↑</button><button class="small ghost" data-dn="${i}" ${i < plan.withdrawal_order.length - 1 ? "" : "disabled"}>↓</button></li>`; }).join("")}</ol>`;
      body.querySelectorAll("[data-up],[data-dn]").forEach((b) => b.onclick = () => {
        const i = +(b.dataset.up ?? b.dataset.dn), j = b.dataset.up !== undefined ? i - 1 : i + 1, o = plan.withdrawal_order;
        [o[i], o[j]] = [o[j], o[i]]; renderTab(); refresh();
      });
      return;
    }
    const spec = SPECS[tab], rows = plan[tab];
    const potOpts = (v) => plan.pots.map((p) => `<option value="${esc(p.id)}" ${p.id === v ? "selected" : ""}>${esc(p.name)}</option>`).join("");
    const cell = (r, i, [k, , t]) => {
      const v = r[k], at = `data-r="${i}" data-c="${k}"`;
      if (Array.isArray(t)) return `<select ${at}>${t.map((o) => `<option ${o === v ? "selected" : ""} value="${o}">${esc(POT_LABELS[o] || o.replace("_", "-"))}</option>`).join("")}</select>`;
      if (t === "pot") return `<select ${at}>${potOpts(v)}</select>`;
      if (t === "bool") return `<input type="checkbox" ${at} ${v ? "checked" : ""}>`;
      if (t.startsWith("pct")) return `<input type="number" step="0.01" ${at} value="${v == null ? "" : pct(v)}" placeholder="${t === "pct?" ? "assumed" : ""}" style="width:80px">`;
      if (t.startsWith("int")) return `<input type="number" ${at} value="${v ?? ""}" placeholder="${t === "int?" ? "end" : ""}" style="width:70px">`;
      if (t === "num") return `<input type="number" step="any" ${at} value="${v ?? 0}" style="width:110px">`;
      return `<input ${at} value="${esc(v ?? "")}">`;
    };
    body.innerHTML = `<table class="edit"><tr>${spec.cols.map((c) => `<th>${esc(c[1])}</th>`).join("")}<th></th></tr>
      ${rows.map((r, i) => `<tr>${spec.cols.map((c) => `<td>${cell(r, i, c)}</td>`).join("")}<td><button class="small danger" data-del="${i}">✕</button></td></tr>`).join("")}</table>
      <p><button class="small ghost" id="add">+ Add</button></p>
      ${tab === "incomes" || tab === "expenses" ? `<p class="muted" style="font-size:12px">Leave inflation blank to use the assumed rate (keeps its value in today's terms). One-off items happen once, at the "from" age.</p>` : ""}`;
    body.querySelectorAll("[data-r]").forEach((el) => {
      const col = spec.cols.find((c) => c[0] === el.dataset.c), t = Array.isArray(col[2]) ? "text" : col[2];
      el.oninput = el.onchange = () => { rows[+el.dataset.r][el.dataset.c] = read(el, t); if (tab === "pots") bindFields(); refresh(); };
    });
    body.querySelectorAll("[data-del]").forEach((b) => b.onclick = () => { rows.splice(+b.dataset.del, 1); renderTab(); refresh(); });
    document.getElementById("add").onclick = () => { rows.push(spec.blank(plan)); renderTab(); refresh(); };
  }
  document.querySelectorAll("[data-tab]").forEach((b) => b.onclick = () => { tab = b.dataset.tab; renderTab(); });
  renderTab();

  // Forecast.
  let chartMode = "wealth";
  document.querySelectorAll("[data-ch]").forEach((b) => b.onclick = () => {
    chartMode = b.dataset.ch; document.querySelectorAll("[data-ch]").forEach((x) => x.classList.toggle("on", x === b)); drawChart();
  });
  function effectivePlan() {
    const p = JSON.parse(JSON.stringify(plan)), adj = +gAdj.value / 100;
    if (adj) p.pots.forEach((x) => (x.growth_rate += adj));
    return p;
  }
  function refresh() {
    document.getElementById("inflOut").textContent = pct(plan.assumptions.inflation) + "%";
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try { forecast = await api("/api/project", { body: effectivePlan() }); document.getElementById("msg").textContent = ""; draw(); }
      catch (e) { document.getElementById("msg").textContent = e.message; }
    }, 150);
  }
  function draw() {
    const f = forecast, last = f.rows[f.rows.length - 1];
    const ret = plan.client.retirement_age, retRow = f.rows.find((r) => r.age === ret);
    const runOut = Object.entries(f.pots_run_out_at).filter(([, a]) => a != null);
    document.getElementById("kpis").innerHTML = `
      <div class="kpi"><span>Savings today</span><b>${gbp(f.rows[0]?.savings_start)}</b></div>
      ${retRow ? `<div class="kpi"><span>At retirement (${ret})</span><b>${gbp(retRow.savings_start)}</b></div>` : ""}
      <div class="kpi"><span>At age ${f.final_age}</span><b class="${f.final_savings < 0 ? "neg" : ""}">${gbp(f.final_savings)}</b></div>
      <div class="kpi"><span>Money runs out</span><b class="${f.assets_run_out_at ? "neg" : ""}">${f.assets_run_out_at ? "Age " + f.assets_run_out_at : "Never"}</b></div>`
      + (runOut.length ? `<div class="kpi" style="grid-column:1/-1"><span>Pots running out</span><div>${runOut.map(([id, a]) => `${esc(f.pot_names[id])}: age ${a}`).join(" · ")}</div></div>` : "");
    document.getElementById("years").innerHTML = `<tr><th>Age</th><th class="num">Start</th><th class="num">Income</th><th class="num">Spending</th><th class="num">Charges</th><th class="num">Tax</th><th class="num">End</th></tr>` +
      f.rows.map((r, i) => `<tr data-i="${i}" class="${i === selected ? "sel" : ""}"><td>${r.age}</td><td class="num">${gbp(r.savings_start)}</td><td class="num">${gbp(r.total_income + r.net_withdrawals)}</td>
        <td class="num">${gbp(r.total_expenses)}</td><td class="num">${gbp(r.total_charges)}</td><td class="num">${gbp(r.tax_paid)}</td><td class="num ${r.savings_end < 0 ? "neg" : ""}">${gbp(r.savings_end)}</td></tr>`).join("");
    document.querySelectorAll("#years tr[data-i]").forEach((tr) => tr.onclick = () => selectYear(+tr.dataset.i));
    drawChart();
    if (selected != null && f.rows[selected]) showDetail(selected);
  }
  function drawChart() {
    if (!forecast) return;
    const f = forecast, labels = f.rows.map((r) => r.age);
    const ids = Object.keys(f.pot_names);
    let datasets, stacked = true, type = "line";
    if (chartMode === "wealth" || chartMode === "pension") {
      const show = chartMode === "pension" ? ids.filter((id) => f.pot_types[id] === "pension") : ids;
      datasets = show.map((id, n) => ({ label: f.pot_names[id], data: f.rows.map((r) => Math.max(0, r.pots[id].closing)), fill: true,
        backgroundColor: COLOURS[n % COLOURS.length] + "cc", borderColor: COLOURS[n % COLOURS.length], pointRadius: 0, borderWidth: 1 }));
      if (chartMode === "wealth" && f.rows.some((r) => r.overdraft > 0))
        datasets.push({ label: "Shortfall", data: f.rows.map((r) => -r.overdraft), fill: true, backgroundColor: "#b3261e88", borderColor: "#b3261e", pointRadius: 0 });
    } else {
      type = "bar"; stacked = false;
      datasets = [
        { label: "Income", data: f.rows.map((r) => r.total_income), backgroundColor: "#3d9970" },
        { label: "Planned withdrawals", data: f.rows.map((r) => r.net_withdrawals), backgroundColor: "#4bacc6" },
        { label: "Drawn from savings", data: f.rows.map((r) => r.drawn_for_shortfall_net), backgroundColor: "#e0a030" },
        { label: "Expenditure", data: f.rows.map((r) => -r.total_expenses), backgroundColor: "#c0504d" }];
      stacked = true;
    }
    chart("ch", { type, data: { labels, datasets }, options: {
      responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: "index", intersect: false },
      scales: { x: { stacked, title: { display: true, text: "Age" } }, y: { stacked, ticks: { callback: (v) => gbp(v) } } },
      plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${gbp(c.raw)}` } }, legend: { position: "bottom", labels: { boxWidth: 12 } } },
      onClick: (e, els) => { if (els.length) selectYear(els[0].index); } } });
  }
  function selectYear(i) { selected = i; document.querySelectorAll("#years tr[data-i]").forEach((tr) => tr.classList.toggle("sel", +tr.dataset.i === i)); showDetail(i); }
  function showDetail(i) {
    const r = forecast.rows[i];
    document.getElementById("detail").innerHTML = `<h2>Age ${r.age} (${r.year}${r.fraction < 1 ? ", part year" : ""})</h2>
      <div class="kpis"><div class="kpi"><span>Income</span><b>${gbp(r.total_income)}</b></div><div class="kpi"><span>Spending</span><b>${gbp(r.total_expenses)}</b></div>
      <div class="kpi"><span>Surplus / shortfall</span><b class="${r.surplus_deficit < 0 ? "neg" : ""}">${gbp(r.surplus_deficit)}</b></div><div class="kpi"><span>Tax on withdrawals</span><b>${gbp(r.tax_paid)}</b></div></div>
      <div class="scroll"><table class="detail"><tr><th>Pot</th><th class="num">Opening</th><th class="num">Charges</th><th class="num">Paid in</th><th class="num">Withdrawn</th><th class="num">Growth</th><th class="num">Closing</th></tr>
      ${Object.entries(r.pots).map(([id, p]) => `<tr><td>${esc(forecast.pot_names[id])}</td><td class="num">${gbp(p.opening)}</td><td class="num">${gbp(p.charges)}</td>
        <td class="num">${gbp(p.contributions + p.surplus_saved)}</td><td class="num">${gbp(p.withdrawals_gross + p.drawn_for_shortfall_gross)}</td><td class="num">${gbp(p.growth)}</td><td class="num">${gbp(p.closing)}</td></tr>`).join("")}
      </table></div>${r.unfunded_shortfall > 0 ? `<p class="neg">Unfunded shortfall this year: ${gbp(r.unfunded_shortfall)}</p>` : ""}`;
  }

  // Saving.
  const msg = (t) => (document.getElementById("msg").textContent = t);
  async function saveAs(p, note) { await api(`/api/clients/${cid}/plans`, { body: { plan: p, note } }); }
  document.getElementById("save").onclick = async () => {
    try { const p = effectivePlan(); p.name = name; await saveAs(p, document.getElementById("note").value); location.reload(); } catch (e) { msg(e.message); }
  };
  document.getElementById("saveAs").onclick = async () => {
    const n = document.getElementById("scName").value.trim();
    if (!n) return msg("Give the scenario a name");
    if (client.plans.includes(n)) return msg("A forecast with that name already exists");
    const p = effectivePlan(); p.name = n;
    await saveAs(p, document.getElementById("note").value || `Scenario created from ${name}`);
    location.hash = `#/client/${cid}/plan/${encodeURIComponent(n)}`;
  };
  document.querySelectorAll("[data-q]").forEach((b) => b.onclick = async () => {
    const p = JSON.parse(JSON.stringify(base)); let n, note;
    if (b.dataset.q === "care") { n = "Long-term care from 85"; note = "£60,000 a year from age 85, rising with inflation";
      p.expenses.push({ name: "Long-term care", amount: 60000, frequency: "annual", start_age: 85, end_age: null, inflation: null, category: "care" }); }
    if (b.dataset.q === "infl") { n = "Inflation 4%"; note = "Inflation raised to 4%"; p.assumptions.inflation = 0.04; }
    if (b.dataset.q === "ret") { n = "Returns 2% lower"; note = "All growth rates 2% lower"; p.pots.forEach((x) => (x.growth_rate -= 0.02)); }
    if (client.plans.includes(n)) { location.hash = `#/client/${cid}/plan/${encodeURIComponent(n)}`; return; }
    p.name = n; await saveAs(p, note); location.hash = `#/client/${cid}/plan/${encodeURIComponent(n)}`;
  });

  refresh();
}

// ---------------------------------------------------------------- compare
async function compareView(cid) {
  const client = await api(`/api/clients/${cid}`);
  nav([["#/clients", "Clients", false], [`#/client/${cid}/plan/Baseline`, client.name, false],
       [`#/client/${cid}/compare`, "Compare scenarios", true], [`#/client/${cid}/audit`, "Audit trail", false]]);
  const fs = await api(`/api/clients/${cid}/compare`);
  $app.innerHTML = `<h1>Compare scenarios: ${esc(client.name)}</h1>
    <div class="panel"><div class="chart" style="height:380px"><canvas id="cmp"></canvas></div></div>
    <div class="panel"><table><tr><th>Forecast</th><th class="num">Savings today</th><th class="num">At age ${fs[0]?.final_age}</th><th>Money runs out</th><th>Pots running out</th></tr>
    ${fs.map((f) => `<tr><td><a href="#/client/${cid}/plan/${encodeURIComponent(f.plan_name)}">${esc(f.plan_name)}</a></td>
      <td class="num">${gbp(f.rows[0]?.savings_start)}</td><td class="num ${f.final_savings < 0 ? "neg" : ""}">${gbp(f.final_savings)}</td>
      <td>${f.assets_run_out_at ? "Age " + f.assets_run_out_at : "Never"}</td>
      <td>${Object.entries(f.pots_run_out_at).filter(([, a]) => a).map(([id, a]) => `${esc(f.pot_names[id])} (${a})`).join(", ") || "–"}</td></tr>`).join("")}</table></div>`;
  chart("cmp", { type: "line", data: { labels: fs[0]?.rows.map((r) => r.age) || [],
    datasets: fs.map((f, n) => ({ label: f.plan_name, data: f.rows.map((r) => r.savings_end), borderColor: COLOURS[n % COLOURS.length],
      backgroundColor: COLOURS[n % COLOURS.length], pointRadius: 0, borderWidth: f.plan_name === "Baseline" ? 3 : 2 })) },
    options: { responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: "index", intersect: false },
      scales: { x: { title: { display: true, text: "Age" } }, y: { ticks: { callback: (v) => gbp(v) } } },
      plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${gbp(c.raw)}` } }, legend: { position: "bottom" } } } });
}

// ---------------------------------------------------------------- audit
async function auditView(cid) {
  const client = await api(`/api/clients/${cid}`);
  nav([["#/clients", "Clients", false], [`#/client/${cid}/plan/Baseline`, client.name, false],
       [`#/client/${cid}/compare`, "Compare scenarios", false], [`#/client/${cid}/audit`, "Audit trail", true]]);
  const entries = (await api(`/api/clients/${cid}/audit`)).reverse();
  const fmt = (v) => (typeof v === "number" && Math.abs(v) < 1 && v !== 0 ? pct(v) + "%" : esc(v ?? "–"));
  $app.innerHTML = `<h1>Audit trail: ${esc(client.name)}</h1><div class="panel"><table>
    <tr><th>When (UTC)</th><th>What</th><th>Details</th></tr>
    ${entries.map((e) => { const d = e.detail; return `<tr><td style="white-space:nowrap">${esc(e.at.replace("T", " ").slice(0, 19))}</td>
      <td>${esc(e.action)}${d.plan ? `: ${esc(d.plan)} v${d.version}` : ""}</td><td>${d.note ? `<b>${esc(d.note)}</b><br>` : ""}
      ${d.result ? `Savings at ${d.result.final_age}: ${gbp(d.result.final_savings)}${d.impact_on_final_savings != null ? ` (${d.impact_on_final_savings >= 0 ? "+" : ""}${gbp(d.impact_on_final_savings)})` : ""}. ` : ""}
      ${d.changes?.length ? `<details><summary>${d.changes.length} change${d.changes.length > 1 ? "s" : ""}</summary><ul>${d.changes.map((c) => `<li>${esc(c.field)}: ${fmt(c.from)} → ${fmt(c.to)}</li>`).join("")}</ul></details>` : ""}</td></tr>`; }).join("")}
  </table></div>`;
}

route();
