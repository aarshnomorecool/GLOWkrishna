# CLAUDE.md

This file gives Claude (and any future contributor) full context on the **GLOW** project before writing or modifying code. Read this in full before making architectural decisions.

---

## Project Overview

**Name:** GLOW — Groundwater Level Outlook & Water-policy Intelligence and Risk attribution
**Formerly named:** AQUASENSE
**Built for:** Smart India Hackathon, Problem Statement 1696 (groundwater governance)
**Pilot scope:** Nagpur district, Maharashtra (block/tehsil level) — designed to be extensible to other districts later

### One-line pitch
A groundwater governance dashboard that separates *natural climate-driven* depletion from *human-induced (extraction) driven* depletion, and lets district officials simulate policy interventions before spending public funds.

### The core idea ("Dynamic Causality")
Most existing tools (India-WRIS, IN-GRES, basic ARIMA/LSTM scripts) forecast a single water-table number or report historical status. They don't tell an administrator *why* a block is failing or *what to do about it*. GLOW splits the problem into two layers:

1. **Climate Baseline Forecast** — what the water table *should* look like given rainfall, temperature, and recharge cycles alone (natural variation only).
2. **Human Extraction Residual** — the gap between the baseline prediction and the actually observed water table, attributed to human activity (borewell pumping, water-intensive cropping), estimated via proxy variables (crop patterns, irrigation census data, and power-consumption data where available).

The residual is not noise — it's the actionable signal. It's what feeds the **Policy Sandbox**: an interactive control panel where officials adjust sliders (e.g. "rainfall −20%", "drip irrigation adoption +30%") and see the projected drawdown curve and risk map update in response.

---

## Why this differs from existing approaches

- Government portals (India-WRIS, IN-GRES) archive and categorize historical/current status but don't simulate future interventions.
- Academic/open-source groundwater models are typically single black-box regressors (LSTM/ARIMA) that output one forecasted number with no explanation of *why*.
- GLOW's differentiation: (a) explicit separation of natural vs. human-driven depletion, (b) an interactive what-if simulator, (c) an interpretable model (not a black box) so officials can see explicit trade-offs.

---

## Model Architecture

**Predictive core:** Interpretable Gradient Boosting / Random Forest with two-stage residual modeling — deliberately *not* a neural network, because interpretability (feature importance, explicit trade-off statements) is a core product requirement, not just a nice-to-have.

**Pipeline stages:**

1. **Data Ingestion** — natural features (rainfall, temperature, recharge cycles, soil) and anthropogenic features (crop patterns, irrigation census, power-consumption proxies where available), joined into a common time-indexed, block/district-level schema.
2. **Climate Baseline Model** — trained on natural features only; target = historical water table level. This produces "what the water table should be under natural conditions alone."
3. **Residual Extraction (the attribution step)** — `residual = observed_water_table - climate_baseline_prediction`. This residual is regressed against anthropogenic features in a second-stage model to quantify human-driven depletion pressure per block/season.
4. **Policy Sandbox / Simulation Layer** — slider inputs perturb stage-1 inputs; perturbed values are re-run through stages 2–3 to regenerate a projected drawdown curve in near real time.
5. **Presentation Layer** — dashboard: map, drawdown curve, attribution breakdown, sandbox controls, exportable summary.

**Important framing note:** the residual is *not* pure human signal — it also absorbs model error and unmeasured natural variables (aquifer geology, inter-basin flow). Don't overclaim precision in the UI copy or the whitepaper; frame it as "estimated human-attributable pressure," not a certainty.

---

## Tech Stack

Two viable paths — pick based on team bandwidth and time remaining. **Recommendation: start on the fallback path to get an ugly-but-working end-to-end demo fast, then port to the primary path if 2+ days remain and a frontend dev is available.**

### Primary path (preferred if time allows)

- **Backend:** Python + FastAPI — serves trained models via REST endpoints. Async support matters here because sandbox sliders fire recompute requests rapidly.
- **ML:** scikit-learn (GradientBoostingRegressor / RandomForestRegressor), trained offline, persisted with `joblib`. No retraining at request time — inference only on perturbed inputs.
- **Frontend:** React (app shell + state for slider values, selected block, panel data)
- **Map:** Leaflet.js via `react-leaflet` — renders the choropleth of Nagpur blocks/tehsils colored by risk category. Chosen over Mapbox/Google Maps specifically to avoid API keys/billing during a hackathon demo.
- **Charts:** Recharts (simpler, cleaner "executive" look) or Plotly.js (if you want zoom/hover for free) for the drawdown curve and attribution breakdown.
- **Styling:** Tailwind CSS.
- **Boundaries:** static GeoJSON for Nagpur district block/tehsil boundaries, served directly from frontend or a simple `/boundaries` endpoint. No PostGIS needed at this scale.

### Fallback path (faster to build, single codebase)

- **Streamlit** + **Plotly** + **Folium or pydeck** for the map — everything in Python, no separate frontend build, ML team can build the whole thing without a dedicated frontend dev. Less polish and slightly less snappy slider interactivity, but dramatically faster to get to a working demo.

### Performance trick (applies to either path)
Precompute the natural-baseline layer once per block. Only the human-residual layer needs to recompute live when sliders move — this is what keeps the sandbox feeling instant rather than laggy during a live demo.

---

## Dashboard Requirements

- **Main view:** choropleth map of Nagpur district, blocks/tehsils colored by stress category (Safe / Semi-Critical / Critical / Over-exploited — matching IN-GRES's own classification language so it's instantly familiar to officials).
- **Interaction:** clicking a block opens a side panel with that block's drawdown curve, attribution split (natural vs. human %), and sandbox sliders scoped to that block.
- **Sandbox behavior:** moving a slider re-colors the map in real time (blocks visibly shifting risk category is a much stronger demo moment than a chart alone). Consider a before/after toggle.
- **Secondary views:** district-wide summary strip (count of blocks per risk category), time-series drawdown curve, attribution bar/pie chart.
- Keep boundary resolution at block/tehsil level, not village level — village-level GeoJSON is unnecessarily heavy and station data isn't dense enough per-village to justify it.

---

## Datasets

### Tier 1 — Core (build the MVP on these; no bureaucratic dependency)

| Dataset | Source | Link | Automation |
|---|---|---|---|
| Groundwater levels (target variable) | CGWB / India-WRIS | https://indiawris.gov.in | WFS geoserver queries possible (see `wris_extractor` QGIS plugin as reference) — semi-automatable |
| Stage-of-extraction categories (ground truth) | IN-GRES | https://ingres.iith.ac.in | Manual (dashboard/report exports) |
| Rainfall (0.25° gridded, daily) | IMD Pune | https://imdpune.gov.in/cmpg/Griddata/Rainfall_25_Bin.html | Scriptable file pulls (`wget`/`curl` loop or `imdR` package) |
| Crop production stats (district/crop/season/year) | data.gov.in | https://www.data.gov.in/catalog/district-wise-season-wise-crop-production-statistics-0 | Full API via `datagovindia` Python package |
| Minor Irrigation Census (borewell/dugwell counts — safest extraction proxy) | data.gov.in / Ministry of Jal Shakti | search via data.gov.in | Full API |

### Tier 2 — Add if time/access allow (strengthens the pitch)

| Dataset | Source | Link | Notes |
|---|---|---|---|
| Finer-grained groundwater/well data for Nagpur | GSDA Nagpur divisional office | https://gsda.maharashtra.gov.in/en-nagpur/ | More granular than CGWB; manual download |
| Temperature (1° gridded, daily) | IMD Pune | https://cdsp.imdpune.gov.in | Scriptable, same pattern as rainfall |
| Soil data | ICAR-NBSS&LUP (HQ in Nagpur) | https://bhoomigeoportal-nbsslup.in | Static layer, one-time pull; check for WMS/WFS before assuming manual-only |
| Agricultural feeder power consumption | MSEDCL / MahaDiscom | https://www.mahadiscom.in | **No public API — requires RTI/direct request. Do not block MVP on this.** |

### Tier 3 — Reference only (not pulled directly into the model)
- ICRISAT District-Level Database (http://data.icrisat.org/dld) — cross-check source, redundant with data.gov.in for core pipeline
- NITI Aayog ICED dashboard (https://iced.niti.gov.in) — too coarse (state/DISCOM level) for block-level modeling; whitepaper context only
- Springer methodology paper on Maharashtra feeder-based extraction estimation — cite as precedent/template, not a data source
- Block/tehsil boundary GeoJSON — GSDA GIS layers, or `datameet` community repo of Indian administrative boundaries as a fallback

**Regional advantage worth using in the pitch:** Maharashtra bills (doesn't fully subsidize/free) agricultural power, which means better metering/billing records than free-power states like Karnataka/Telangana — improving the odds of a real consumption signal rather than just connection counts. Nagpur also has NBSS&LUP's national HQ and a GSDA divisional office locally.

---

## Storage / Compute Expectations

Not a constraint. For a 10–15 year training window scoped to Nagpur district:
- Processed training data: well under 200 MB total across all features
- Model artifacts (GBM/RF ensembles): a few MB, unlikely to exceed 100 MB
- Even keeping full unclipped India-wide raw downloads around: still under 1 GB

The actual bottleneck is data-cleaning/feature-engineering time (aligning grid cells to district boundaries, handling missing station-years), not disk space. Don't over-engineer for scale that isn't needed at hackathon scope.

---

## Known Challenges (be upfront about these, don't hide them from judges)

- **Proxy data availability/granularity** — feeder-level power data is often unmetered/unavailable; Minor Irrigation Census is the safer fallback proxy.
- **Residual ≠ pure human signal** — includes model error and unmeasured natural variables; frame conservatively in UI and whitepaper.
- **No labeled ground truth for the attribution split** — validation will be indirect (known drought years vs. known high-extraction years as sanity checks), not a clean accuracy metric.
- **Temporal lag** — extraction effects on water table aren't instantaneous; residual model needs lagged features.
- **Cross-region generalization** — hydrogeology varies across India; keep the pitch scoped explicitly to Nagpur/Vidarbha rather than claiming pan-India accuracy.
- **UX for non-technical officials** — sliders and curves must degrade to plain-language risk statements, not just charts, for a 5-minute DM review.

---

## Coding Conventions

- Prefer interpretable models over black-box ones throughout — this is a stated product differentiator, not just a modeling choice, so don't swap in a neural net "for better accuracy" without discussing the trade-off first.
- Keep the natural-baseline and human-residual models as clearly separate, inspectable stages in code (not fused into one pipeline) — the separation is the core technical claim and needs to be demonstrable, not just conceptually true.
- Cache/precompute anything that doesn't need to respond to sliders in real time.
- Scope all data pulls to Nagpur district by default; keep boundary/filter logic parameterized so extending to other districts later isn't a rewrite.
