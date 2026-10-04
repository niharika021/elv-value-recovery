// ELV Value Recovery front end. Displays engine output only; it computes no figures of its own.
"use strict";

const inr = (n) => n == null ? "–" : "INR " + Math.round(n).toLocaleString("en-IN");
const num = (n, d = 0) => n == null ? "–" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const label = (s) => esc(String(s ?? "").replaceAll("_", " "));
const $ = (id) => document.getElementById(id);

const STATUS_TEXT = { green: "Compliant", amber: "Evidence gap", red: "Blocked" };
const pill = (status, text) => `<span class="pill ${esc(status)}">${esc(text ?? STATUS_TEXT[status] ?? status)}</span>`;
const approvalPill = (s) => s === "ready" ? pill("green", "Ready to sign") : pill("neutral", "Awaiting engineer");

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

// ---- theme ---------------------------------------------------------------------------
(function theme() {
  const root = document.documentElement;
  try { const t = localStorage.getItem("elv-theme"); if (t) root.dataset.theme = t; } catch (_) {}
  $("theme").addEventListener("click", () => {
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("elv-theme", root.dataset.theme); } catch (_) {}
  });
})();

// ---- summary --------------------------------------------------------------------------
function renderSummary(m, vehicles) {
  $("hero-value").textContent = `${m.gap_closed_pct}%`;
  $("hero-note").innerHTML = `Average gap ${inr(m.average_gap_scrap_only_inr)} with scrap only, ${inr(m.average_gap_inr)} with harvesting`;
  const review = vehicles.reduce((a, v) => a + v.open_items, 0);
  const tiles = [
    ["Average gap, scrap only", inr(m.average_gap_scrap_only_inr), "informal offer minus RVSF offer"],
    ["Average gap, with harvesting", inr(m.average_gap_inr), "after parts are pulled and sold"],
    ["Blocked before dismantling", m.blocked_before_dismantling.join(", ") || "None", "a dismantle-stage compliance rule fails"],
    ["Steel to recyclers", `${num(m.steel_to_recycler_kg)} kg`, "weighbridge basis for EPR"],
    ["CO₂ avoided by reuse", `${num(m.co2_avoided_kg)} kg`, "harvested parts reused, not made new"],
    ["Open items", num(review), "for engineer review or evidence"],
  ];
  $("tiles").innerHTML = tiles.map(([l, v, n]) =>
    `<div class="tile"><div class="label">${esc(l)}</div><div class="value">${esc(v)}</div><div class="note">${esc(n)}</div></div>`).join("");
}

// ---- chart: one row per vehicle, scrap-only -> with harvest, against the informal offer ----
function renderChart(vehicles) {
  $("legend").innerHTML = `
    <span class="key"><span class="dot" style="background:var(--series-2)"></span>Scrap-only offer</span>
    <span class="key"><span class="dot" style="background:var(--series-1)"></span>Offer with harvesting</span>
    <span class="key"><span class="tick"></span>Informal scrapper's offer</span>`;

  const el = $("chart");
  const W = Math.max(320, el.clientWidth), rowH = 30, top = 8, bottom = 28;
  const left = W < 520 ? 70 : 150, right = 16, H = top + rowH * vehicles.length + bottom;
  const vals = vehicles.flatMap((v) => [v.offer_scrap_only_inr, v.offer_inr, v.informal_offer_inr]);
  const step = 10000, lo = Math.floor(Math.min(...vals) / step) * step, hi = Math.ceil(Math.max(...vals) / step) * step;
  const x = (v) => left + (v - lo) / (hi - lo) * (W - left - right);

  let s = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true">`;
  for (let t = lo; t <= hi; t += step) {
    s += `<line class="gridline" x1="${x(t)}" x2="${x(t)}" y1="${top}" y2="${H - bottom}"/>`;
    s += `<text class="axis-label" x="${x(t)}" y="${H - bottom + 16}" text-anchor="middle">${(t / 1000).toLocaleString("en-IN")}k</text>`;
  }
  vehicles.forEach((v, i) => {
    const cy = top + rowH * i + rowH / 2;
    const name = W < 520 ? v.vehicle_id : `${v.vehicle_id}  ${v.segment}`;
    s += `<g class="row" data-i="${i}" tabindex="0" role="button" aria-label="${esc(v.vehicle_id)} details">`;
    s += `<rect class="hit" x="0" y="${cy - rowH / 2}" width="${W}" height="${rowH}" rx="4"/>`;
    s += `<text class="row-label" x="8" y="${cy + 4}">${esc(name)}</text>`;
    s += `<line class="gap" x1="${x(v.offer_inr)}" x2="${x(v.informal_offer_inr)}" y1="${cy}" y2="${cy}"/>`;
    s += `<line class="link" x1="${x(v.offer_scrap_only_inr)}" x2="${x(v.offer_inr)}" y1="${cy}" y2="${cy}"/>`;
    s += `<line class="m-informal" x1="${x(v.informal_offer_inr)}" x2="${x(v.informal_offer_inr)}" y1="${cy - 8}" y2="${cy + 8}"/>`;
    s += `<circle class="m-scrap" cx="${x(v.offer_scrap_only_inr)}" cy="${cy}" r="5"/>`;
    s += `<circle class="m-offer" cx="${x(v.offer_inr)}" cy="${cy}" r="5"/>`;
    s += `</g>`;
  });
  el.innerHTML = s + "</svg>";

  const tip = $("tooltip");
  el.querySelectorAll(".row").forEach((g) => {
    const v = vehicles[+g.dataset.i];
    const show = (cx, cy) => {
      tip.innerHTML = `<div class="t-head">${esc(v.vehicle_id)} · ${esc(v.segment)}</div>
        <div class="t-row"><span>Informal offer</span><span>${inr(v.informal_offer_inr)}</span></div>
        <div class="t-row"><span>Scrap-only offer</span><span>${inr(v.offer_scrap_only_inr)}</span></div>
        <div class="t-row"><span>Offer with harvesting</span><span>${inr(v.offer_inr)}</span></div>
        <div class="t-row"><span>Gap left</span><span>${inr(v.gap_inr)}</span></div>
        <div class="t-row"><span>Compliance</span><span>${esc(STATUS_TEXT[v.compliance])}</span></div>`;
      tip.hidden = false;
      const r = tip.getBoundingClientRect();
      tip.style.left = Math.min(cx + 14, innerWidth - r.width - 8) + "px";
      tip.style.top = Math.max(8, cy - r.height - 10) + "px";
    };
    g.addEventListener("mousemove", (e) => show(e.clientX, e.clientY));
    g.addEventListener("mouseleave", () => { tip.hidden = true; });
    g.addEventListener("focus", () => { const b = g.getBoundingClientRect(); show(b.left + b.width / 2, b.top); });
    g.addEventListener("blur", () => { tip.hidden = true; });
    g.addEventListener("click", () => openVehicle(v.vehicle_id));
    g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openVehicle(v.vehicle_id); } });
  });

  $("chart-table").innerHTML = `<table><thead><tr><th>Vehicle</th><th>Segment</th><th class="num">Informal</th>
    <th class="num">Scrap-only</th><th class="num">With harvesting</th><th class="num">Gap left</th><th class="num">Gap closed</th></tr></thead><tbody>
    ${vehicles.map((v) => `<tr><td>${esc(v.vehicle_id)}</td><td>${esc(v.segment)}</td><td class="num">${inr(v.informal_offer_inr)}</td>
      <td class="num">${inr(v.offer_scrap_only_inr)}</td><td class="num">${inr(v.offer_inr)}</td><td class="num">${inr(v.gap_inr)}</td>
      <td class="num">${num(v.gap_closed_pct)}%</td></tr>`).join("")}</tbody></table>`;
}

$("table-toggle").addEventListener("click", (e) => {
  const showTable = $("chart-table").hidden;
  $("chart-table").hidden = !showTable;
  $("chart").hidden = showTable;
  e.currentTarget.setAttribute("aria-pressed", String(showTable));
  e.currentTarget.textContent = showTable ? "Show chart" : "Show table";
});

// ---- cards -----------------------------------------------------------------------------
function renderCards(vehicles) {
  $("cards").innerHTML = vehicles.map((v) => `
    <button class="card" type="button" data-vid="${esc(v.vehicle_id)}">
      <div class="row1"><span class="vid">${esc(v.vehicle_id)}</span>${pill(v.compliance)}</div>
      <div class="meta">${esc(v.segment)} · ${esc(v.condition)}</div>
      <div class="offer">${inr(v.offer_inr)} <small>vs ${inr(v.informal_offer_inr)} informal</small></div>
      <div class="facts"><span>Gap left <b>${inr(v.gap_inr)}</b></span><span>Parts <b>${num(v.parts_harvested)}</b></span>
        <span>Open items <b>${num(v.open_items)}</b></span></div>
      <div>${approvalPill(v.approval)}</div>
    </button>`).join("");
  $("cards").querySelectorAll(".card").forEach((c) => c.addEventListener("click", () => openVehicle(c.dataset.vid)));
}

// ---- detail ----------------------------------------------------------------------------
async function openVehicle(vid) {
  const dlg = $("detail");
  $("detail-title").textContent = vid;
  $("detail-body").innerHTML = `<p class="muted">Loading…</p>`;
  if (!dlg.open) dlg.showModal();
  try {
    renderDetail(await getJSON(`/api/vehicles/${encodeURIComponent(vid)}`));
  } catch (e) {
    $("detail-body").innerHTML = `<p>Could not load ${esc(vid)}: ${esc(e.message)}</p>`;
  }
}

function renderDetail(p) {
  const v = p.value, veh = p.vehicle, c = p.compliance;
  $("detail-title").innerHTML = `${esc(p.vehicle_id)} <span class="sub">${esc(veh.segment)} · ${esc(veh.condition)} · ${esc(veh.model_year)}</span>`;

  const waterfall = `<table class="waterfall"><tbody>
    <tr><td>Metal in the shredder stream</td><td class="num">${inr(v.metal_value)}</td></tr>
    <tr><td>Battery and catalytic converter</td><td class="num">${inr(v.always_removed_value)}</td></tr>
    <tr><td>EPR certificate</td><td class="num">${inr(v.epr)}</td></tr>
    <tr><td>Harvested parts, net of labour and scrap value lost</td><td class="num">${inr(v.harvest_gain)}</td></tr>
    <tr class="total"><td>Revenue</td><td class="num">${inr(v.revenue)}</td></tr>
    <tr><td>Processing cost</td><td class="num">−${inr(v.processing)}</td></tr>
    <tr><td>Margin</td><td class="num">−${inr(v.margin)}</td></tr>
    <tr class="total"><td>Offer to the owner</td><td class="num">${inr(v.offer)}</td></tr>
  </tbody></table>`;
  const compare = `<table><tbody>
    <tr><td>Informal scrapper's offer</td><td class="num">${inr(v.informal_offer)}</td></tr>
    <tr><td>Scrap-only offer</td><td class="num">${inr(v.offer_scrap_only)}</td></tr>
    <tr><td>Gap left</td><td class="num">${inr(v.gap)}</td></tr>
    <tr><td>Gap closed by harvesting</td><td class="num">${num(v.gap_closed_pct, 1)}%</td></tr>
    <tr><td>Steel to the recycler</td><td class="num">${num(v.steel_to_recycler_kg, 1)} kg</td></tr>
    <tr><td>CO₂ avoided by reuse</td><td class="num">${num(v.co2_avoided_kg, 1)} kg</td></tr>
    <tr><td>Technician minutes</td><td class="num">${num(p.plan.minutes)}</td></tr>
  </tbody></table>`;

  const open = p.open_items.length
    ? `<ul class="open-items">${p.open_items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>`
    : `<p class="muted">Nothing open.</p>`;

  const comps = `<div class="table-wrap"><table><thead><tr><th>Component</th><th>Grade</th><th class="num">Net</th>
    <th>Decision</th><th>Why</th><th>Teardown</th></tr></thead><tbody>
    ${p.components.map((r) => `<tr><td>${label(r.component)}</td><td>${esc(r.grade)}</td><td class="num">${inr(r.net)}</td>
      <td>${r.harvested ? "<b>Harvest</b>" : label(r.status)}</td><td>${esc(r.why)}</td><td>${esc(r.teardown || "")}</td></tr>`).join("")}
    </tbody></table></div>`;

  const grading = p.grading.length ? `<div class="table-wrap"><table><thead><tr><th>Part</th><th>Measured</th><th>Limit</th>
    <th>Drawing</th><th>Verdict</th><th>Flags</th><th>Inspector note</th></tr></thead><tbody>
    ${p.grading.map((g) => `<tr class="${g.needs_review ? "review" : ""}"><td>${esc(g.part_no)}</td><td class="num">${esc(g.measured_value)}</td>
      <td>${esc(g.limit)}</td><td>${esc(g.drawing_no)}</td><td>${g.needs_review ? "<b>" + esc(g.verdict) + "</b> · review" : esc(g.verdict)}</td>
      <td>${(g.flags || "").split(",").filter(Boolean).map((f) => `<span class="flag">${label(f)}</span>`).join("")}</td>
      <td>${esc(g.inspector_note)}</td></tr>`).join("")}</tbody></table></div>`
    : `<p class="muted">No starter or alternator harvested from this vehicle.</p>`;

  const rules = `<div class="table-wrap"><table><thead><tr><th>Rule</th><th>Result</th><th>Blocks</th><th>Detail</th><th>Source</th></tr></thead><tbody>
    ${c.rules.map((r) => `<tr><td>${esc(r.rule_id)} · ${esc(r.check)}</td>
      <td>${r.status === "fail" ? pill(r.severity === "red" ? "red" : "amber", "Fail") : r.status === "pass" ? pill("green", "Pass") : pill("neutral", "n/a")}</td>
      <td>${esc(r.stage)}</td><td>${esc(r.detail)}</td><td class="muted">${esc(r.source)}</td></tr>`).join("")}</tbody></table></div>`;

  $("detail-body").innerHTML = `
    <div>${pill(c.status)} ${approvalPill(p.approval.status)}
      <span class="muted">· ${c.can_dismantle ? "may be dismantled" : "may not be dismantled"} · ${c.can_release ? "may be released" : "release on hold"}</span></div>
    <section class="detail-grid"><div><h2>How the offer is built</h2>${waterfall}</div><div><h2>Against the informal offer</h2>${compare}</div></section>
    <section><h2>Open items</h2>${open}</section>
    <section><h2>Components</h2>${comps}</section>
    <section><h2>Teardown grading</h2>${grading}</section>
    <section><h2>Compliance</h2>${rules}</section>
    <section class="approval"><b>Engineer sign-off:</b> ${p.approval.status === "ready" ? "nothing open; ready to sign" : "pending until the open items are resolved"}.
      Agents and this screen explain; only an engineer decides.</section>`;
}

$("detail-close").addEventListener("click", () => $("detail").close());
$("detail").addEventListener("click", (e) => { if (e.target === $("detail")) $("detail").close(); });

// ---- boot --------------------------------------------------------------------------------
(async function boot() {
  try {
    const data = await getJSON("/api/month");
    renderSummary(data.month, data.vehicles);
    renderChart(data.vehicles);
    renderCards(data.vehicles);
    let w = innerWidth;
    addEventListener("resize", () => { if (Math.abs(innerWidth - w) > 40) { w = innerWidth; renderChart(data.vehicles); } });
  } catch (e) {
    $("cards").innerHTML = `<p>Could not load the month: ${esc(e.message)}</p>`;
  }
})();
