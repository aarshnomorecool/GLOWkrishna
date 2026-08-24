"""
Policy Sandbox — the interactive what-if layer described in claude.md:
"officials adjust sliders ... and see the projected drawdown curve and
risk map update in response."

Both trained stages are already persisted (models/*.joblib) — nothing
here retrains anything. A slider move only triggers fast single-row
inference against those fixed artifacts, which is what keeps this feeling
instant. Sliders map to interventions officials actually think in
(rainfall change, drip-irrigation adoption, borewell growth), not raw
model columns, since a % change in "recharge_proxy" means nothing to a DM.
"""

from dataclasses import dataclass, field

import pandas as pd

from src.baseline_model import load_baseline_model, predict_baseline
from src.config import TEHSIL_NAMES
from src.features import add_encodings
from src.residual_model import load_residual_model, predict_residual
from src.risk import classify, load_thresholds


@dataclass
class SandboxInputs:
    rainfall_pct_change: float = 0.0            # persistent shift, e.g. -20 = 20% less rainfall every year
    drip_irrigation_adoption_pct: float = 0.0   # 0-100, held constant once adopted
    borewell_growth_pct: float = 0.0            # annual compounding growth rate


@dataclass
class ModelBundle:
    baseline_model: object
    baseline_cols: list
    residual_model: object
    residual_cols: list
    thresholds: dict


def load_models() -> ModelBundle:
    """Load once per session (the Streamlit layer wraps this in
    st.cache_resource) and hand the bundle to every scenario call instead
    of hitting disk on every slider tick."""
    baseline_model, baseline_cols = load_baseline_model()
    residual_model, residual_cols = load_residual_model()
    thresholds = load_thresholds()
    return ModelBundle(baseline_model, baseline_cols, residual_model, residual_cols, thresholds)


def _latest_row(enriched: pd.DataFrame, tehsil: str) -> pd.Series:
    sub = enriched[enriched["tehsil"] == tehsil]
    latest_year = sub["year"].max()
    return sub[sub["year"] == latest_year].sort_values("season").iloc[-1].copy()


def _predict_row(bundle: ModelBundle, row: pd.Series) -> tuple:
    encoded = add_encodings(pd.DataFrame([row]))
    baseline_pred = float(predict_baseline(bundle.baseline_model, bundle.baseline_cols, encoded)[0])
    residual_pred = float(predict_residual(bundle.residual_model, bundle.residual_cols, encoded)[0])
    return baseline_pred, residual_pred


def _apply_scenario(base_row: pd.Series, inputs: SandboxInputs, years_forward: int) -> pd.Series:
    row = base_row.copy()

    rain_factor = max(0.0, 1 + inputs.rainfall_pct_change / 100.0)
    row["rainfall_mm"] = base_row["rainfall_mm"] * rain_factor
    row["rainfall_mm_lag1"] = base_row["rainfall_mm_lag1"] * rain_factor
    row["recharge_proxy"] = max(0.0, base_row["recharge_proxy"] * rain_factor)

    # Drip adoption is a state (fraction of cropped area converted), not a
    # rate — reduces effective crop water demand immediately and holds.
    row["crop_water_intensity_index"] = max(
        0.0,
        base_row["crop_water_intensity_index"] * (1 - 0.6 * inputs.drip_irrigation_adoption_pct / 100.0),
    )

    # Borewell growth is naturally an annual rate, so it compounds with horizon.
    growth_factor = (1 + inputs.borewell_growth_pct / 100.0) ** years_forward
    row["borewell_density"] = max(0.0, base_row["borewell_density"] * growth_factor)
    row["irrigation_census_proxy"] = min(100.0, base_row["irrigation_census_proxy"] * (1 + 0.3 * inputs.borewell_growth_pct / 100.0) ** years_forward)

    return row


@dataclass
class SandboxResult:
    tehsil: str
    baseline_pred_m: float
    human_residual_pred_m: float
    projected_water_table_m: float
    risk_category: str


def run_scenario(enriched: pd.DataFrame, bundle: ModelBundle, tehsil: str, inputs: SandboxInputs) -> SandboxResult:
    base_row = _latest_row(enriched, tehsil)
    scenario_row = _apply_scenario(base_row, inputs, years_forward=1)
    baseline_pred, residual_pred = _predict_row(bundle, scenario_row)
    risk_category = classify(residual_pred, bundle.thresholds)
    return SandboxResult(
        tehsil=tehsil,
        baseline_pred_m=baseline_pred,
        human_residual_pred_m=residual_pred,
        projected_water_table_m=baseline_pred + residual_pred,
        risk_category=risk_category,
    )


def run_all_tehsils(enriched: pd.DataFrame, bundle: ModelBundle, inputs: SandboxInputs) -> pd.DataFrame:
    """Same scenario deltas applied to every tehsil at once — this is what
    redraws the choropleth when a slider moves."""
    rows = []
    for tehsil in TEHSIL_NAMES:
        result = run_scenario(enriched, bundle, tehsil, inputs)
        rows.append({
            "tehsil": tehsil,
            "baseline_pred_m": result.baseline_pred_m,
            "human_residual_pred_m": result.human_residual_pred_m,
            "projected_water_table_m": result.projected_water_table_m,
            "risk_category": result.risk_category,
        })
    return pd.DataFrame(rows)


def project_drawdown_curve(
    enriched: pd.DataFrame, bundle: ModelBundle, tehsil: str, inputs: SandboxInputs, horizon_years: int = 10
) -> pd.DataFrame:
    """Historical observed curve + a forward projection under the current
    slider scenario, for the per-block drawdown chart."""
    hist = (
        enriched[enriched["tehsil"] == tehsil]
        .groupby("year", as_index=False)["observed_water_table_m"]
        .mean()
        .rename(columns={"observed_water_table_m": "water_table_m"})
    )
    hist["segment"] = "Historical"

    base_row = _latest_row(enriched, tehsil)
    last_year = int(base_row["year"])

    future_rows = []
    for offset in range(1, horizon_years + 1):
        scenario_row = _apply_scenario(base_row, inputs, years_forward=offset)
        baseline_pred, residual_pred = _predict_row(bundle, scenario_row)
        future_rows.append({
            "year": last_year + offset,
            "water_table_m": baseline_pred + residual_pred,
            "segment": "Projected",
        })
    future = pd.DataFrame(future_rows)

    # Bridge point so the two line segments connect visually with no gap.
    bridge = hist[hist["year"] == last_year].copy()
    bridge["segment"] = "Projected"
    return pd.concat([hist, bridge, future], ignore_index=True)
