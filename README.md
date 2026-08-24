# GLOW — build status

This is a first working slice of the GLOW project described in `claude.md`,
built on the **fallback path** the spec itself recommends first ("start on
the fallback path to get an ugly-but-working end-to-end demo fast"):
Streamlit + Plotly + Folium, one Python codebase, no separate frontend build.

## What's here and working right now

- **Two-stage model, kept as genuinely separate inspectable stages**
  (`src/baseline_model.py`, `src/residual_model.py`), exactly as
  `claude.md`'s coding conventions require:
  - **Stage 1 — Climate Baseline**: RandomForest trained on rainfall,
    temperature, recharge proxy, local hydrogeology (tehsil), season.
    Never sees any human/anthropogenic feature.
  - **Stage 2 — Residual Extraction**: RandomForest trained on
    `observed − baseline_prediction`, regressed against anthropogenic
    proxies only (crop water-intensity index, borewell density,
    irrigation census proxy). Never sees rainfall/temperature/tehsil.
  - Both use `monotonic_cst` constraints (more borewells/cropping intensity
    → never a *lower* predicted human residual; more rainfall → never a
    *deeper* predicted baseline). Without this, a weak-R² tree ensemble can
    learn a locally sign-flipped relationship for one input — which would
    have shown up as a slider moving a block the *wrong* direction in the
    live demo, not as a bad offline metric. Verified in a scenario sweep,
    not just eyeballed (see `python -m src.train` + ad hoc scripts used
    during this build).
- **Policy Sandbox** (`src/simulate.py`): sliders for rainfall change,
  drip-irrigation adoption, borewell growth. A slider move reruns both
  trained stages on a single perturbed row per tehsil — fast, since it's
  inference against already-persisted `models/*.joblib`, not retraining.
  Also produces a 10-year forward-projected drawdown curve per block.
- **Risk classification** (`src/risk.py`): buckets tehsils into
  Safe / Semi-Critical / Critical / Over-Exploited — IN-GRES's own
  category language — using quantile thresholds fit once on the reference
  population, reused (not recomputed) on every scenario so a block's
  category moves relative to a fixed bar.
- **Dashboard** (`app/streamlit_app.py`): choropleth map of the 14 Nagpur
  tehsils colored by risk category (click a block, or use the sidebar
  selector), a district-wide summary strip, a before/after map toggle, a
  drawdown curve + attribution split panel per block, and a plain-language
  risk statement — covering every item in `claude.md`'s Dashboard
  Requirements section.
- **Synthetic Nagpur dataset** (`scripts/generate_synthetic_data.py` →
  `data/processed/nagpur_blocks.csv`): 14 tehsils × 2010–2024 × 4 seasons,
  generated with a real underlying structure (climate signal + compounding
  anthropogenic-pressure trend + noise) so the two-stage split is genuinely
  learnable and demoable — not just random numbers.

## What's explicitly NOT real yet (~70% remaining)

- **All data is synthetic.** None of the Tier 1/2 sources in `claude.md`
  (India-WRIS, IMD Pune, data.gov.in crop stats, Minor Irrigation Census)
  have been pulled. `data/raw/` is an empty landing spot for those pulls.
  Swapping in real data means writing the actual ingestion scripts and
  producing a CSV with the same schema as `nagpur_blocks.csv` — nothing
  downstream (features/models/sandbox/dashboard) should need to change.
- **Tehsil boundaries are placeholder squares**, not real GeoJSON
  (`data/geo/nagpur_tehsils.geojson`), centered on approximate centroids.
  Needs replacing with real GSDA GIS layers or the datameet community
  boundary repo per `claude.md`'s Tier 3 notes.
- **No real IN-GRES stage-of-extraction ground truth** — the risk category
  is a ranking heuristic over the model's own residual output, not
  validated against real drought-year / high-extraction-year sanity
  checks as `claude.md`'s Known Challenges section calls for.
- **Residual model fit is modest** (R² ≈ 0.25 on held-out synthetic data)
  — expected, since a meaningful share of the "residual" is actually the
  baseline model's own estimation error rather than true human signal,
  which is the exact caveat `claude.md` warns not to overclaim in the UI.
  Real data with a cleaner natural signal (denser rainfall stations, actual
  soil/geology layers) should tighten this.
- **No FastAPI/React "primary path"** — everything is one Streamlit process.
  Worth porting only if 2+ days remain and a frontend dev is free, per
  `claude.md`'s own recommendation.
- **No tests, no lagged-effect validation, no whitepaper.**

## Running it

```bash
pip install -r requirements.txt
python scripts/generate_synthetic_data.py   # writes data/processed/*.csv, data/geo/*.geojson
python -m src.train                          # trains both stages, writes models/*.joblib
streamlit run app/streamlit_app.py
```

## Project layout

```
scripts/generate_synthetic_data.py   stand-in for the real data-ingestion pipeline
src/config.py                        shared constants: tehsil registry, schema, risk categories
src/features.py                      encoding + monotonic-constraint definitions (training AND sandbox use this)
src/baseline_model.py                Stage 1 — Climate Baseline Model
src/residual_model.py                Stage 2 — Residual Extraction Model
src/risk.py                          quantile-based risk classification
src/train.py                         orchestrates both stages, builds dashboard-ready CSVs
src/simulate.py                      Policy Sandbox — scenario inference + drawdown projection
app/streamlit_app.py                 the dashboard
models/                              persisted joblib artifacts + risk thresholds (git-ignore if this gets committed)
data/processed/                      synthetic dataset + enriched/status CSVs the dashboard reads
data/geo/                            placeholder tehsil GeoJSON
```
