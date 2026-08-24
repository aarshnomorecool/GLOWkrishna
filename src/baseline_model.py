"""
Stage 1 — Climate Baseline Model.

Trained on natural features only (rainfall, temperature, recharge proxy,
local hydrogeology via tehsil identity, season). Predicts what the water
table "should" be under natural conditions alone. Never sees any
anthropogenic feature — that separation is the core technical claim of
GLOW and has to hold in code, not just in the pitch (see claude.md's
Coding Conventions).
"""

from dataclasses import dataclass

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

from src.config import MODELS_DIR, TARGET
from src.features import add_encodings, baseline_feature_columns, baseline_monotonic_constraints

BASELINE_MODEL_PATH = MODELS_DIR / "baseline_model.joblib"


@dataclass
class BaselineFitResult:
    model: RandomForestRegressor
    mae: float
    r2: float
    feature_columns: list


def train_baseline_model(df: pd.DataFrame, random_state: int = 42) -> BaselineFitResult:
    encoded = add_encodings(df)
    feature_cols = baseline_feature_columns()
    X = encoded[feature_cols]
    y = encoded[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=random_state
    )

    model = RandomForestRegressor(
        n_estimators=300,
        max_depth=8,
        min_samples_leaf=3,
        monotonic_cst=baseline_monotonic_constraints(),
        random_state=random_state,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    r2 = r2_score(y_test, preds)

    return BaselineFitResult(model=model, mae=mae, r2=r2, feature_columns=feature_cols)


def predict_baseline(model: RandomForestRegressor, feature_cols: list, df_encoded: pd.DataFrame):
    return model.predict(df_encoded[feature_cols])


def save_baseline_model(model: RandomForestRegressor, feature_cols: list) -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "feature_columns": feature_cols}, BASELINE_MODEL_PATH)


def load_baseline_model():
    payload = joblib.load(BASELINE_MODEL_PATH)
    return payload["model"], payload["feature_columns"]
