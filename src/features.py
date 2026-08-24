"""
Feature engineering shared by training and inference. Kept as one module
(rather than duplicated in train.py and simulate.py) so the sandbox's
single perturbed row gets encoded exactly the way the models were trained.
"""

import pandas as pd

from src.config import ANTHRO_FEATURES, NATURAL_FEATURES, SEASONS, TEHSIL_NAMES


def _one_hot(df: pd.DataFrame, column: str, categories: list) -> pd.DataFrame:
    cat = pd.Categorical(df[column], categories=categories)
    dummies = pd.get_dummies(cat, prefix=column)
    return pd.concat([df.reset_index(drop=True), dummies.reset_index(drop=True)], axis=1)


def add_encodings(df: pd.DataFrame) -> pd.DataFrame:
    """Adds fixed-width one-hot columns for season and tehsil so a
    single-row inference frame (used by the sandbox) lines up column-for-
    column with the training matrix, even though it only ever contains one
    category of each."""
    df = _one_hot(df, "season", SEASONS)
    df = _one_hot(df, "tehsil", TEHSIL_NAMES)
    return df


def baseline_feature_columns() -> list:
    """Stage 1 sees natural drivers plus tehsil identity (local
    hydrogeology is a natural variable, not a human one) and season — but
    never any anthropogenic feature."""
    return (
        NATURAL_FEATURES
        + ["rainfall_mm_lag1"]
        + [f"season_{s}" for s in SEASONS]
        + [f"tehsil_{t}" for t in TEHSIL_NAMES]
    )


def residual_feature_columns() -> list:
    """Stage 2 sees only anthropogenic proxies (plus season for mild
    seasonal-demand structure) — never rainfall/temperature/tehsil, so the
    attribution story stays honest to what actually drove it."""
    return ANTHRO_FEATURES + [f"season_{s}" for s in SEASONS]


# Monotonic direction each feature is known a priori to push the target
# (+1 deeper/worse, -1 shallower/better, 0 unconstrained). This is what
# keeps the Policy Sandbox trustworthy: without it, a tree ensemble can
# learn a locally noisy, sign-flipped relationship for a weakly-predictive
# feature, so pushing a slider the "worse" direction could show a block
# getting *safer* — a demo-breaking bug for an interactive what-if tool,
# even though it wouldn't show up as an error in offline MAE/R2 metrics.
_BASELINE_DIRECTIONS = {
    "rainfall_mm": -1,
    "temperature_c": 1,
    "recharge_proxy": -1,
    "rainfall_mm_lag1": -1,
}

_RESIDUAL_DIRECTIONS = {
    "crop_water_intensity_index": 1,
    "borewell_density": 1,
    "irrigation_census_proxy": 1,
}


def baseline_monotonic_constraints() -> list:
    return [_BASELINE_DIRECTIONS.get(col, 0) for col in baseline_feature_columns()]


def residual_monotonic_constraints() -> list:
    return [_RESIDUAL_DIRECTIONS.get(col, 0) for col in residual_feature_columns()]
