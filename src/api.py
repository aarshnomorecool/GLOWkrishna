"""
GLOW FastAPI Backend: Serves the trained two-stage RandomForest models
and scenario simulation for the standalone GLOW frontend.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from src.baseline_model import predict_baseline
from src.config import PROCESSED_DIR, RISK_CATEGORIES, ROOT_DIR, TEHSIL_NAMES
from src.features import add_encodings
from src.residual_model import predict_residual
from src.risk import classify
from src.simulate import (
    ModelBundle,
    SandboxInputs,
    _apply_scenario,
    _latest_row,
    load_models,
)

ENRICHED_PATH = PROCESSED_DIR / "nagpur_blocks_enriched.csv"
STATUS_PATH = PROCESSED_DIR / "tehsil_status.csv"
HTML_PATH = ROOT_DIR / "glow-product-mockup.html"
MAHARASHTRA_BOUNDARIES_PATH = ROOT_DIR / "data" / "geo" / "maharashtra_districts.geojson"

# Tehsil slug ID <-> formal config name mapping
TEHSIL_ID_TO_NAME: Dict[str, str] = {
    "nagpur-urban": "Nagpur Urban",
    "nagpur-rural": "Nagpur Rural",
    "kamptee": "Kamptee",
    "hingna": "Hingna",
    "katol": "Katol",
    "narkhed": "Narkhed",
    "savner": "Savner",
    "kalmeshwar": "Kalmeshwar",
    "ramtek": "Ramtek",
    "parseoni": "Parseoni",
    "mouda": "Mouda",
    "kuhi": "Kuhi",
    "umred": "Umred",
    "bhiwapur": "Bhiwapur",
}
TEHSIL_NAME_TO_ID: Dict[str, str] = {v: k for k, v in TEHSIL_ID_TO_NAME.items()}

TEHSIL_CODES: Dict[str, str] = {
    "nagpur-urban": "NGP-U",
    "nagpur-rural": "NGP-R",
    "kamptee": "KAM",
    "hingna": "HNG",
    "katol": "KAT",
    "narkhed": "NRK",
    "savner": "SAV",
    "kalmeshwar": "KLM",
    "ramtek": "RAM",
    "parseoni": "PAR",
    "mouda": "MOU",
    "kuhi": "KUH",
    "umred": "UMR",
    "bhiwapur": "BHI",
}

TEHSIL_DISPLAY_NAMES: Dict[str, str] = {
    "nagpur-urban": "Nagpur (Urban)",
    "nagpur-rural": "Nagpur (Rural)",
    "kamptee": "Kamptee",
    "hingna": "Hingna",
    "katol": "Katol",
    "narkhed": "Narkhed",
    "savner": "Savner",
    "kalmeshwar": "Kalmeshwar",
    "ramtek": "Ramtek",
    "parseoni": "Parseoni",
    "mouda": "Mouda",
    "kuhi": "Kuhi",
    "umred": "Umred",
    "bhiwapur": "Bhiwapur",
}

CATEGORY_TO_KEY = {
    "Safe": "safe",
    "Semi-Critical": "semi",
    "Critical": "critical",
    "Over-Exploited": "over",
}


def normalize_tehsil(identifier: str) -> str:
    """Resolves any tehsil identifier (id, formal name, display name) to canonical TEHSIL_NAMES."""
    if not identifier:
        return "Nagpur Urban"
    clean = identifier.strip()
    if clean in TEHSIL_ID_TO_NAME:
        return TEHSIL_ID_TO_NAME[clean]
    if clean in TEHSIL_NAME_TO_ID:
        return clean
    stripped = clean.replace("(", "").replace(")", "").strip()
    if stripped in TEHSIL_NAME_TO_ID:
        return stripped
    slug = clean.lower().replace("(", "").replace(")", "").replace(" ", "-").replace("_", "-")
    if slug in TEHSIL_ID_TO_NAME:
        return TEHSIL_ID_TO_NAME[slug]
    for t in TEHSIL_NAMES:
        if t.lower() == clean.lower() or t.lower() == stripped.lower():
            return t
    return "Nagpur Urban"


def residual_to_score(residual: float, thresholds: dict) -> int:
    """
    Piecewise calibration of human residual (m) into 0-100 score matching
    the frontend risk keys:
    Safe: < 35
    Semi-Critical: 35-54
    Critical: 55-74
    Over-Exploited: 75-100
    """
    q25 = thresholds["q25"]
    q50 = thresholds["q50"]
    q75 = thresholds["q75"]

    if residual <= q25:
        ratio = (residual - (-1.5)) / max(1e-6, q25 - (-1.5))
        score = 10 + ratio * 24
        return int(max(5, min(34, round(score))))
    elif residual <= q50:
        ratio = (residual - q25) / max(1e-6, q50 - q25)
        score = 35 + ratio * 19
        return int(max(35, min(54, round(score))))
    elif residual <= q75:
        ratio = (residual - q50) / max(1e-6, q75 - q50)
        score = 55 + ratio * 19
        return int(max(55, min(74, round(score))))
    else:
        ratio = (residual - q75) / max(1e-6, 2.5 - q75)
        score = 75 + ratio * 20
        return int(max(75, min(98, round(score))))


def predict_two_stage(bundle: ModelBundle, row: pd.Series) -> tuple:
    """
    Keep Stage 1 (Climate Baseline) and Stage 2 (Residual Extraction)
    as genuinely separate calls internally.
    """
    encoded = add_encodings(pd.DataFrame([row]))
    # Stage 1: Climate baseline (natural features only)
    baseline_pred = float(predict_baseline(bundle.baseline_model, bundle.baseline_cols, encoded)[0])
    # Stage 2: Human residual (anthropogenic proxies only)
    residual_pred = float(predict_residual(bundle.residual_model, bundle.residual_cols, encoded)[0])
    return baseline_pred, residual_pred


# Global application state holder
class AppState:
    bundle: Optional[ModelBundle] = None
    enriched_df: Optional[pd.DataFrame] = None
    status_df: Optional[pd.DataFrame] = None
    tehsils_cache: Optional[dict] = None


state = AppState()


def build_drawdown_projection(
    enriched: pd.DataFrame,
    bundle: ModelBundle,
    tehsil: str,
    inputs: SandboxInputs,
    horizon_years: int = 10,
) -> dict:
    """Generates dual-series drawdown data matching the Chart.js format."""
    sub = enriched[enriched["tehsil"] == tehsil]
    hist_obs = sub.groupby("year")["observed_water_table_m"].mean()
    hist_base = sub.groupby("year")["baseline_pred"].mean()

    years = []
    observed = []
    baseline = []

    for y in sorted(hist_obs.index):
        years.append(str(y))
        observed.append(round(float(hist_obs.loc[y]), 2))
        baseline.append(round(float(hist_base.loc[y]), 2))

    split_index = len(years)

    base_row = _latest_row(enriched, tehsil)
    last_year = int(base_row["year"])

    for offset in range(1, horizon_years + 1):
        scenario_row = _apply_scenario(base_row, inputs, years_forward=offset)
        b_pred, r_pred = predict_two_stage(bundle, scenario_row)
        years.append(str(last_year + offset))
        observed.append(round(b_pred + r_pred, 2))
        baseline.append(round(b_pred, 2))

    return {
        "years": years,
        "observed": observed,
        "baseline": baseline,
        "splitIndex": split_index,
    }


def ensure_loaded():
    """Ensures models and dataframes are loaded into state."""
    if state.bundle is None:
        state.bundle = load_models()
    if state.enriched_df is None:
        state.enriched_df = pd.read_csv(ENRICHED_PATH)
    if state.status_df is None:
        state.status_df = pd.read_csv(STATUS_PATH)
    if state.tehsils_cache is None:
        compute_baseline_data()


def compute_baseline_data():
    """Precomputes baseline scores and drawdowns for all 14 tehsils."""
    if state.bundle is None or state.enriched_df is None or state.status_df is None:
        if state.bundle is None:
            state.bundle = load_models()
        if state.enriched_df is None:
            state.enriched_df = pd.read_csv(ENRICHED_PATH)
        if state.status_df is None:
            state.status_df = pd.read_csv(STATUS_PATH)
    bundle = state.bundle
    enriched = state.enriched_df
    status = state.status_df
    baseline_inputs = SandboxInputs(
        rainfall_pct_change=0.0,
        drip_irrigation_adoption_pct=20.0,
        borewell_growth_pct=0.0,
    )

    tehsil_list = []
    for tehsil in TEHSIL_NAMES:
        tid = TEHSIL_NAME_TO_ID.get(tehsil, tehsil.lower().replace(" ", "-"))
        status_row = status[status["tehsil"] == tehsil].iloc[0]

        residual_m = float(status_row["latest_human_residual_m"])
        category = str(status_row["risk_category"])
        risk_k = CATEGORY_TO_KEY.get(category, "semi")
        score = residual_to_score(residual_m, bundle.thresholds)

        drawdown = build_drawdown_projection(enriched, bundle, tehsil, baseline_inputs, horizon_years=10)

        tehsil_list.append({
            "id": tid,
            "name": TEHSIL_DISPLAY_NAMES.get(tid, tehsil),
            "tehsil": tehsil,
            "code": TEHSIL_CODES.get(tid, tid[:3].upper()),
            "score": score,
            "risk_category": category,
            "risk_key": risk_k,
            "human_pct": round(float(status_row["human_pct"]), 1),
            "natural_pct": round(float(status_row["natural_pct"]), 1),
            "latest_observed_water_table_m": round(float(status_row["latest_observed_water_table_m"]), 2),
            "latest_baseline_pred_m": round(float(status_row["latest_baseline_pred_m"]), 2),
            "latest_human_residual_m": round(residual_m, 2),
            "drawdown": drawdown,
        })

    state.tehsils_cache = {
        "tehsils": tehsil_list,
        "risk_thresholds": bundle.thresholds,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Load ML artifacts and precompute baseline data
    state.bundle = load_models()
    state.enriched_df = pd.read_csv(ENRICHED_PATH)
    state.status_df = pd.read_csv(STATUS_PATH)
    compute_baseline_data()
    yield
    # Shutdown


app = FastAPI(
    title="GLOW Groundwater Outlook API",
    description="Two-stage ML model API for natural baseline and human residual simulation",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def serve_ui():
    """Serves the frontend mockup directly at root."""
    if HTML_PATH.exists():
        return FileResponse(HTML_PATH)
    return JSONResponse({"status": "GLOW API running", "docs": "/docs"})


@app.get("/assets/maharashtra_districts.geojson")
async def serve_maharashtra_boundaries():
    """Serve the local public district-boundary data used by the Vidarbha map."""
    if not MAHARASHTRA_BOUNDARIES_PATH.exists():
        raise HTTPException(status_code=404, detail="District boundary data not found")
    return FileResponse(MAHARASHTRA_BOUNDARIES_PATH, media_type="application/geo+json")


@app.get("/api/tehsils")
async def get_tehsils():
    """
    Returns baseline scores for all tehsils, calling the existing trained models
    and persisted status artifacts (no retraining).
    """
    ensure_loaded()
    return state.tehsils_cache


class SimulateRequest(BaseModel):
    rainfall: float = Field(0.0, description="Rainfall change (%)")
    drip: float = Field(20.0, description="Drip irrigation adoption (%)")
    borewell: float = Field(0.0, description="Borewell growth (%/yr)")
    tehsil_id: Optional[str] = Field(None, description="Tehsil slug ID or name")
    tehsil: Optional[str] = Field(None, description="Alternate field for tehsil identifier")


@app.post("/api/simulate")
async def simulate(req: SimulateRequest):
    """
    Accepts {rainfall, drip, borewell} slider values and a tehsil id,
    calls simulate.py's existing logic, and returns the updated score plus
    drawdown projection. Stage 1 and Stage 2 are kept as genuinely separate calls.
    Also returns updated scenario scores for all tehsils to update the district map in one call.
    """
    ensure_loaded()
    identifier = req.tehsil_id or req.tehsil or "nagpur-urban"
    target_tehsil = normalize_tehsil(identifier)
    target_id = TEHSIL_NAME_TO_ID.get(target_tehsil, "nagpur-urban")

    inputs = SandboxInputs(
        rainfall_pct_change=float(req.rainfall),
        drip_irrigation_adoption_pct=float(req.drip),
        borewell_growth_pct=float(req.borewell),
    )

    bundle = state.bundle
    enriched = state.enriched_df
    status = state.status_df

    # 1. Focused tehsil detailed simulation
    base_row = _latest_row(enriched, target_tehsil)
    scenario_row = _apply_scenario(base_row, inputs, years_forward=1)

    # Separate Stage 1 and Stage 2 calls
    baseline_pred, residual_pred = predict_two_stage(bundle, scenario_row)

    risk_category = classify(residual_pred, bundle.thresholds)
    risk_k = CATEGORY_TO_KEY.get(risk_category, "semi")
    score = residual_to_score(residual_pred, bundle.thresholds)

    # Calculate dynamic attribution split under the scenario
    status_row = status[status["tehsil"] == target_tehsil].iloc[0]
    earliest_baseline = status_row["latest_baseline_pred_m"] - status_row["natural_change_m"]
    earliest_residual = status_row["latest_human_residual_m"] - status_row["human_change_m"]

    natural_change = baseline_pred - earliest_baseline
    human_change = residual_pred - earliest_residual
    denom = abs(natural_change) + abs(human_change)
    natural_pct = round(100.0 * abs(natural_change) / denom, 1) if denom > 1e-9 else 50.0
    human_pct = round(100.0 - natural_pct, 1)

    # Forward drawdown projection
    drawdown = build_drawdown_projection(enriched, bundle, target_tehsil, inputs, horizon_years=10)

    # 2. District-wide response for all 14 tehsils
    all_tehsils = {}
    for tehsil in TEHSIL_NAMES:
        t_id = TEHSIL_NAME_TO_ID.get(tehsil, tehsil.lower().replace(" ", "-"))
        t_base_row = _latest_row(enriched, tehsil)
        t_scen_row = _apply_scenario(t_base_row, inputs, years_forward=1)
        t_b_pred, t_r_pred = predict_two_stage(bundle, t_scen_row)
        t_cat = classify(t_r_pred, bundle.thresholds)
        t_key = CATEGORY_TO_KEY.get(t_cat, "semi")
        t_score = residual_to_score(t_r_pred, bundle.thresholds)

        t_status = status[status["tehsil"] == tehsil].iloc[0]
        t_e_base = t_status["latest_baseline_pred_m"] - t_status["natural_change_m"]
        t_e_res = t_status["latest_human_residual_m"] - t_status["human_change_m"]
        t_nat_change = t_b_pred - t_e_base
        t_hum_change = t_r_pred - t_e_res
        t_denom = abs(t_nat_change) + abs(t_hum_change)
        t_nat_pct = round(100.0 * abs(t_nat_change) / t_denom, 1) if t_denom > 1e-9 else 50.0
        t_hum_pct = round(100.0 - t_nat_pct, 1)

        all_tehsils[t_id] = {
            "id": t_id,
            "tehsil": tehsil,
            "score": t_score,
            "risk_category": t_cat,
            "risk_key": t_key,
            "human_pct": t_hum_pct,
            "natural_pct": t_nat_pct,
            "baseline_pred_m": round(t_b_pred, 3),
            "human_residual_pred_m": round(t_r_pred, 3),
            "projected_water_table_m": round(t_b_pred + t_r_pred, 3),
        }

    return {
        "tehsil": {
            "id": target_id,
            "name": TEHSIL_DISPLAY_NAMES.get(target_id, target_tehsil),
            "tehsil": target_tehsil,
            "score": score,
            "risk_category": risk_category,
            "risk_key": risk_k,
            "human_pct": human_pct,
            "natural_pct": natural_pct,
            "baseline_pred_m": round(baseline_pred, 3),
            "human_residual_pred_m": round(residual_pred, 3),
            "projected_water_table_m": round(baseline_pred + residual_pred, 3),
            "drawdown": drawdown,
        },
        "all_tehsils": all_tehsils,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)
