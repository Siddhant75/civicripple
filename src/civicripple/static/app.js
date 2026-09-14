/* CivicRipple — calm operations app. Vanilla JS, no build step. */

const $ = (sel) => document.querySelector(sel);
const state = { incidents: [], selected: null, cloud: false, watch: null, openRun: null };

const STATE_LABEL = {
  DETECTED: "Detected",
  EXTRACTED: "Extracted",
  VERIFIED: "Verified",
  IMPACT_ASSESSED: "Impact assessed",
  NO_IMPACT: "No impact",
  ROUTE_REQUESTED: "Requesting detour",
  CANDIDATE_REJECTED: "Detour rejected",
  CANDIDATE_VALIDATED: "Detour validated",
  FEASIBLE: "Feasible",
  INFEASIBLE: "Infeasible",
  POLICY_EVALUATED: "Policy applied",
  AUTO_APPROVED: "Auto-approved",
  REVIEW_REQUIRED: "Needs your decision",
  HUMAN_APPROVED: "Approved by you",
  HUMAN_REJECTED: "Rejected by you",
  RESOLVED: "Resolved",
  OPEN: "Open",
};

function esc(s) {
  const d = document.createElement("div");
  d.textContent = String(s ?? "");
  return d.innerHTML;
}

function statePill(s) {
  const cls = s === "REVIEW_REQUIRED" ? "needs" : ["OPEN", "INFEASIBLE", "CANDIDATE_REJECTED"].includes(s) ? "bad" : "quiet";
  return `<span class="state ${cls}">${esc(STATE_LABEL[s] || s)}</span>`;
}

function ago(iso) {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const h = Math.floor(mins / 60);
  return `${h}h ${mins % 60}m ago`;
}

function banner(msg) {
  const slot = $("#banner-slot");
  slot.innerHTML = `<div class="error-banner">${esc(msg)}</div>`;
  setTimeout(() => { slot.innerHTML = ""; }, 6000);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

/* ---------------- watch ---------------- */

async function refreshWatch() {
  try {
    state.watch = await api("/watch");
  } catch {
    return;
  }
  const pill = $("#watch-pill");
  if (state.watch.enabled) {
    pill.textContent = "on watch";
    pill.className = "pill on";
  } else {
    pill.textContent = "watch off";
    pill.className = "pill quiet";
  }
  if (document.querySelector("nav .active")?.dataset.view === "watch") renderWatch();
}

/* ---------------- data ---------------- */

async function refresh() {
  try {
    const mode = await api("/mode");
    $("#mode-badge").textContent =
      mode.mode === "aws" ? `AWS · ${mode.region}` : "local replay";
    state.incidents = (await api("/incidents")).incidents;
    state.ops = await api(`/operations/op-demo-2026-09-03`).catch(() => null);
  } catch (err) {
    banner(`Cannot reach the service: ${err.message}`);
  }
  render();
}

/* ---------------- views ---------------- */

function current() {
  return document.querySelector("nav .active").dataset.view;
}

function render() {
  const view = current();
  if (view === "watch") renderWatch();
  else if (view === "today") renderToday();
  else if (view === "incident") renderIncident();
  else renderAudit();
}

function showView(name) {
  document.querySelectorAll("nav button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === name));
  render();
}

/* ---- On watch ---- */

const DOT = { observed: "observed", extracting: "extracting", escalated: "escalated", failed: "failed" };

function renderWatch() {
  const w = state.watch || { enabled: false, watching: "", items: [] };
  let body;
  if (!w.enabled) {
    body = `<p class="sub">The watch loop is off. Start the service with <span class="mono">WATCH_ENABLED=1</span> and it will scan the WSDOT feed every few minutes.</p>`;
  } else {
    body = w.items.length
      ? `<div class="feed">${w.items.map((it) => {
          const key = it.status.split(":")[0];
          const dot = DOT[key] || "classified";
          const corr = `watch-${esc(it.hash)}`;
          const open = state.openRun === corr;
          return `<div class="feed-row" data-hash="${esc(it.hash)}">
            <span class="t mono">${esc(new Date(it.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }))}</span>
            <span class="dot ${dot}"></span>
            <div class="feed-main">
              ${(key === "classified" || key === "escalated")
                ? `<a href="#" class="watch-link" data-corr="${corr}">${esc(it.title || it.status)}</a>`
                : esc(it.title || it.status)}
              <div class="muted">${esc(it.status.replace("classified:", "classified "))} · ${esc(ago(it.at))}</div>
              ${open ? `<div class="run-viewer" id="run-${esc(it.hash)}"><span class="muted">loading run…</span></div>` : ""}
            </div>
            ${["observed", "extracting", "classified", "escalated"].includes(key)
              ? `<button class="ghost run-toggle" data-hash="${esc(it.hash)}">${open ? "hide run" : "show run"}</button>` : ""}
          </div>`;
        }).join("")}</div>`
      : `<p class="sub">Watching the WSDOT feed — nothing new yet.</p>`;
  }
  $("#view").innerHTML = `
    <h1>On watch</h1>
    <p class="sub">The agent scans <span class="mono">${esc(w.watching)}</span> unattended and works each new notice end to end. It interrupts you only when a decision is needed.</p>
    ${body}
    <div id="report-slot"></div>`;
  if (w.enabled) loadReport();
  document.querySelectorAll("button.run-toggle").forEach((b) =>
    b.onclick = () => {
      state.openRun = state.openRun === `watch-${b.dataset.hash}` ? null : `watch-${b.dataset.hash}`;
      renderWatch();
    });
  document.querySelectorAll(".watch-link").forEach((a) =>
    a.onclick = (e) => {
      e.preventDefault();
      state.selected = a.dataset.corr;
      showView("incident");
    });
  pollOpenRun();
}

async function loadReport() {
  try {
    const r = await api("/report");
    const slot = $("#report-slot");
    if (!slot) return;
    slot.innerHTML = `
      <h2>This watch session</h2>
      <div class="cards">
        <div class="card stat"><div class="num">${r.watched}</div>notices worked</div>
        <div class="card stat"><div class="num">${r.auto_resolved}</div>auto-resolved</div>
        <div class="card stat needs"><div class="num">${r.escalated}</div>escalated to you</div>
        <div class="card stat"><div class="num">${r.false_interventions}</div>false alarms</div>
      </div>`;
  } catch {}
}

let runPoll = null;

function pollOpenRun() {
  if (runPoll) { clearInterval(runPoll); runPoll = null; }
  if (!state.openRun) return;
  const corr = state.openRun;
  const draw = async () => {
    const box = document.getElementById(`run-${corr.replace("watch-", "")}`);
    if (!box) { clearInterval(runPoll); runPoll = null; return; }
    try {
      const { events } = await api(`/audit/${corr}`);
      box.innerHTML = `<ol class="timeline mini">
        ${events.map((e, idx) => `<li class="${idx === events.length - 1 ? "live" : ""}">
          <strong>${esc(e.node)}</strong> — ${esc(STATE_LABEL[e.state_to] || e.state_to)}
          <span class="muted mono">${esc(new Date(e.recorded_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }))}</span>
        </li>`).join("")}</ol>`;
    } catch {}
  };
  draw();
  runPoll = setInterval(draw, 2000);
}

/* ---- Today ---- */

function incidentCard(i) {
  const needs = i.state === "REVIEW_REQUIRED";
  const failed = i.review_payload?.failed_constraints?.length
    ? `${i.review_payload.failed_constraints.length} failed constraint${i.review_payload.failed_constraints.length > 1 ? "s" : ""}`
    : "";
  return `<div class="card clickable ${needs ? "needs" : ""}" data-corr="${esc(i.correlation_id)}">
    <div>${esc(i.correlation_id)} ${statePill(i.state)}</div>
    <div class="muted">
      ${i.decision ? esc(i.decision.classification.replace(/_/g, " ").toLowerCase()) : ""}
      ${i.decision?.review_reason ? " — " + esc(i.decision.review_reason.replace(/_/g, " ").toLowerCase()) : ""}
      ${failed ? " — " + esc(failed) : ""}
    </div>
  </div>`;
}

function renderToday() {
  const needs = state.incidents.filter((i) => i.state === "REVIEW_REQUIRED");
  const auto = state.incidents.filter((i) => i.state === "RESOLVED");
  const ops = state.ops;
  const deliveries = ops ? ops.routes.reduce((n, r) => n + r.stops.length, 0) : 0;
  const drivers = ops ? new Set(ops.routes.map((r) => r.driver_id)).size : 0;
  $("#view").innerHTML = `
    <h1>Today's service</h1>
    <p class="sub">${ops ? `${deliveries} deliveries, ${ops.routes.length} routes, ${drivers} volunteer drivers` : "Loading the operation plan…"}</p>
    ${needs.length ? `<h2>Needs your decision</h2>${needs.map(incidentCard).join("")}` : ""}
    <h2>Handled by the agent</h2>
    ${auto.length ? auto.map(incidentCard).join("") : `<p class="sub">Nothing yet — the agent resolves what it safely can and tells you here.</p>`}
    <h2>Try a scenario</h2>
    <p class="muted"><label><input type="checkbox" id="cloud-toggle" ${state.cloud ? "checked" : ""}> run on the deployed cloud agent (real Bedrock + routing)</label></p>
    ${["no_impact", "feasible_reroute", "infeasible_reroute", "avoidance_failure"].map((s) =>
      `<button class="ghost replay" data-scenario="${s}">${s.replace(/_/g, " ")}</button>`).join(" ")}`;
  $("#cloud-toggle").onchange = (e) => { state.cloud = e.target.checked; };
  document.querySelectorAll("button.replay").forEach((b) =>
    b.onclick = async () => {
      const corr = `incident-${b.dataset.scenario}-${Date.now()}`;
      const send = (extra) => api(`/incidents/${corr}/replay`, {
        method: "POST",
        body: JSON.stringify({ scenario: b.dataset.scenario, remote: state.cloud, ...extra }),
        headers: { "content-type": "application/json" },
      });
      try {
        await send({ live: true });
      } catch (err) {
        if (!state.cloud && String(err.message).startsWith("502")) {
          // Designed degradation, visible to the user — never silent.
          banner("Live model unavailable — running the scripted replay instead.");
          try {
            await send({ live: false });
          } catch (err2) { banner(`Replay failed — ${err2.message}`); return; }
        } else { banner(`Replay failed — ${err.message}`); return; }
      }
      refresh();
    });
  document.querySelectorAll(".card.clickable").forEach((el) =>
    el.onclick = () => { state.selected = el.dataset.corr; showView("incident"); });
}

/* ---- Incident (map-first) ---- */

let map = null, mapLayer = null;
const latlng = (c) => [c[1], c[0]];

function drawMap(snap) {
  const box = $("#mapbox");
  if (!box) return;
  box.style.height = "560px";
  if (!map || !map.getContainer().isConnected) {
    if (map) map.remove();
    map = L.map(box);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap" }).addTo(map);
    mapLayer = L.layerGroup().addTo(map);
  }
  mapLayer.clearLayers();
  setTimeout(() => map.invalidateSize(), 40);

  const bounds = [latlng([snap.depot.lon, snap.depot.lat])];
  L.marker(latlng([snap.depot.lon, snap.depot.lat])).bindTooltip("Depot").addTo(mapLayer);

  for (const stop of snap.stops) {
    const pos = latlng([stop.location.lon, stop.location.lat]);
    bounds.push(pos);
    const late = stop.projected_arrival && new Date(stop.projected_arrival) > new Date(stop.window_end);
    const color = late ? "#b3261e" : stop.projected_arrival ? "#1f6f54" : "#9aa4a1";
    L.circleMarker(pos, { radius: 8, color, fill: true, fillOpacity: 0.92, weight: 2 })
      .bindTooltip(`${stop.stop_id}${late ? " — late" : ""}`)
      .addTo(mapLayer);
  }
  for (const leg of snap.legs) {
    if (!leg.coordinates.length) continue;
    const pts = leg.coordinates.map(latlng);
    bounds.push(...pts);
    L.polyline(pts, {
      color: leg.affected ? "#b3261e" : "#9aa4a1",
      weight: leg.affected ? 5 : 3,
      opacity: leg.affected ? 0.9 : 0.55,
    }).addTo(mapLayer);
  }
  if (snap.disruption_geometry?.kind === "Polygon") {
    const ring = snap.disruption_geometry.coordinates[0].map(latlng);
    bounds.push(...ring);
    L.polygon(ring, { color: "#b45309", dashArray: "6 6", fillOpacity: 0.18 }).bindTooltip("Road closure").addTo(mapLayer);
  }
  if (snap.candidate_geometry?.kind === "LineString") {
    L.polyline(snap.candidate_geometry.coordinates.map(latlng), { color: "#1f6f54", weight: 4 })
      .bindTooltip("Agent's detour").addTo(mapLayer);
  }
  map.fitBounds(bounds, { padding: [28, 28] });
}

function timeOrDash(iso) {
  return iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—";
}

function renderIncident() {
  const corr = state.selected;
  if (!corr) {
    $("#view").innerHTML = `<h1>Incident</h1><p class="sub">Choose one from Today, or watch the feed.</p>`;
    return;
  }
  const i = state.incidents.find((x) => x.correlation_id === corr);
  if (!i) { $("#view").innerHTML = `<h1>Incident</h1><p class="sub">Not found.</p>`; return; }
  const p = i.review_payload;
  const snap = i.map;

  const constraints = p?.failed_constraints?.length
    ? p.failed_constraints.map((v) =>
        `<div class="card"><span class="state bad">${esc(v.code.replace(/_/g, " ").toLowerCase())}</span>
         <strong>${esc(v.stop_id)}</strong> arrives <span class="mono">${timeOrDash(v.stop_id && i.map ? projectedOf(v.stop_id) : "")}</span>,
         <span class="mono">${v.lateness_s}s</span> past the promised window.</div>`).join("")
    : "";

  $("#view").innerHTML = `
    <h1>${esc(i.correlation_id)} ${statePill(i.state)}</h1>
    <div class="split">
      <div id="mapbox"></div>
      <div>
        <h2>What the agent found</h2>
        <div class="card">
          ${i.decision ? `<div><strong>${esc(i.decision.classification.replace(/_/g, " ").toLowerCase())}</strong>
            ${i.decision.review_reason ? `<div class="muted">${esc(i.decision.review_reason.replace(/_/g, " ").toLowerCase())}</div>` : ""}</div>` : ""}
          ${p?.affected_stop_ids?.length ? `<div class="muted" style="margin-top:6px">Affected: ${p.affected_stop_ids.map(esc).join(", ")}</div>` : ""}
          ${i.options ? `<div style="margin-top:8px">${i.options.options.map((o) => `<div>• ${esc(o.title)}</div>`).join("")}</div>` : ""}
        </div>
        ${constraints ? `<h2>Failed constraints</h2>${constraints}` : ""}
      </div>
    </div>
    <div id="whatif-slot"></div>`;
  if (snap) drawMap(snap);
  if (i.state === "REVIEW_REQUIRED") renderWhatIf(i);
}

function projectedOf(stopId) {
  const i = state.incidents.find((x) => x.correlation_id === state.selected);
  const arr = i?.map?.stops?.find((s) => s.stop_id === stopId)?.projected_arrival;
  return arr ? new Date(arr).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";
}

/* ---- What-if console ---- */

let chosenVariant = null;

function renderWhatIf(i) {
  const ctx = i.whatif_context;
  const failedStops = (i.review_payload?.failed_constraints || []).map((v) => v.stop_id);
  const otherStops = (ctx?.plan?.routes || [])
    .flatMap((r) => r.stops)
    .map((s) => s.stop_id)
    .filter((id) => !failedStops.includes(id));
  $("#whatif-slot").innerHTML = `
    <h2>Work it out with the agent</h2>
    <p class="sub">Ask for a change and the agent re-runs the real feasibility math before you commit.</p>
    <div class="card">
      <button class="ghost wi" data-v='${JSON.stringify({ action: "delay_departure", seconds: 600 })}'>Delay departure 10 min</button>
      ${failedStops.map((s) =>
        `<button class="ghost wi" data-v='${JSON.stringify({ action: "drop_stop", stop_id: s })}'>Drop ${esc(s)}</button>`).join(" ")}
      ${failedStops.map((s) =>
        `<button class="ghost wi" data-v='${JSON.stringify({ action: "shift_window", stop_id: s, new_end: new Date(Date.now() + 3600e3).toISOString() })}'>Give ${esc(s)} an extra hour</button>`).join(" ")}
      <div id="wi-out"></div>
    </div>`;
  if (!ctx) {
    $("#whatif-slot").querySelector(".card").innerHTML +=
      `<p class="muted">This incident has no route to vary (it never got a detour). Approving keeps the plan unchanged.</p>`;
  }
  document.querySelectorAll("button.wi").forEach((b) =>
    b.onclick = async () => {
      const variant = JSON.parse(b.dataset.v);
      try {
        const result = await api(`/incidents/${state.selected}/whatif`, {
          method: "POST",
          body: JSON.stringify(variant),
          headers: { "content-type": "application/json" },
        });
        showWhatIfResult(variant, result);
      } catch (err) { banner(`What-if failed — ${err.message}`); }
    });
}

function showWhatIfResult(variant, result) {
  chosenVariant = { variant, result };
  const f = result.feasibility;
  const ok = f.feasible;
  $("#wi-out").innerHTML = `
    <div class="card wi-result" style="margin-top:12px">
      <div><strong>${ok ? "This works" : "This doesn't work yet"}</strong>
        <span class="state ${ok ? "" : "needs"}">${esc(result.decision.classification.replace(/_/g, " ").toLowerCase())}</span></div>
      <div class="muted">${esc(result.explanation)}</div>
      <div style="margin-top:10px">
        <button class="action" id="approve-variant" ${ok ? "" : "disabled"}>Approve this change</button>
        <button class="ghost" id="discard-variant">Discard</button>
      </div>
    </div>`;
  $("#approve-variant").onclick = () => review("approve", variant);
  $("#discard-variant").onclick = () => { $("#wi-out").innerHTML = ""; chosenVariant = null; };
}

/* ---- Review ---- */

async function review(decision, variant) {
  try {
    await api(`/incidents/${state.selected}/review`, {
      method: "POST",
      body: JSON.stringify({ decision, variant }),
      headers: { "content-type": "application/json" },
    });
  } catch (err) { banner(`Review failed — ${err.message}`); return; }
  refresh();
}

/* ---- Audit ---- */

function renderAudit() {
  const corr = state.selected || state.incidents[0]?.correlation_id;
  if (!corr) {
    $("#view").innerHTML = `<h1>Audit</h1><p class="sub">No incidents yet.</p>`;
    return;
  }
  api(`/audit/${corr}`).then(({ events }) => {
    $("#view").innerHTML = `
      <h1>Audit</h1>
      <p class="sub">${esc(corr)} — every step the agent took, in order.</p>
      <ol class="timeline">
        ${events.map((e) => `<li>
          <strong>${esc(e.node)}</strong> — ${esc(STATE_LABEL[e.state_to] || e.state_to)}
          ${e.mode ? `<span class="muted mono"> ${esc(e.mode)}</span>` : ""}
          ${Object.keys(e.facts || {}).length ? `<div class="facts">${esc(JSON.stringify(e.facts))}</div>` : ""}
        </li>`).join("")}
      </ol>`;
  }).catch((err) => banner(`Audit failed — ${err.message}`));
}

/* ---- shell ---- */

document.querySelectorAll("nav button").forEach((b) =>
  b.onclick = () => showView(b.dataset.view));

refresh();
refreshWatch();
setInterval(refreshWatch, 15000);

document.addEventListener("click", (e) => {
  const link = e.target.closest(".watch-link");
  if (link) {
    e.preventDefault();
    state.selected = link.dataset.corr;
    showView("incident");
  }
});
