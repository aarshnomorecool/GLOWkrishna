# GLOW — Groundwater Level Outlook & Water-policy Intelligence

Groundwater governance dashboard for Nagpur district, separating natural climate-driven depletion from human extraction pressure, and enabling district officials to simulate policy interventions before spending public funds.

## Architecture & Features

- **Two-stage model, kept as genuinely separate inspectable stages**:
  - **Stage 1 — Climate Baseline** (`src/baseline_model.py`): RandomForest trained on rainfall, temperature, recharge proxy, local hydrogeology (tehsil), and season. Predicts expected water-table depth under natural climate alone.
  - **Stage 2 — Residual Extraction** (`src/residual_model.py`): RandomForest trained on `observed − baseline_prediction`, regressed against human proxies (crop water intensity, borewell density, irrigation census proxy).
  - Both stages enforce monotonic constraints (`monotonic_cst`).
- **Risk Classification** (`src/risk.py`): Buckets tehsils into Safe, Semi-Critical, Critical, and Over-Exploited using quantile thresholds fit on reference distributions.
- **Policy Sandbox & Simulation Engine** (`src/simulate.py`): Fast single-row inference against persisted artifacts (`models/*.joblib`) producing forward 10-year drawdown projections under perturbed climate and agricultural interventions.
- **FastAPI REST Service** (`src/api.py`):
  - `GET /api/tehsils`: Serves baseline scores, risk categories, attribution splits, and drawdown curves for all 14 tehsils without retraining.
  - `POST /api/simulate`: Runs scenario inference with `{rainfall, drip, borewell, tehsil_id}` and returns updated projections and district-wide scores.
  - `GET /`: Serves the live web dashboard.
- **Frontend Dashboard** (`glow-product-mockup.html`):
  - Interactive choropleth map of Nagpur's 14 tehsils.
  - Policy Sandbox with interactive sliders (rainfall, drip irrigation, borewells) with debounced live API recomputations.
  - Dual-line Chart.js drawdown charts (observed/projected vs. climate baseline).
  - Attribution donut charts and plain-language summary statements.
  - Three.js animated 3D water table visualization driven by district-wide stress.
  - Data sources status, reports generation, and alerts.

## Running the Project

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. (Optional) Re-generate synthetic data and retrain models:
```bash
python scripts/generate_synthetic_data.py
python -m src.train
```

3. Launch the FastAPI server:
```bash
uvicorn src.api:app --reload --port 8000
```
*(Or simply run: `python -m src.api`)*

4. Open in your browser:
```
http://localhost:8000
```

## Project Layout

```
src/api.py                           FastAPI application & simulation endpoints
glow-product-mockup.html             Interactive frontend dashboard & Policy Sandbox
src/config.py                        Tehsil registry, schema, risk categories & color tokens
src/features.py                      Encoding & monotonic constraint definitions
src/baseline_model.py                Stage 1 — Climate Baseline RandomForest
src/residual_model.py                Stage 2 — Residual Extraction RandomForest
src/risk.py                          Quantile-based risk classification
src/train.py                         Pipeline training & artifact generation
src/simulate.py                      Policy Sandbox scenario inference & projection engine
scripts/generate_synthetic_data.py   Synthetic data generator
models/                              Persisted joblib model artifacts & risk thresholds
data/processed/                      Processed block datasets & summary CSVs
data/geo/                            Tehsil GeoJSON boundaries
```
