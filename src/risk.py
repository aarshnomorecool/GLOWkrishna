"""
Risk classification — buckets tehsils into IN-GRES-style categories
(Safe / Semi-Critical / Critical / Over-Exploited) using quantile
thresholds fit once on the historical human-residual distribution across
Nagpur's 14 tehsils.

claude.md's Known Challenges section is explicit that there's no labeled
ground truth for the attribution split, so this is a placeholder heuristic
— it ranks tehsils' human-attributable pressure against each other, not
against IN-GRES's actual draft-to-recharge-ratio definition. Swapping in
real stage-of-extraction data later means replacing fit_thresholds'
input, not the classification logic.
"""

import json

import pandas as pd

from src.config import MODELS_DIR, RISK_CATEGORIES

THRESHOLDS_PATH = MODELS_DIR / "risk_thresholds.json"


def fit_thresholds(values: pd.Series) -> dict:
    """25/50/75th percentile cut points computed once on the reference
    (unperturbed, latest-year) tehsil population. The sandbox reuses these
    saved thresholds rather than recomputing quantiles on every slider
    move, so a block's category shifts relative to a fixed reference
    instead of a population that's also moving under it."""
    q = values.quantile([0.25, 0.5, 0.75])
    return {"q25": float(q.loc[0.25]), "q50": float(q.loc[0.5]), "q75": float(q.loc[0.75])}


def save_thresholds(thresholds: dict) -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    THRESHOLDS_PATH.write_text(json.dumps(thresholds, indent=2))


def load_thresholds() -> dict:
    return json.loads(THRESHOLDS_PATH.read_text())


def classify(value: float, thresholds: dict) -> str:
    if value <= thresholds["q25"]:
        return RISK_CATEGORIES[0]
    if value <= thresholds["q50"]:
        return RISK_CATEGORIES[1]
    if value <= thresholds["q75"]:
        return RISK_CATEGORIES[2]
    return RISK_CATEGORIES[3]


def classify_series(values: pd.Series, thresholds: dict) -> pd.Series:
    return values.apply(lambda v: classify(v, thresholds))
