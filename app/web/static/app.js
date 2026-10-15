// ELV Value Recovery front end. Displays engine output only; it computes no figures of its own.
"use strict";

const inr = (n) => n == null ? "–" : "INR " + Math.round(n).toLocaleString("en-IN");
const num = (n, d = 0) => n == null ? "–" : Number(n).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: d });
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const label = (s) => esc(String(s ?? "").replaceAll("_", " "));
const $ = (id) => document.getElementById(id);

const STATUS_TEXT = { green: "Compliant", amber: "Evidence gap", red: "Blocked" };
const pill = (status, text) => `<span class="pill ${esc(status)}">${esc(text ?? STATUS_TEXT[status] ?? status)}</span>`;
const approvalPill = (s) => s === "signed" ? pill("green", "Signed off") : s === "ready" ? pill("green", "Ready to sign") : pill("neutral", "Awaiting engineer");

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
let heroShown = null;
const calm = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

function countUp(el, to, suffix = "") {
  if (calm() || heroShown === to) { el.textContent = `${to}${suffix}`; return; }
  const from = heroShown ?? 0, t0 = performance.now(), dur = 700;
  const step = (t) => {
    const k = Math.min(1, (t - t0) / dur), e = 1 - (1 - k) ** 3;
    el.textContent = `${Math.round(from + (to - from) * e)}${suffix}`;
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function renderSummary(m, vehicles) {
  countUp($("hero-value"), m.gap_closed_pct, "%");
  heroShown = m.gap_closed_pct;
  const before = m.average_gap_scrap_only_inr, after = m.average_gap_inr;
  $("gapbars").innerHTML = `
    <div class="gapbar before"><span>Scrap only</span><div class="track"><div class="fill"></div></div><b>${inr(before)}</b></div>
    <div class="gapbar after"><span>With harvesting</span><div class="track"><div class="fill"></div></div><b>${inr(after)}</b></div>`;
  const fills = $("gapbars").querySelectorAll(".fill");
  void $("gapbars").offsetWidth;                 // lay out at 0 first, so the widths animate (works in background tabs too)
  fills[0].style.width = "100%";
  fills[1].style.width = `${Math.max(0, Math.min(100, 100 * after / before))}%`;
  initWhatIf(m);
  $("hero-note").innerHTML = `The informal scrapper outbids us by ${inr(m.average_gap_scrap_only_inr)} per vehicle on scrap value alone;
    harvesting cuts that to ${inr(m.average_gap_inr)}.`;
  const tiles = [
    ["Average offer, scrap only", inr(m.average_offer_scrap_only_inr), "metal, battery, converter, EPR"],
    ["Average offer, with harvesting", inr(m.average_offer_inr), "after the planned parts are sold"],
    ["Harvest gain this month", inr(m.harvest_gain_inr), "net of labour and scrap value lost"],
    ["Blocked before dismantling", m.blocked_before_dismantling.join(", ") || "None", "a dismantle-stage compliance rule fails"],
    ["Steel to recyclers", `${num(m.steel_to_recycler_kg)} kg`, "weighbridge basis for EPR"],
    ["CO₂ avoided by reuse", `${num(m.co2_avoided_kg)} kg`, "harvested parts reused, not made new"],
    ["Average gap, scrap only", inr(m.average_gap_scrap_only_inr), "informal offer minus RVSF offer"],
    ["Average gap, with harvesting", inr(m.average_gap_inr), "what the informal scrapper still pays more"],
    ["Open items", num(m.open_items), "engineer reviews and evidence gaps"],
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
const cardState = { f: "all", q: "", sort: "gap" };
const FILTERS = {
  all: () => true,
  ready: (v) => v.approval === "ready" || v.approval === "signed",
  open: (v) => v.open_items > 0 && v.compliance !== "red",
  blocked: (v) => v.compliance === "red",
};
const SORTS = {
  gap: (a, b) => b.gap_inr - a.gap_inr,
  closed: (a, b) => b.gap_closed_pct - a.gap_closed_pct,
  offer: (a, b) => b.offer_inr - a.offer_inr,
  id: (a, b) => a.vehicle_id.localeCompare(b.vehicle_id),
};

function cardBar(v) {
  const pct = (x) => Math.max(0, Math.min(100, 100 * x / v.informal_offer_inr));
  return `<div class="cbar" title="Scrap-only ${inr(v.offer_scrap_only_inr)} → with harvesting ${inr(v.offer_inr)}, against the informal ${inr(v.informal_offer_inr)}">
    <div class="track"><div class="gain" style="width:${pct(v.offer_inr)}%"></div><div class="scrap" style="width:${pct(v.offer_scrap_only_inr)}%"></div></div>
    <div class="cap"><span>${num(v.gap_closed_pct)}% of gap closed</span><span>informal ${inr(v.informal_offer_inr)}</span></div></div>`;
}

function renderCards(all) {
  for (const b of document.querySelectorAll("#card-filter button")) {
    b.querySelector("span").textContent = all.filter(FILTERS[b.dataset.f]).length;
    b.setAttribute("aria-pressed", String(b.dataset.f === cardState.f));
  }
  const q = cardState.q.trim().toLowerCase();
  const vehicles = all.filter(FILTERS[cardState.f])
    .filter((v) => !q || `${v.vehicle_id} ${v.segment} ${v.condition} ${v.compliance}`.toLowerCase().includes(q))
    .sort(SORTS[cardState.sort]);
  $("cards-empty").hidden = vehicles.length > 0;
  $("cards").innerHTML = vehicles.map((v) => `
    <button class="card" type="button" data-vid="${esc(v.vehicle_id)}">
      <div class="row1"><span class="vid">${esc(v.vehicle_id)}</span>${pill(v.compliance)}</div>
      <div class="meta">${esc(v.segment)} · ${esc(v.condition)}</div>
      <div class="offer">${inr(v.offer_inr)} <small>vs ${inr(v.informal_offer_inr)} informal</small></div>
      ${cardBar(v)}
      <div class="facts"><span>Gap left <b>${inr(v.gap_inr)}</b></span><span>Parts <b>${num(v.parts_harvested)}</b></span>
        <span>Open items <b>${num(v.open_items)}</b></span></div>
      <div>${approvalPill(v.approval)}</div>
      <div class="next">Next: <b>${esc(v.next_action)}</b></div>
    </button>`).join("");
  $("cards").querySelectorAll(".card").forEach((c) => c.addEventListener("click", () => openVehicle(c.dataset.vid)));
}

// ---- detail ----------------------------------------------------------------------------
async function openVehicle(vid) {
  openVid = vid;
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
    <th>Drawing</th><th>Verdict</th><th>Status</th><th>Next action</th><th>Flags</th><th>Inspector note</th></tr></thead><tbody>
    ${p.grading.map((g) => `<tr class="${g.needs_review ? "review" : ""}"><td>${esc(g.part_no)}</td><td class="num">${esc(g.measured_value)}</td>
      <td title="${esc(g.rule_source)}">${esc(g.limit)}${String(g.rule_source || "").startsWith("Gemini") ? " <span class=\"flag\">Gemini, approved</span>" : ""}</td>
      <td>${esc(g.drawing_no)}</td><td><b>${esc(g.verdict)}</b></td><td>${esc(g.status)}</td><td>${esc(g.next_action)}</td>
      <td>${(g.flags || "").split(",").filter(Boolean).map((f) => `<span class="flag">${label(f)}</span>`).join("")}</td>
      <td>${esc(g.inspector_note)}</td></tr>`).join("")}</tbody></table></div>
      <p class="caveat">Limits are demonstration rules, not production or legal requirements. Hover a limit to see which rule graded the part.</p>`
    : `<p class="muted">No starter or alternator harvested from this vehicle.</p>`;

  const rules = `<div class="table-wrap"><table><thead><tr><th>Rule</th><th>Result</th><th>Blocks</th><th>Detail</th><th>Source</th></tr></thead><tbody>
    ${c.rules.map((r) => `<tr><td>${esc(r.rule_id)} · ${esc(r.check)}</td>
      <td>${r.status === "fail" ? pill(r.severity === "red" ? "red" : "amber", "Fail") : r.status === "pass" ? pill("green", "Pass") : pill("neutral", "n/a")}</td>
      <td>${esc(r.stage)}</td><td>${esc(r.detail)}</td><td class="muted">${esc(r.source)}</td></tr>`).join("")}</tbody></table></div>
    <p class="caveat">Demo rule pack: simplified summaries with their source names, not legal advice. Gaps close only with evidence.</p>`;

  $("detail-body").innerHTML = `
    <div>${pill(c.status)} ${approvalPill(p.approval.status)}
      <span class="muted">· ${c.can_dismantle ? "may be dismantled" : "may not be dismantled"} · ${c.can_release ? "may be released" : "release on hold"}</span></div>
    <div class="next">Next action: <b>${esc(p.approval.next_action)}</b></div>
    <section class="detail-grid"><div><h2>How the offer is built</h2>${waterfall}</div><div><h2>Against the informal offer</h2>${compare}</div></section>
    <section><h2>Open items</h2>${open}</section>
    <section><h2>Components</h2>${comps}</section>
    <section><h2>Teardown grading</h2>${grading}</section>
    <section><h2>Compliance</h2>${rules}</section>
    ${planForm(p)}
    ${decisionsTable(p.decisions)}
    <section class="approval" id="approval">${approvalBlock(p)}</section>`;
  wireDetail(p);
}

const HARVESTABLE = new Set(["harvestable", "not_worth_it"]);

function planForm(p) {
  const opts = p.components.filter((c) => HARVESTABLE.has(c.status))
    .map((c) => `<option value="${esc(c.component)}">${label(c.component)} (${c.harvested ? "harvested" : "left on"})</option>`).join("");
  if (!opts) return "";
  return `<section class="decide"><h3>Change the plan</h3>
    <div class="decide-row"><select id="plan-comp" aria-label="Component">${opts}</select>
      <select id="plan-action" aria-label="Instruction"><option value="exclude">Exclude</option><option value="require">Require</option><option value="clear">Clear earlier instruction</option></select>
      <input id="plan-reason" type="text" placeholder="Reason (required)" maxlength="500" aria-label="Reason">
      <button class="primary" type="button" id="plan-go">Record</button></div>
    <div class="msg" id="plan-msg" role="status" aria-live="polite"></div></section>`;
}

const when = (at) => esc(String(at).replace("T", " ").replace("+00:00", ""));

function decisionsTable(ds) {
  if (!ds || !ds.length) return `<section><h2>Engineer decisions</h2><p class="muted">None recorded for this vehicle.</p></section>`;
  return `<section><h2>Engineer decisions</h2><div class="table-wrap"><table><thead><tr><th>When (UTC)</th><th>Engineer</th><th>Decision</th><th>Reason</th></tr></thead><tbody>
    ${ds.slice().reverse().map((d) => `<tr><td class="num">${when(d.at)}</td><td>${esc(d.engineer)}</td>
      <td>${esc(d.kind.replace("_", " "))} · ${esc(d.target || d.vehicle_id)} · ${esc(d.action)}</td><td>${esc(d.reason)}</td></tr>`).join("")}</tbody></table></div></section>`;
}

function approvalBlock(p) {
  const a = p.approval;
  if (a.status === "signed") return `<b>Signed off</b> by ${esc(a.engineer)} at ${when(a.signed_at)} UTC. Next: <b>${esc(a.next_action)}</b>.`;
  if (a.status === "ready") return `<div class="decide-row"><span><b>Nothing open.</b> Ready for an engineer to sign off.</span>
    <button class="primary" type="button" id="sign-go">Sign off ${esc(p.vehicle_id)}</button></div><div class="msg" id="sign-msg" role="status" aria-live="polite"></div>`;
  return `<b>Engineer sign-off:</b> pending until the open items are resolved. Agents and this screen explain; only an engineer decides.`;
}

function wireDetail(p) {
  const go = $("plan-go");
  if (go) go.addEventListener("click", () => decide({ kind: "harvest", vehicle_id: p.vehicle_id, target: $("plan-comp").value,
    action: $("plan-action").value, reason: $("plan-reason").value }, $("plan-msg")));
  const sign = $("sign-go");
  if (sign) sign.addEventListener("click", () => decide({ kind: "sign_off", vehicle_id: p.vehicle_id, action: "sign" }, $("sign-msg")));
}

$("detail-close").addEventListener("click", () => $("detail").close());
$("detail").addEventListener("click", (e) => { if (e.target === $("detail")) $("detail").close(); });

// ---- decisions ------------------------------------------------------------------------------
const engineer = $("engineer");
try { engineer.value = localStorage.getItem("elv-engineer") || ""; } catch (_) {}
engineer.addEventListener("change", () => { try { localStorage.setItem("elv-engineer", engineer.value.trim()); } catch (_) {} });

function say(el, text, ok) { if (el) { el.textContent = text; el.className = "msg " + (ok ? "ok" : "err"); } }

let lastNote = null;   // survives the re-render that follows a decision

async function decide(body, msgEl) {
  const who = engineer.value.trim();
  if (!who) { say(msgEl, "Enter your name in the Engineer box at the top first.", false); engineer.focus(); return false; }
  const r = await fetch("/api/decisions", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, engineer: who }) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { say(msgEl, data.detail || `Not recorded (${r.status}).`, false); return false; }
  const d = data.decision;
  const what = d.kind === "sign_off" ? `${d.vehicle_id} signed off` : `${d.vehicle_id || ""} ${d.target}: ${d.action.replace(":", " to ").replace("_", " ")}`.trim();
  lastNote = { id: msgEl && msgEl.id, text: `Recorded: ${what}, by ${d.engineer}. Result: ${data.outcome || "recorded"}.` };
  await loadAll();
  return true;
}

const ACTION_TEXT = { accept: "Approve the engine's verdict", request_review: "Request further inspection", "override:reuse": "Override: reuse",
  "override:replace": "Override: replace", "override:refurbish": "Override: refurbish", "override:scrap": "Override: scrap" };

function renderInbox(ib) {
  const reviews = ib.reviews.length ? ib.reviews.map((r, i) => `
    <div class="review-item">
      <div class="what"><b>${esc(r.vehicle_id)} · ${esc(r.part_no)}</b> · engine verdict <b>${esc(r.verdict)}</b>
        ${(r.flags || "").split(",").filter(Boolean).map((f) => `<span class="flag">${label(f)}</span>`).join("")}</div>
      <div class="why">${esc(r.reason)} Inspector note: "${esc(r.inspector_note)}"</div>
      <div class="next">Status: <b>${esc(r.status)}</b> · if approved, next: <b>${esc(r.next_if_accepted)}</b></div>
      <div class="decide-row">
        <select id="rv-act-${i}" aria-label="Decision for ${esc(r.vehicle_id)} ${esc(r.part_no)}">
          ${Object.entries(ACTION_TEXT).filter(([a]) => a !== "override:" + r.verdict).map(([a, t]) => `<option value="${a}">${esc(t)}</option>`).join("")}</select>
        <input id="rv-why-${i}" type="text" placeholder="Reason (required)" maxlength="500" aria-label="Reason">
        <button class="primary" type="button" data-i="${i}">Record</button>
      </div>
    </div>`).join("") : `<p class="muted">No parts waiting for review.</p>`;
  const ready = ib.ready_to_sign.length ? ib.ready_to_sign.map((v) => `
    <div class="sign-item"><span><b>${esc(v.vehicle_id)}</b> · ${inr(v.offer)} · ${pill(v.compliance)}</span>
      <button class="primary" type="button" data-sign="${esc(v.vehicle_id)}">Sign off</button></div>`).join("")
    : `<p class="muted">No vehicle is ready: each still has open items.</p>`;
  const signed = ib.signed.map((v) => `<div class="sign-item"><span><b>${esc(v.vehicle_id)}</b> signed by ${esc(v.engineer)}</span><span class="muted">${when(v.signed_at)}</span></div>`).join("");
  const recent = ib.recent.length ? `<div class="table-wrap"><table><thead><tr><th>When (UTC)</th><th>Engineer</th><th>Decision</th><th>Reason</th><th>Result now</th></tr></thead><tbody>
    ${ib.recent.map((d) => `<tr><td class="num">${when(d.at)}</td><td>${esc(d.engineer)}</td>
      <td>${esc(d.vehicle_id)} ${esc(d.target)} · ${esc(d.action)}</td><td>${esc(d.reason)}</td><td class="outcome">${esc(d.outcome)}</td></tr>`).join("")}</tbody></table></div>`
    : `<p class="muted">No decisions recorded yet.</p>`;

  $("inbox").innerHTML = `<div class="inbox-grid">
      <div><h3>Parts waiting for review (${ib.reviews.length})</h3>${reviews}</div>
      <div><h3>Ready to sign off (${ib.ready_to_sign.length})</h3>${ready}${signed ? `<h3 style="margin-top:14px">Signed off</h3>${signed}` : ""}</div>
    </div>
    <h3 style="margin-top:16px">Recent decisions</h3>${recent}`;

  $("inbox").querySelectorAll("button[data-i]").forEach((b) => b.addEventListener("click", () => {
    const r = ib.reviews[+b.dataset.i], i = b.dataset.i;
    decide({ kind: "part_review", vehicle_id: r.vehicle_id, target: r.part_no, action: $(`rv-act-${i}`).value,
      reason: $(`rv-why-${i}`).value }, $("inbox-msg"));
  }));
  $("inbox").querySelectorAll("button[data-sign]").forEach((b) => b.addEventListener("click", () =>
    decide({ kind: "sign_off", vehicle_id: b.dataset.sign, action: "sign" }, $("inbox-msg"))));
}

// ---- drawing rules: Gemini's readings, approved or rejected by an engineer ------------------------
function renderRules(rl) {
  $("rules-count").textContent = `· ${rl.pending} awaiting approval`;
  const STATE = { "pending approval": "neutral", approved: "green", rejected: "red", "failed the fixed checks": "amber", "no Gemini reading": "neutral" };
  $("rules").innerHTML = `<div class="table-wrap"><table><thead><tr><th>Part</th><th>Gemini read</th><th>Baseline</th>
    <th>Fixed checks</th><th>Status</th><th>Grades with</th><th>Decide</th></tr></thead><tbody>
    ${rl.rules.map((r, i) => `<tr class="rule-row"><td><b>${esc(r.part_no)}</b><br><span class="muted">${esc(r.drawing_no)}</span></td>
      <td>${esc(r.gemini || "–")} · ${esc(r.gemini_action || "")}<div class="rule-quote">"${esc(r.evidence || "")}"</div></td>
      <td>${esc(r.baseline)} · ${esc(r.baseline_action)}</td>
      <td>${r.gates === "checked" ? pill("green", "Passed") : pill("amber", "Failed")}${r.gate_problems ? `<div class="rule-quote">${esc(r.gate_problems)}</div>` : ""}</td>
      <td>${pill(STATE[r.state] || "neutral", r.state)}${r.decision ? `<div class="rule-quote">${esc(r.decision.engineer)}: ${esc(r.decision.reason)}</div>` : ""}</td>
      <td class="rule-quote">${esc(r.active_source)}</td>
      <td><div class="decide-row"><input id="rl-why-${i}" type="text" placeholder="Reason (required)" maxlength="500" aria-label="Reason for ${esc(r.part_no)}">
        <button class="primary" type="button" data-rule="${i}" data-act="approve" ${r.gates === "checked" && r.state !== "approved" ? "" : "disabled"}>Approve</button>
        <button class="ghost" type="button" data-rule="${i}" data-act="reject" ${r.gemini && r.state !== "rejected" ? "" : "disabled"}>Reject</button></div></td>
    </tr>`).join("")}</tbody></table></div>`;
  $("rules").querySelectorAll("button[data-rule]").forEach((b) => b.addEventListener("click", () => {
    const r = rl.rules[+b.dataset.rule];
    decide({ kind: "rule_review", vehicle_id: "", target: r.part_no, action: b.dataset.act,
      reason: $(`rl-why-${b.dataset.rule}`).value }, $("rules-msg"));
  }));
}

// ---- chat ------------------------------------------------------------------------------------
// Markdown from the agents: escape everything first, then allow a small, safe subset.
function inline(t) {
  return t.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/(^|[\s(])\*([^*\s][^*]*?)\*(?=[\s).,;:]|$)/g, "$1<i>$2</i>");
}
function renderMarkdown(md) {
  const out = []; let list = null;
  const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of esc(md).split(/\r?\n/)) {
    const line = raw.trimEnd();
    let m;
    if (!line.trim()) { close(); continue; }
    if (/^\s*(---|\*\*\*)\s*$/.test(line)) { close(); out.push("<hr>"); continue; }
    if ((m = line.match(/^\s*#{1,6}\s+(.*)$/))) { close(); out.push(`<h4>${inline(m[1])}</h4>`); continue; }
    if ((m = line.match(/^\s*[*-]\s+(.*)$/))) { if (list !== "ul") { close(); out.push("<ul>"); list = "ul"; } out.push(`<li>${inline(m[1])}</li>`); continue; }
    if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) { if (list !== "ol") { close(); out.push("<ol>"); list = "ol"; } out.push(`<li>${inline(m[1])}</li>`); continue; }
    close(); out.push(`<p>${inline(line)}</p>`);
  }
  close();
  return out.join("");
}

const CHIPS = [
  "Why is the starter on V05 waiting for an engineer?",
  "Is the alternator bearing on V08 OK to reuse?",
  "Can we dismantle V07?",
  "Which vehicle has the biggest gap to the informal scrapper before harvesting, and why?",
  "If we only have 620 technician minutes this month, what do we give up?",
  "What have engineers decided so far?",
];
let chatSid = null;
try { chatSid = sessionStorage.getItem("elv-chat") || null; } catch (_) {}

function addMsg(html, cls) {
  const el = document.createElement("div");
  el.className = cls; el.innerHTML = html;
  $("chat-log").appendChild(el);
  el.scrollIntoView({ block: "nearest" });
  return el;
}

async function ask(question) {
  const q = question.trim();
  if (!q) return;
  $("chat-q").value = "";
  $("chat-go").disabled = true;
  addMsg(esc(q), "msg-q");
  const pending = addMsg(`<span class="thinking">Asking the agents… 0 s</span>`, "msg-a");
  const t0 = Date.now();
  const timer = setInterval(() => { pending.querySelector(".thinking").textContent = `Asking the agents… ${Math.round((Date.now() - t0) / 1000)} s`; }, 1000);
  try {
    const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, session_id: chatSid }) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || `Error ${r.status}`);
    chatSid = d.session_id;
    try { sessionStorage.setItem("elv-chat", chatSid); } catch (_) {}
    const ground = d.ungrounded.length
      ? `<span class="ungrounded">Not found in tool results: ${d.ungrounded.map((n) => esc(n)).join(", ")}</span>`
      : `<span class="grounded">✓ Every number traced to a tool result</span>`;
    pending.innerHTML = renderMarkdown(d.answer) + `<div class="msg-meta">${ground}
      <span>Agents: ${esc(d.agents.join(" → ") || "elv_coordinator")}</span>
      <span>Tools: ${esc(d.tools.join(", ") || "none")}</span><span>${esc(d.seconds)} s</span></div>`;
  } catch (e) {
    pending.innerHTML = `<span class="ungrounded">${esc(e.message)}</span>`;
  } finally {
    clearInterval(timer);
    $("chat-go").disabled = false;
  }
}

$("chat-chips").innerHTML = CHIPS.map((c, i) => `<button class="chip" type="button" data-c="${i}">${esc(c)}</button>`).join("");
$("chat-chips").querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => ask(CHIPS[+b.dataset.c])));
$("chat-form").addEventListener("submit", (e) => { e.preventDefault(); ask($("chat-q").value); });
$("chat-new").addEventListener("click", () => {
  chatSid = null; $("chat-log").innerHTML = "";
  try { sessionStorage.removeItem("elv-chat"); } catch (_) {}
});

// ---- boot --------------------------------------------------------------------------------
let current = null, openVid = null;

async function loadAll() {
  const [data, ib, rl] = await Promise.all([getJSON("/api/month"), getJSON("/api/inbox"), getJSON("/api/rules")]);
  renderRules(rl);
  const waiting = ib.reviews.length + ib.ready_to_sign.length;
  $("nav-inbox").textContent = waiting ? String(waiting) : "";
  $("nav-inbox").title = `${ib.reviews.length} part(s) to review, ${ib.ready_to_sign.length} vehicle(s) ready to sign`;
  $("nav-rules").textContent = rl.pending ? String(rl.pending) : "";
  $("nav-rules").title = `${rl.pending} rule(s) awaiting approval`;
  current = data;
  renderSummary(data.month, data.vehicles);
  renderChart(data.vehicles);
  renderCards(data.vehicles);
  renderInbox(ib);
  if ($("detail").open && openVid) renderDetail(await getJSON(`/api/vehicles/${encodeURIComponent(openVid)}`));
  if (lastNote) {
    const el = (lastNote.id && $(lastNote.id)) || ($("detail").open ? $("approval") : $("inbox-msg"));
    if (el) { if (el.id === "approval") el.insertAdjacentHTML("beforeend", `<div class="msg ok">${esc(lastNote.text)}</div>`); else say(el, lastNote.text, true); }
    lastNote = null;
  }
}

// ---- overview interactions: stories, card tools, what-if ----------------------------------------
document.querySelectorAll(".story").forEach((b) => b.addEventListener("click", () => openVehicle(b.dataset.vid)));
$("card-filter").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-f]"); if (!b) return;
  cardState.f = b.dataset.f; if (current) renderCards(current.vehicles);
});
$("card-q").addEventListener("input", (e) => { cardState.q = e.target.value; if (current) renderCards(current.vehicles); });
$("card-sort").addEventListener("change", (e) => { cardState.sort = e.target.value; if (current) renderCards(current.vehicles); });

let wiReady = false, wiTimer = null, wiSeq = 0;
function initWhatIf(m) {
  const s = $("wi-min");
  if (!wiReady) { s.max = String(m.harvest_minutes); s.value = String(m.harvest_minutes); wiReady = true; runWhatIf(); }
  else if (+s.max !== m.harvest_minutes) { s.max = String(m.harvest_minutes); runWhatIf(); }
}
async function runWhatIf() {
  const minutes = +$("wi-min").value, seq = ++wiSeq;
  $("wi-min-out").textContent = `${num(minutes)} of ${num(+$("wi-min").max)}`;
  $("wi-out").classList.add("busy");
  try {
    const w = await getJSON(`/api/what-if?capacity_minutes=${minutes}`);
    if (seq !== wiSeq) return;                       // a newer drag has already asked
    $("wi-gap").textContent = `${w.gap_closed_pct}%`;
    $("wi-parts").textContent = num(w.parts_harvested);
    $("wi-gain").textContent = inr(w.harvest_gain_inr);
    $("wi-left").textContent = num(w.left_for_capacity.length);
  } catch (e) {
    if (seq === wiSeq) $("wi-gap").textContent = "–";
  } finally {
    if (seq === wiSeq) $("wi-out").classList.remove("busy");
  }
}
$("wi-min").addEventListener("input", () => {
  $("wi-min-out").textContent = `${num(+$("wi-min").value)} of ${num(+$("wi-min").max)}`;
  clearTimeout(wiTimer); wiTimer = setTimeout(runWhatIf, 250);
});

// ---- how it works: the two guided starts ------------------------------------------------------
$("how-start").addEventListener("click", () => openVehicle("V05"));
$("how-ask").addEventListener("click", () => {
  // the link switches to the Ask tab; the question goes once, not on every visit
  setTimeout(() => ask("Why is the starter on V05 waiting for an engineer?"), 0);
});

// ---- assistant: the same chat, borrowed by a side panel on any screen ---------------------------
function placeChat(slotId) { const box = $("chat-box"); if (box.parentElement.id !== slotId) $(slotId).appendChild(box); }

function openAssistant() {
  if (location.hash === "#ask") { $("chat-q").focus(); return; }   // already on the full Ask screen
  placeChat("drawer-slot");
  $("assistant").hidden = false;
  $("assistant-open").setAttribute("aria-expanded", "true");
  $("assistant-open").classList.add("active");
  $("chat-q").focus();
}

function closeAssistant() {
  if ($("assistant").hidden) return;
  $("assistant").hidden = true;
  $("assistant-open").setAttribute("aria-expanded", "false");
  $("assistant-open").classList.remove("active");
  placeChat("ask-slot");
  $("assistant-open").focus();
}

$("assistant-open").addEventListener("click", () => ($("assistant").hidden ? openAssistant() : closeAssistant()));
$("assistant-close").addEventListener("click", closeAssistant);
addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("assistant").hidden && !$("detail").open) closeAssistant(); });

// ---- tabs: one view at a time, driven by the URL hash so links and the back button work ----------
const VIEWS = ["overview", "inbox", "rules", "ask"];

function showView(name) {
  const view = VIEWS.includes(name) ? name : "overview";
  for (const v of VIEWS) {
    $(`view-${v}`).hidden = v !== view;
    const tab = document.querySelector(`.tabs a[data-view="${v}"]`);   // Ask has no tab: it opens from the corner button
    if (!tab) continue;
    if (v === view) tab.setAttribute("aria-current", "page"); else tab.removeAttribute("aria-current");
  }
  $("tooltip").hidden = true;
  if (view === "ask") closeAssistant();   // the Ask tab shows the same conversation full-width
  if (view === "overview" && current) renderChart(current.vehicles);   // its width is known only once visible
}

addEventListener("hashchange", () => { showView(location.hash.slice(1)); scrollTo(0, 0); });
showView(location.hash.slice(1));

(async function boot() {
  try {
    await loadAll();
    let w = innerWidth;
    addEventListener("resize", () => { if (current && Math.abs(innerWidth - w) > 40) { w = innerWidth; renderChart(current.vehicles); } });
  } catch (e) {
    $("cards").innerHTML = `<p>Could not load the month: ${esc(e.message)}</p>`;
  }
})();
