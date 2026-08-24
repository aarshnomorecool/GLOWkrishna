"""
Stage 2 — Residual Extraction (the attribution step).

residual = observed_water_table - climate_baseline_prediction

That residual is regressed against anthropogenic features only (crop
water-intensity, borewell density, irrigation proxy) to quantify
human-attributable depletion pressure per tehsil/season. This model never
sees rainfall, temperature, or tehsil identity — see claude.md's framing
note: the residual is not pure human signal (it also absorbs model error
and unmeasured natural variables), so keep it scoped to what it can
actually claim to explain.
"""

from dataclasses import dataclass

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

from src.config import MODELS_DIR
from src.features import add_encodings, residual_feature_columns, residual_monotonic_constraints

RESIDUAL_MODEL_PATH = MODELS_DIR / "residual_model.joblib"


@dataclass
class ResidualFitResult:
    model: RandomForestRegressor
    mae: float
    r2: float
    feature_columns: list


def compute_residual(df: pd.DataFrame, baseline_pred) -> pd.Series:
    observed = df[["observed_water_table_m"]].reset_index(drop=True)["observed_water_table_m"]
    return observed - pd.Series(baseline_pred, index=observed.index)


def train_residual_model(df: pd.DataFrame, baseline_pred, random_state: int = 42) -> ResidualFitResult:
    encoded = add_encodings(df)
    feature_cols = residual_feature_columns()
    X = encoded[feature_cols]
    y = compute_residual(df, baseline_pred)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=random_state
    )

    model = RandomForestRegressor(
        n_estimators=300,
        max_depth=6,
        min_samples_leaf=3,
        monotonic_cst=residual_monotonic_constraints(),
        random_state=random_state,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    r2 = r2_score(y_test, preds)

    return ResidualFitResult(model=model, mae=mae, r2=r2, feature_columns=feature_cols)


def predict_residual(model: RandomForestRegressor, feature_cols: list, df_encoded: pd.DataFrame):
    return model.predict(df_encoded[feature_cols])


def save_residual_model(model: RandomForestRegressor, feature_cols: list) -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "feature_columns": feature_cols}, RESIDUAL_MODEL_PATH)


def load_residual_model():
    payload = joblib.load(RESIDUAL_MODEL_PATH)
    return payload["model"], payload["feature_columns"]
