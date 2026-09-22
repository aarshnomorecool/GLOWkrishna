(function () {
"use strict";

/* ============================================================
   DATA
   ============================================================ */
const RISK = {
  safe:     { label: "Safe",           color: "var(--safe)",     hex: "#3E8E75", bg: "var(--safe-bg)"     },
  semi:     { label: "Semi-Critical",  color: "var(--semi)",     hex: "#B98A1E", bg: "var(--semi-bg)"     },
  critical: { label: "Critical",       color: "var(--critical)", hex: "#C3641F", bg: "var(--critical-bg)" },
  over:     { label: "Over-Exploited", color: "var(--over)",     hex: "#A63A2C", bg: "var(--over-bg)"     }
};

function riskKey(score) {
  if (score < 35) return "safe";
  if (score < 55) return "semi";
  if (score < 75) return "critical";
  return "over";
}

const TEHSILS = [
  { id: "nagpur-urban",  name: "Nagpur (Urban)", code: "NGP-U", base: 58, humanRatio: 0.55 },
  { id: "nagpur-rural",  name: "Nagpur (Rural)", code: "NGP-R", base: 47, humanRatio: 0.45 },
  { id: "kamptee",       name: "Kamptee",        code: "KAM",   base: 62, humanRatio: 0.60 },
  { id: "hingna",        name: "Hingna",         code: "HNG",   base: 71, humanRatio: 0.65 },
  { id: "katol",         name: "Katol",          code: "KAT",   base: 44, humanRatio: 0.40 },
  { id: "narkhed",       name: "Narkhed",        code: "NRK",   base: 78, humanRatio: 0.70 },
  { id: "savner",        name: "Savner",         code: "SAV",   base: 39, humanRatio: 0.35 },
  { id: "kalmeshwar",     name: "Kalmeshwar",     code: "KLM",   base: 52, humanRatio: 0.48 },
  { id: "ramtek",        name: "Ramtek",         code: "RAM",   base: 28, humanRatio: 0.20 },
  { id: "parseoni",      name: "Parseoni",       code: "PAR",   base: 33, humanRatio: 0.25 },
  { id: "mouda",         name: "Mouda",          code: "MOU",   base: 46, humanRatio: 0.42 },
  { id: "kuhi",          name: "Kuhi",           code: "KUH",   base: 60, humanRatio: 0.58 },
  { id: "umred",         name: "Umred",          code: "UMR",   base: 82, humanRatio: 0.72 },
  { id: "bhiwapur",      name: "Bhiwapur",       code: "BHI",   base: 32, humanRatio: 0.30 }
];

const SOURCES = [
  { name: "CGWB / India-WRIS", tier: "Tier 1", desc: "Groundwater level readings, the target variable for both model stages.", status: "connected", tier2: false },
  { name: "IMD Pune",          tier: "Tier 1", desc: "Gridded rainfall and temperature, the core climate baseline inputs.",      status: "connected", tier2: false },
  { name: "data.gov.in",       tier: "Tier 1", desc: "District crop and season production, an anthropogenic-demand proxy.",      status: "connected", tier2: false },
  { name: "Minor Irrigation Census", tier: "Tier 1", desc: "Borewell and dugwell counts, the safest extraction proxy available.", status: "connected", tier2: false },
  { name: "GSDA Nagpur",       tier: "Tier 2", desc: "Finer-grained well and geological data for the Nagpur division.",           status: "pending", tier2: true },
  { name: "MSEDCL power",      tier: "Tier 2", desc: "Feeder-level consumption. No public API, needs a direct request.",          status: "pending", tier2: true }
];

const STEPS = [
  { title: "Ingest & align", desc: "Rainfall, temperature and crop data are aligned to each tehsil and season.", more: "Every reading is joined on a block/tehsil plus season grid, so a rainfall anomaly and a crop-water-intensity reading for the same place and quarter sit in one row." },
  { title: "Two-stage model", desc: "A climate baseline model and a residual model, kept genuinely separate.", more: "Stage one predicts the water table from natural variables alone. Stage two explains the gap between that prediction and reality using human-demand proxies only. Neither stage sees the other's inputs." },
  { title: "Risk classification", desc: "Each tehsil is placed into Safe, Semi-Critical, Critical or Over-Exploited.", more: "Thresholds are fit once against the reference population and then reused, so a tehsil's category always means the same thing across every scenario you test." },
  { title: "Policy Sandbox", desc: "Adjust rainfall, irrigation or extraction assumptions and see the effect immediately.", more: "Moving a slider reruns both trained stages by inference only, on one perturbed row per tehsil, and projects a new drawdown curve." }
];

/* ============================================================
   STATE & API INTEGRATION
   ============================================================ */
const API_BASE = window.location.origin.startsWith("http") ? "" : "http://127.0.0.1:8000";
/* Nagpur tehsil boundaries: Survey of India subdistrict polygons served from
   /assets/nagpur_tehsils.geojson (see data/geo/nagpur_tehsils.geojson).
   All 14 tehsils are rendered from a SINGLE global fit, so shared borders
   project to identical screen coordinates and align exactly with no gaps. */
let tehsilFeatures = [];

function projectTehsilFeatures(features) {
  const points = [];
  features.forEach((feature) => {
    const polygons = feature.geometry.type === "MultiPolygon"
      ? feature.geometry.coordinates : [feature.geometry.coordinates];
    polygons.forEach((polygon) => polygon.forEach((ring) => ring.forEach((point) => points.push(point))));
  });
  const lons = points.map((p) => p[0]), lats = points.map((p) => p[1]);
  const minLon = Math.min.apply(null, lons), maxLon = Math.max.apply(null, lons);
  const minLat = Math.min.apply(null, lats), maxLat = Math.max.apply(null, lats);
  const margin = 26, width = 640, height = 460;
  const scale = Math.min((width - margin * 2) / (maxLon - minLon), (height - margin * 2) / (maxLat - minLat));
  const offsetX = (width - (maxLon - minLon) * scale) / 2;
  const offsetY = (height - (maxLat - minLat) * scale) / 2;
  const project = (p) => [offsetX + (p[0] - minLon) * scale, offsetY + (maxLat - p[1]) * scale];
  const ringPath = (ring) => ring.map((p, i) => (i ? "L" : "M") + project(p).map((v) => v.toFixed(1)).join(",")).join("") + "Z";

  const knownIds = {};
  TEHSILS.forEach((t) => { knownIds[t.id] = t; });
  return features.map((feature) => {
    const polygons = feature.geometry.type === "MultiPolygon"
      ? feature.geometry.coordinates : [feature.geometry.coordinates];
    const outline = polygons.map((polygon) => polygon.map(ringPath).join("")).join("");
    // Label anchor is precomputed in the GeoJSON (representative point,
    // guaranteed inside the polygon) — never a raw ring average.
    const label = project([feature.properties.labelLon, feature.properties.labelLat]);
    const tid = feature.properties.id;
    return {
      id: tid,
      name: (knownIds[tid] && knownIds[tid].name) || feature.properties.tehsil,
      code: (knownIds[tid] && knownIds[tid].code) || "",
      outline: outline,
      labelX: label[0],
      labelY: label[1]
    };
  }).filter((f) => !!knownIds[f.id]);
}

async function loadNagpurTehsilBoundaries() {
  const url = API_BASE + "/assets/nagpur_tehsils.geojson";
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error("HTTP " + response.status);
    const geojson = await response.json();
    const projected = projectTehsilFeatures(geojson.features || []);
    if (projected.length === TEHSILS.length) {
      tehsilFeatures = projected;
      return;
    }
    console.warn("Nagpur tehsil boundary data incomplete:",
      projected.length + " of " + TEHSILS.length + " tehsils matched");
  } catch (err) {
    console.warn("Unable to load Nagpur tehsil boundary data from", url, err);
  }
}

const state = {
  view: "dashboard",
  selectedTehsil: null,
  sandboxFocus: "nagpur-urban",
  sliders: { rainfall: 0, drip: 20, borewell: 0 },
  scenarios: [],
  reports: [],
  theme: "light",
  compactNumbers: false,
  charts: {},
  baselineData: {},
  scenarioData: null,
  apiConnected: false
};

async function fetchTehsilsFromAPI() {
  try {
    const res = await fetch(API_BASE + "/api/tehsils");
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    state.apiConnected = true;
    state.baselineData = {};
    if (data && data.tehsils) {
      data.tehsils.forEach((t) => {
        state.baselineData[t.id] = t;
      });
    }
    return true;
  } catch (err) {
    console.warn("GLOW API /api/tehsils unreachable, running in preview mode:", err);
    return false;
  }
}

async function fetchSimulateFromAPI(tehsilId, sliders) {
  try {
    const res = await fetch(API_BASE + "/api/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rainfall: sliders.rainfall,
        drip: sliders.drip,
        borewell: sliders.borewell,
        tehsil_id: tehsilId
      })
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    state.scenarioData = data;
    return data;
  } catch (err) {
    console.warn("GLOW API /api/simulate error:", err);
    return null;
  }
}

/* ============================================================
   HELPERS
   ============================================================ */
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
function fmtPct(n) { return (n > 0 ? "+" : "") + n + "%"; }
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

function currentScore(tehsil, sliders) {
  const tid = typeof tehsil === "string" ? tehsil : (tehsil ? tehsil.id : "");
  if (sliders && state.scenarioData && state.scenarioData.all_tehsils && state.scenarioData.all_tehsils[tid]) {
    return state.scenarioData.all_tehsils[tid].score;
  }
  if (state.baselineData && state.baselineData[tid]) {
    return state.baselineData[tid].score;
  }
  sliders = sliders || { rainfall: 0, drip: 20, borewell: 0 };
  const rainfallEffect = -sliders.rainfall * 0.55;
  const dripEffect = -(sliders.drip - 20) * 0.22;
  const borewellEffect = sliders.borewell * 0.45;
  const raw = (tehsil && tehsil.base ? tehsil.base : 50) + rainfallEffect + dripEffect + borewellEffect;
  return clamp(Math.round(raw), 4, 97);
}

function scoreParts(tehsil, sliders) {
  const tid = typeof tehsil === "string" ? tehsil : (tehsil ? tehsil.id : "");
  if (sliders && state.scenarioData && state.scenarioData.all_tehsils && state.scenarioData.all_tehsils[tid]) {
    const sc = state.scenarioData.all_tehsils[tid];
    return { score: sc.score, humanPct: Math.round(sc.human_pct), naturalPct: Math.round(sc.natural_pct) };
  }
  if (state.baselineData && state.baselineData[tid]) {
    const b = state.baselineData[tid];
    return { score: b.score, humanPct: Math.round(b.human_pct), naturalPct: Math.round(b.natural_pct) };
  }
  const score = currentScore(tehsil, sliders);
  const humanPct = clamp(Math.round((tehsil && tehsil.humanRatio ? tehsil.humanRatio : 0.5) * 100 + (sliders ? (sliders.borewell * 0.3 - (sliders.drip - 20) * 0.15) : 0)), 6, 94);
  return { score, humanPct, naturalPct: 100 - humanPct };
}
function plainLanguage(tehsil, score, humanPct) {
  const key = riskKey(score);
  const label = RISK[key].label;
  let verb = "Roughly";
  return tehsil.name + " is " + label.toLowerCase() + ". " + verb + " " + humanPct + "% of its stress traces back to extraction and cropping, not rainfall.";
}

function showToast(msg, tone) {
  const stack = document.getElementById("toast-stack");
  const el = document.createElement("div");
  el.className = "toast";
  const iconOk = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M20 6L9 17l-5-5"/></svg>';
  el.innerHTML = iconOk + "<span>" + msg + "</span>";
  stack.appendChild(el);
  setTimeout(() => {
    el.style.transition = "opacity 200ms ease, transform 200ms ease";
    el.style.opacity = "0";
    el.style.transform = "translateY(6px)";
    setTimeout(() => el.remove(), 220);
  }, 2600);
}

function openModal(html) {
  document.getElementById("modal-body").innerHTML = html;
  document.getElementById("modal-overlay").classList.add("open");
}
function closeModal() {
  document.getElementById("modal-overlay").classList.remove("open");
}
document.getElementById("modal-overlay").addEventListener("click", (e) => {
  if (e.target.id === "modal-overlay") closeModal();
});

/* ============================================================
   MAP RENDERING (shared renderer, used for dashboard + sandbox)
   ============================================================ */
function renderMap(svgId, opts) {
  opts = opts || {};
  const svg = document.getElementById(svgId);
  svg.innerHTML = "";
  if (!tehsilFeatures.length) {
    const loading = document.createElementNS("http://www.w3.org/2000/svg", "text");
    loading.setAttribute("x", "320");
    loading.setAttribute("y", "230");
    loading.setAttribute("text-anchor", "middle");
    loading.setAttribute("class", "map-loading");
    loading.textContent = "Loading Nagpur tehsil boundaries…";
    svg.appendChild(loading);
    return;
  }
  const sliders = opts.sliders || null;
  tehsilFeatures.forEach((feature) => {
    const t = TEHSILS.find((x) => x.id === feature.id);
    if (!t) return;
    const parts = scoreParts(t, sliders);
    const key = riskKey(parts.score);
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", feature.outline);
    path.setAttribute("fill", "var(--" + key + ")");
    path.setAttribute("class", "tehsil-shape is-pilot");
    path.dataset.tehsil = feature.id;
    if (opts.selected === feature.id) path.classList.add("selected");
    if (opts.filterKey && key !== opts.filterKey) path.classList.add("dimmed");
    path.addEventListener("click", () => {
      if (opts.onClick) opts.onClick(feature.id);
    });
    path.addEventListener("mousemove", (e) => {
      if (opts.onHover) opts.onHover(t, parts, e);
    });
    path.addEventListener("mouseleave", () => {
      if (opts.onLeave) opts.onLeave();
    });
    svg.appendChild(path);

    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", feature.labelX);
    label.setAttribute("y", feature.labelY + 3);
    label.setAttribute("class", "tehsil-label is-pilot");
    label.textContent = feature.code;
    label.style.pointerEvents = "none";
    svg.appendChild(label);
  });
}

function renderLegend(elId) {
  const el = document.getElementById(elId);
  el.innerHTML = Object.keys(RISK).map((k) =>
    '<div class="legend-item"><span class="legend-swatch" style="background:var(--' + k + ')"></span>' + RISK[k].label + '</div>'
  ).join("");
}

const tooltipEl = document.getElementById("map-tooltip");
function handleHover(t, parts, evt) {
  const wrap = evt.currentTarget.closest(".map-wrap");
  const rect = wrap.getBoundingClientRect();
  tooltipEl.style.left = (evt.clientX - rect.left) + "px";
  tooltipEl.style.top = (evt.clientY - rect.top) + "px";
  tooltipEl.innerHTML = "<b>" + t.name + "</b> &middot; " + RISK[riskKey(parts.score)].label;
  tooltipEl.classList.add("show");
}
function handleLeave() { tooltipEl.classList.remove("show"); }

/* ============================================================
   DRAWDOWN SERIES
   ============================================================ */
function buildSeries(t, sliders) {
  const tid = typeof t === "string" ? t : (t ? t.id : "");
  // If simulation data exists for this tehsil under active sliders
  if (sliders && state.scenarioData && state.scenarioData.tehsil && state.scenarioData.tehsil.id === tid && state.scenarioData.tehsil.drawdown) {
    return state.scenarioData.tehsil.drawdown;
  }
  // If baseline data exists for this tehsil
  if (state.baselineData && state.baselineData[tid] && state.baselineData[tid].drawdown && (!sliders || (sliders.rainfall === 0 && sliders.drip === 20 && sliders.borewell === 0))) {
    return state.baselineData[tid].drawdown;
  }
  // Fallback
  const score = currentScore(t, sliders);
  const naturalScore = Math.round((t && t.base ? t.base : 50) * (1 - (t && t.humanRatio ? t.humanRatio : 0.5)));
  const years = [];
  const observed = [];
  const baseline = [];
  let level = 14, baseLevel = 14;
  const rnd = mulberry32((t && t.cx ? t.cx : 200) * 31 + (t && t.cy ? t.cy : 200) * 7 + 1);
  for (let y = 2010; y <= 2024; y++) {
    years.push(String(y));
    level -= ((t && t.base ? t.base : 50) / 100) * 0.14 + (rnd() - 0.5) * 0.04;
    baseLevel -= (naturalScore / 100) * 0.05 + (rnd() - 0.5) * 0.02;
    observed.push(+level.toFixed(2));
    baseline.push(+baseLevel.toFixed(2));
  }
  const splitIndex = years.length;
  for (let y = 2025; y <= 2034; y++) {
    years.push(String(y));
    level -= (score / 100) * 0.14;
    baseLevel -= (naturalScore / 100) * 0.05;
    observed.push(+level.toFixed(2));
    baseline.push(+baseLevel.toFixed(2));
  }
  return { years, observed, baseline, splitIndex };
}

function drawdownChart(canvasId, tehsil, sliders) {
  const s = buildSeries(tehsil, sliders);
  const ctx = document.getElementById(canvasId).getContext("2d");
  if (state.charts[canvasId]) state.charts[canvasId].destroy();
  state.charts[canvasId] = new Chart(ctx, {
    type: "line",
    data: {
      labels: s.years,
      datasets: [
        {
          label: "Observed / projected",
          data: s.observed,
          borderColor: cssVar("--deep-water-soft") || "#1B4A56",
          backgroundColor: "transparent",
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.25,
          segment: { borderDash: (c) => (c.p0DataIndex >= s.splitIndex - 1 ? [5, 4] : undefined) }
        },
        {
          label: "Climate-only baseline",
          data: s.baseline,
          borderColor: cssVar("--aquifer") || "#1F7A68",
          backgroundColor: "transparent",
          borderWidth: 1.5,
          borderDash: [2, 3],
          pointRadius: 0,
          tension: 0.25
        }
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: true, position: "bottom", labels: { boxWidth: 10, font: { size: 10.5, family: "IBM Plex Sans" }, color: cssVar("--ink-soft") } },
        tooltip: { titleFont: { family: "IBM Plex Mono", size: 11 }, bodyFont: { family: "IBM Plex Mono", size: 11 } }
      },
      scales: {
        x: { ticks: { maxTicksLimit: 6, font: { size: 10, family: "IBM Plex Mono" }, color: cssVar("--ink-soft") }, grid: { display: false } },
        y: { title: { display: true, text: "metres below ground", font: { size: 10, family: "IBM Plex Sans" }, color: cssVar("--ink-soft") }, ticks: { font: { size: 10, family: "IBM Plex Mono" }, color: cssVar("--ink-soft") }, grid: { color: cssVar("--line-soft") } }
      }
    }
  });
}

function attribChart(canvasId, humanPct) {
  const ctx = document.getElementById(canvasId).getContext("2d");
  if (state.charts[canvasId]) state.charts[canvasId].destroy();
  state.charts[canvasId] = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: ["Human extraction", "Natural climate"],
      datasets: [{
        data: [humanPct, 100 - humanPct],
        backgroundColor: [cssVar("--critical") || "#C3641F", cssVar("--aquifer") || "#1F7A68"],
        borderWidth: 0
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: "68%",
      plugins: { legend: { display: false }, tooltip: { enabled: true } }
    }
  });
}

/* ============================================================
   DASHBOARD RENDER
   ============================================================ */
let dashboardFilter = null;

function renderStatStrip() {
  const counts = { safe: 0, semi: 0, critical: 0, over: 0 };
  TEHSILS.forEach((t) => { counts[riskKey(currentScore(t, null))]++; });
  const el = document.getElementById("stat-strip");
  el.innerHTML = Object.keys(RISK).map((k) => {
    const active = dashboardFilter === k ? "filtered" : "";
    return '<button class="stat-chip ' + active + '" data-key="' + k + '">' +
      '<div class="stat-top"><span class="stat-label">' + RISK[k].label + '</span><span class="stat-swatch" style="background:var(--' + k + ')"></span></div>' +
      '<span class="stat-count">' + counts[k] + '</span>' +
      '<span class="stat-sub">tehsils</span></button>';
  }).join("");
  el.querySelectorAll(".stat-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const k = btn.dataset.key;
      dashboardFilter = dashboardFilter === k ? null : k;
      renderStatStrip();
      renderDashboardMap();
    });
  });
}

function renderDashboardMap() {
  renderMap("tehsil-map", {
    selected: state.selectedTehsil,
    filterKey: dashboardFilter,
    onClick: (id) => selectTehsil(id),
    onHover: handleHover,
    onLeave: handleLeave
  });
}

function selectTehsil(id) {
  state.selectedTehsil = id;
  const t = TEHSILS.find((x) => x.id === id);
  if (!t) return;
  const parts = scoreParts(t, null);
  document.getElementById("detail-empty").style.display = "none";
  document.getElementById("detail-content").classList.add("show");
  document.getElementById("detail-name").textContent = t.name;
  const key = riskKey(parts.score);
  const badge = document.getElementById("detail-badge");
  badge.style.background = "var(--" + key + "-bg)";
  badge.style.color = "var(--" + key + ")";
  badge.querySelector(".dot").style.background = "var(--" + key + ")";
  document.getElementById("detail-badge-text").textContent = RISK[key].label;
  document.getElementById("detail-statement").textContent = plainLanguage(t, parts.score, parts.humanPct);
  drawdownChart("drawdown-chart", t, null);
  attribChart("attrib-chart", parts.humanPct);
  document.getElementById("attrib-legend").innerHTML =
    '<div class="li"><span class="sw" style="background:var(--critical)"></span>Human extraction <b>' + parts.humanPct + '%</b></div>' +
    '<div class="li"><span class="sw" style="background:var(--aquifer)"></span>Natural climate <b>' + parts.naturalPct + '%</b></div>';
  renderDashboardMap();
}

/* ============================================================
   SANDBOX
   ============================================================ */
let simulateDebounceTimer = null;

function debouncedRunSimulation() {
  clearTimeout(simulateDebounceTimer);
  simulateDebounceTimer = setTimeout(() => {
    runSimulationImmediate();
  }, 180);
}

async function runSimulationImmediate() {
  const t = TEHSILS.find((x) => x.id === state.sandboxFocus) || TEHSILS[0];
  document.getElementById("sandbox-focus-name").textContent = t.name;
  document.getElementById("val-rainfall").textContent = fmtPct(state.sliders.rainfall);
  document.getElementById("val-drip").textContent = state.sliders.drip + "%";
  document.getElementById("val-borewell").textContent = fmtPct(state.sliders.borewell);

  await fetchSimulateFromAPI(t.id, state.sliders);
  renderSandboxMap();
  drawdownChart("sandbox-chart", t, state.sliders);
}

function renderSandboxMap() {
  renderMap("tehsil-map-sandbox", {
    selected: state.sandboxFocus,
    sliders: state.sliders,
    onClick: (id) => {
      state.sandboxFocus = id;
      runSimulationImmediate();
    }
  });
}

function renderSandbox() {
  runSimulationImmediate();
}

function renderScenarioList() {
  const el = document.getElementById("scenario-list-items");
  if (state.scenarios.length === 0) {
    el.innerHTML = '<div class="scenario-empty">No scenarios saved yet.</div>';
    return;
  }
  el.innerHTML = state.scenarios.map((s, i) =>
    '<div class="scenario-item"><div><div>' + s.label + '</div><div class="scenario-meta">' + s.time + '</div></div>' +
    '<button class="scenario-load" data-idx="' + i + '">Load</button></div>'
  ).join("");
  el.querySelectorAll(".scenario-load").forEach((btn) => {
    btn.addEventListener("click", () => {
      const s = state.scenarios[+btn.dataset.idx];
      state.sliders = Object.assign({}, s.sliders);
      document.getElementById("slider-rainfall").value = state.sliders.rainfall;
      document.getElementById("slider-drip").value = state.sliders.drip;
      document.getElementById("slider-borewell").value = state.sliders.borewell;
      runSimulationImmediate();
      showToast("Scenario loaded");
    });
  });
}

document.getElementById("slider-rainfall").addEventListener("input", (e) => {
  state.sliders.rainfall = +e.target.value;
  document.getElementById("val-rainfall").textContent = fmtPct(state.sliders.rainfall);
  debouncedRunSimulation();
});
document.getElementById("slider-drip").addEventListener("input", (e) => {
  state.sliders.drip = +e.target.value;
  document.getElementById("val-drip").textContent = state.sliders.drip + "%";
  debouncedRunSimulation();
});
document.getElementById("slider-borewell").addEventListener("input", (e) => {
  state.sliders.borewell = +e.target.value;
  document.getElementById("val-borewell").textContent = fmtPct(state.sliders.borewell);
  debouncedRunSimulation();
});

document.getElementById("reset-sliders-btn").addEventListener("click", () => {
  state.sliders = { rainfall: 0, drip: 20, borewell: 0 };
  document.getElementById("slider-rainfall").value = 0;
  document.getElementById("slider-drip").value = 20;
  document.getElementById("slider-borewell").value = 0;
  runSimulationImmediate();
  showToast("Sliders reset");
});
document.getElementById("save-scenario-btn").addEventListener("click", () => {
  const t = TEHSILS.find((x) => x.id === state.sandboxFocus);
  state.scenarios.unshift({
    label: t.name + " · rain " + fmtPct(state.sliders.rainfall) + ", drip " + state.sliders.drip + "%, wells " + fmtPct(state.sliders.borewell),
    time: "Saved just now",
    sliders: Object.assign({}, state.sliders)
  });
  renderScenarioList();
  showToast("Scenario saved");
});

document.getElementById("open-in-sandbox-btn").addEventListener("click", () => {
  if (!state.selectedTehsil) return;
  state.sandboxFocus = state.selectedTehsil;
  switchView("sandbox");
});

/* ============================================================
   REPORTS
   ============================================================ */
function renderReports() {
  const el = document.getElementById("reports-list");
  if (state.reports.length === 0) {
    el.innerHTML = '<div class="reports-empty"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M7 3h8l5 5v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/></svg><p>No reports yet. Generate one from here, or export directly from a tehsil.</p></div>';
    return;
  }
  el.innerHTML = state.reports.map((r, i) =>
    '<div class="report-row">' +
    '<div class="report-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M7 3h8l5 5v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M9 13h6M9 17h6M9 9h2"/></svg></div>' +
    '<div class="report-info"><div class="report-title">' + r.title + '</div><div class="report-meta">' + r.date + ' &middot; ' + r.scope + '</div></div>' +
    '<span class="report-status">' + r.status + '</span>' +
    '<div class="report-actions">' +
    '<button class="btn btn-quiet" data-act="view" data-idx="' + i + '">View</button>' +
    '<button class="btn btn-ghost" data-act="dl" data-idx="' + i + '">Download</button>' +
    '</div></div>'
  ).join("");
  el.querySelectorAll("[data-act='view']").forEach((btn) => btn.addEventListener("click", () => viewReport(+btn.dataset.idx)));
  el.querySelectorAll("[data-act='dl']").forEach((btn) => btn.addEventListener("click", () => {
    showToast("Downloaded " + state.reports[+btn.dataset.idx].file);
  }));
}
function viewReport(idx) {
  const r = state.reports[idx];
  openModal(
    '<div class="modal-head"><span class="modal-title">' + r.title + '</span>' +
    '<button class="modal-close" onclick="document.getElementById(\'modal-overlay\').classList.remove(\'open\')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg></button></div>' +
    '<div class="modal-row"><span>Scope</span><span>' + r.scope + '</span></div>' +
    '<div class="modal-row"><span>Risk category</span><span>' + r.risk + '</span></div>' +
    '<div class="modal-row"><span>Human share</span><span>' + r.humanPct + '%</span></div>' +
    '<div class="modal-row"><span>Generated</span><span>' + r.date + '</span></div>' +
    '<div class="modal-foot"><button class="btn btn-primary btn-block" id="modal-dl-btn">Download PDF</button></div>'
  );
  document.getElementById("modal-dl-btn").addEventListener("click", () => {
    closeModal();
    showToast("Downloaded " + r.file);
  });
}
function addReport(tehsilId) {
  let scope = "District-wide";
  let risk = "Mixed";
  let humanPct = Math.round(TEHSILS.reduce((a, t) => a + scoreParts(t, null).humanPct, 0) / TEHSILS.length);
  if (tehsilId) {
    const t = TEHSILS.find((x) => x.id === tehsilId);
    const parts = scoreParts(t, null);
    scope = t.name;
    risk = RISK[riskKey(parts.score)].label;
    humanPct = parts.humanPct;
  }
  const today = new Date();
  const dateStr = today.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  const rep = {
    title: scope + " outlook, " + dateStr,
    date: dateStr, scope: scope, risk: risk, humanPct: humanPct,
    status: "Ready", file: "GLOW_" + scope.replace(/[^a-zA-Z0-9]+/g, "_") + ".pdf"
  };
  state.reports.unshift(rep);
  renderReports();
  return rep;
}
document.getElementById("generate-report-btn").addEventListener("click", () => {
  addReport(state.selectedTehsil);
  showToast("Report generated");
});
document.getElementById("export-report-btn").addEventListener("click", () => {
  addReport(state.selectedTehsil);
  switchView("reports");
  showToast("Report generated");
});

/* ============================================================
   DATA SOURCES
   ============================================================ */
function renderSources() {
  const el = document.getElementById("source-grid");
  el.innerHTML = SOURCES.map((s, i) =>
    '<div class="source-card ' + (s.tier2 && s.status !== "connected" ? "tier2" : "") + '">' +
    '<div class="source-top"><div><div class="source-name">' + s.name + '</div><div class="source-tier">' + s.tier + '</div></div>' +
    '<span class="source-status ' + s.status + '" id="src-status-' + i + '">' + (s.status === "connected" ? "Connected" : "Not connected") + '</span></div>' +
    '<div class="source-desc">' + s.desc + '</div>' +
    '<div class="source-sync" id="src-sync-' + i + '">' + (s.status === "connected" ? "Last synced 2 hours ago" : "Never synced") + '</div>' +
    '<div class="source-actions">' +
    (s.tier2
      ? '<button class="btn btn-ghost btn-block" data-act="connect" data-idx="' + i + '" ' + (s.status === "connected" ? "disabled" : "") + '>' + (s.status === "connected" ? "Connected" : "Connect") + '</button>'
      : '<button class="btn btn-quiet btn-block" data-act="sync" data-idx="' + i + '">Sync now</button>') +
    '</div></div>'
  ).join("");
  el.querySelectorAll("[data-act='sync']").forEach((btn) => btn.addEventListener("click", () => {
    const i = +btn.dataset.idx;
    document.getElementById("src-sync-" + i).textContent = "Last synced just now";
    showToast("Synced " + SOURCES[i].name);
  }));
  el.querySelectorAll("[data-act='connect']").forEach((btn) => btn.addEventListener("click", () => {
    const i = +btn.dataset.idx;
    SOURCES[i].status = "connected";
    renderSources();
    showToast("Connected " + SOURCES[i].name);
  }));
}

/* ============================================================
   HOW IT WORKS
   ============================================================ */
function renderSteps() {
  const icons = [
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 12h18M3 6h18M3 18h18"/></svg>',
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="8" cy="12" r="3.2"/><circle cx="16" cy="12" r="3.2"/></svg>',
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>',
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 6h16M4 6a2 2 0 1 0 4 0 2 2 0 1 0-4 0zM4 18h16M14 18a2 2 0 1 0 4 0 2 2 0 1 0-4 0z"/></svg>'
  ];
  const el = document.getElementById("steps-grid");
  el.innerHTML = STEPS.map((s, i) =>
    '<div class="step-card" data-idx="' + i + '"><div class="step-icon">' + icons[i] + '</div>' +
    '<div class="step-title">' + s.title + '</div><div class="step-desc">' + s.desc + '</div>' +
    '<div class="step-more">' + s.more + '</div>' +
    '<div class="step-toggle-hint">Tap for detail</div></div>'
  ).join("");
  el.querySelectorAll(".step-card").forEach((card) => card.addEventListener("click", () => card.classList.toggle("expanded")));
}

/* ============================================================
   ALERTS
   ============================================================ */
function renderAlerts() {
  const sorted = TEHSILS.map((t) => ({ t: t, score: currentScore(t, null) })).sort((a, b) => b.score - a.score).slice(0, 4);
  const el = document.getElementById("alerts-list");
  el.innerHTML = sorted.map((row) => {
    const key = riskKey(row.score);
    return '<button class="alert-item" data-tehsil="' + row.t.id + '">' +
      '<span class="alert-dot" style="background:var(--' + key + ')"></span>' +
      '<span><span class="alert-text">' + row.t.name + ' crossed into ' + RISK[key].label.toLowerCase() + ' this quarter.</span>' +
      '<div class="alert-time">2 days ago</div></span></button>';
  }).join("");
  el.querySelectorAll(".alert-item").forEach((btn) => btn.addEventListener("click", () => {
    document.getElementById("alerts-dropdown").classList.remove("open");
    switchView("dashboard");
    selectTehsil(btn.dataset.tehsil);
  }));
}

/* ============================================================
   NAV / SEARCH / DROPDOWNS
   ============================================================ */
const VIEW_TITLES = { dashboard: "Dashboard", sandbox: "Policy Sandbox", reports: "Reports", sources: "Data Sources", howitworks: "How It Works" };
function switchView(view) {
  state.view = view;
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  document.getElementById("view-" + view).classList.add("active");
  document.querySelectorAll(".navitem").forEach((n) => n.classList.toggle("active", n.dataset.view === view));
  document.getElementById("view-title-text").textContent = VIEW_TITLES[view];
  document.getElementById("main").scrollTop = 0;
  if (view === "sandbox") renderSandbox();
}
document.querySelectorAll(".navitem").forEach((btn) => btn.addEventListener("click", () => switchView(btn.dataset.view)));

const searchInput = document.getElementById("search-input");
const searchResults = document.getElementById("search-results");
searchInput.addEventListener("input", () => {
  const q = searchInput.value.trim().toLowerCase();
  if (!q) { searchResults.classList.remove("open"); return; }
  const matches = TEHSILS.filter((t) => t.name.toLowerCase().includes(q));
  if (matches.length === 0) {
    searchResults.innerHTML = '<div class="search-result-item" style="color:var(--ink-soft)">No tehsil matches "' + searchInput.value + '"</div>';
  } else {
    searchResults.innerHTML = matches.map((t) => {
      const key = riskKey(currentScore(t, null));
      return '<button class="search-result-item" data-id="' + t.id + '"><span>' + t.name + '</span><span class="legend-swatch" style="background:var(--' + key + ')"></span></button>';
    }).join("");
    searchResults.querySelectorAll(".search-result-item").forEach((btn) => btn.addEventListener("click", () => {
      switchView("dashboard");
      selectTehsil(btn.dataset.id);
      searchInput.value = "";
      searchResults.classList.remove("open");
    }));
  }
  searchResults.classList.add("open");
});
document.addEventListener("click", (e) => {
  if (!e.target.closest(".search-wrap")) searchResults.classList.remove("open");
});

function wireDropdown(btnId, ddId) {
  const btn = document.getElementById(btnId), dd = document.getElementById(ddId);
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const willOpen = !dd.classList.contains("open");
    document.querySelectorAll(".dropdown").forEach((d) => d.classList.remove("open"));
    if (willOpen) dd.classList.add("open");
  });
}
wireDropdown("alerts-btn", "alerts-dropdown");
wireDropdown("profile-btn", "profile-dropdown");
document.addEventListener("click", () => document.querySelectorAll(".dropdown").forEach((d) => d.classList.remove("open")));
document.querySelectorAll(".dropdown").forEach((d) => d.addEventListener("click", (e) => e.stopPropagation()));

document.getElementById("signout-btn").addEventListener("click", () => {
  document.getElementById("profile-dropdown").classList.remove("open");
  showToast("Signed out");
});
document.getElementById("preferences-btn").addEventListener("click", () => {
  document.getElementById("profile-dropdown").classList.remove("open");
  openModal(
    '<div class="modal-head"><span class="modal-title">Preferences</span>' +
    '<button class="modal-close" onclick="document.getElementById(\'modal-overlay\').classList.remove(\'open\')"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg></button></div>' +
    '<div class="pref-row"><span>Dark mode</span><button class="toggle ' + (state.theme === "dark" ? "on" : "") + '" id="theme-toggle"></button></div>' +
    '<div class="pref-row"><span>Compact numbers</span><button class="toggle ' + (state.compactNumbers ? "on" : "") + '" id="compact-toggle"></button></div>'
  );
  document.getElementById("theme-toggle").addEventListener("click", (e) => {
    state.theme = state.theme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", state.theme);
    e.currentTarget.classList.toggle("on");
    refreshOpenCharts();
    showToast(state.theme === "dark" ? "Dark mode on" : "Dark mode off");
  });
  document.getElementById("compact-toggle").addEventListener("click", (e) => {
    state.compactNumbers = !state.compactNumbers;
    e.currentTarget.classList.toggle("on");
  });
});
function refreshOpenCharts() {
  if (state.selectedTehsil) selectTehsil(state.selectedTehsil);
  if (state.view === "sandbox") renderSandbox();
}

/* ============================================================
   INIT
   ============================================================ */
async function init() {
  await Promise.all([fetchTehsilsFromAPI(), loadNagpurTehsilBoundaries()]);
  renderStatStrip();
  renderDashboardMap();
  renderLegend("map-legend");
  renderLegend("map-legend-sandbox");
  renderAlerts();
  renderSources();
  renderSteps();
  renderReports();
  await runSimulationImmediate();
  selectTehsil("nagpur-urban");
}
init();

})();
