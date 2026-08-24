"""
Orchestrates the full two-stage pipeline end to end:

  1. Fit the climate baseline model (stage 1, natural features only).
  2. Reconstruct the exact historical residual: observed - baseline_pred.
  3. Fit the residual/attribution model (stage 2) on that residual against
     anthropogenic features only — this is what the sandbox later reruns
     under perturbed slider inputs.
  4. Classify each tehsil's latest-year human-attributable pressure into
     an IN-GRES-style risk category.
  5. Persist model artifacts + enriched dataframes for the dashboard.

Run: python -m src.train
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.baseline_model import predict_baseline, save_baseline_model, train_baseline_model  # noqa: E402
from src.config import PROCESSED_DIR, TEHSIL_NAMES  # noqa: E402
from src.features import add_encodings  # noqa: E402
from src.residual_model import predict_residual, save_residual_model, train_residual_model  # noqa: E402
from src.risk import classify_series, fit_thresholds, save_thresholds  # noqa: E402

RAW_DATA_PATH = PROCESSED_DIR / "nagpur_blocks.csv"
ENRICHED_PATH = PROCESSED_DIR / "nagpur_blocks_enriched.csv"
STATUS_PATH = PROCESSED_DIR / "tehsil_status.csv"


def load_data() -> pd.DataFrame:
    if not RAW_DATA_PATH.exists():
        raise FileNotFoundError(
            f"{RAW_DATA_PATH} not found — run scripts/generate_synthetic_data.py first "
            "(or point this at a real cleaned pull once the ingestion scripts exist)."
        )
    return pd.read_csv(RAW_DATA_PATH)


def build_tehsil_status(enriched: pd.DataFrame) -> pd.DataFrame:
    """One row per tehsil: latest-year status + how much of the full-period
    change in water table is attributable to natural vs. human drivers."""
    rows = []
    for tehsil in TEHSIL_NAMES:
        sub = enriched[enriched["tehsil"] == tehsil].sort_values(["year"])
        first_year = sub["year"].min()
        last_year = sub["year"].max()

        earliest = sub[sub["year"] == first_year]
        latest = sub[sub["year"] == last_year]

        natural_change = latest["baseline_pred"].mean() - earliest["baseline_pred"].mean()
        human_change = latest["human_residual"].mean() - earliest["human_residual"].mean()
        total_change = natural_change + human_change

        denom = abs(natural_change) + abs(human_change)
        natural_pct = 100.0 * abs(natural_change) / denom if denom > 1e-9 else 50.0
        human_pct = 100.0 - natural_pct

        rows.append({
            "tehsil": tehsil,
            "first_year": int(first_year),
            "last_year": int(last_year),
            "latest_observed_water_table_m": round(latest["observed_water_table_m"].mean(), 3),
            "latest_baseline_pred_m": round(latest["baseline_pred"].mean(), 3),
            "latest_human_residual_m": round(latest["human_residual"].mean(), 3),
            "natural_change_m": round(natural_change, 3),
            "human_change_m": round(human_change, 3),
            "total_change_m": round(total_change, 3),
            "natural_pct": round(natural_pct, 1),
            "human_pct": round(human_pct, 1),
        })
    return pd.DataFrame(rows)


def main():
    print("Loading data...")
    df = load_data()

    print("Training Stage 1 — Climate Baseline Model (natural features only)...")
    baseline_fit = train_baseline_model(df)
    print(f"  Baseline: MAE={baseline_fit.mae:.3f} m, R2={baseline_fit.r2:.3f} (held-out test split)")
    save_baseline_model(baseline_fit.model, baseline_fit.feature_columns)

    encoded = add_encodings(df)
    baseline_pred_full = predict_baseline(baseline_fit.model, baseline_fit.feature_columns, encoded)

    enriched = df.copy()
    enriched["baseline_pred"] = baseline_pred_full
    enriched["human_residual"] = enriched["observed_water_table_m"] - enriched["baseline_pred"]

    print("Training Stage 2 — Residual Extraction Model (anthropogenic features only)...")
    residual_fit = train_residual_model(df, baseline_pred_full)
    print(f"  Residual:  MAE={residual_fit.mae:.3f} m, R2={residual_fit.r2:.3f} (held-out test split)")
    save_residual_model(residual_fit.model, residual_fit.feature_columns)

    print("Building tehsil status summary + fitting risk thresholds...")
    status = build_tehsil_status(enriched)
    thresholds = fit_thresholds(status["latest_human_residual_m"])
    save_thresholds(thresholds)
    status["risk_category"] = classify_series(status["latest_human_residual_m"], thresholds)

    enriched.to_csv(ENRICHED_PATH, index=False)
    status.to_csv(STATUS_PATH, index=False)
    print(f"Wrote {ENRICHED_PATH}")
    print(f"Wrote {STATUS_PATH}")
    print("\nRisk category counts:")
    print(status["risk_category"].value_counts().reindex(
        ["Safe", "Semi-Critical", "Critical", "Over-Exploited"]
    ).fillna(0).astype(int).to_string())


if __name__ == "__main__":
    main()
