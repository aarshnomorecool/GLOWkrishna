"""
Shared constants for the GLOW pipeline: tehsil registry, schema, and
classification thresholds. Centralized here so data generation, modeling,
simulation, and the dashboard all agree on the same shape.
"""

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
PROCESSED_DIR = DATA_DIR / "processed"
GEO_DIR = DATA_DIR / "geo"
MODELS_DIR = ROOT_DIR / "models"

# Nagpur district, 14 tehsils. Centroids are approximate (public-domain
# town-location knowledge, not a surveyed source) and only used to place
# placeholder polygons — see data/geo/README.md for why these aren't the
# real GSDA/datameet boundaries yet.
TEHSILS = {
    "Nagpur Urban":  (21.1458, 79.0882),
    "Nagpur Rural":  (21.2050, 78.9550),
    "Kamptee":       (21.2333, 79.2000),
    "Hingna":        (21.0700, 78.9200),
    "Katol":         (21.2667, 78.5833),
    "Narkhed":       (21.4667, 78.5333),
    "Savner":        (21.3833, 78.8000),
    "Kalmeshwar":    (21.2333, 78.8333),
    "Ramtek":        (21.4000, 79.3333),
    "Mouda":         (21.3833, 79.4833),
    "Parseoni":      (21.3167, 79.2500),
    "Umred":         (20.8500, 79.3333),
    "Kuhi":          (20.9667, 79.4333),
    "Bhiwapur":      (20.7667, 79.5000),
}

TEHSIL_NAMES = list(TEHSILS.keys())

SEASONS = ["Pre-Monsoon", "Monsoon", "Post-Monsoon", "Winter"]

YEAR_START = 2010
YEAR_END = 2024  # inclusive

NATURAL_FEATURES = [
    "rainfall_mm",
    "temperature_c",
    "recharge_proxy",
]

ANTHRO_FEATURES = [
    "crop_water_intensity_index",
    "borewell_density",
    "irrigation_census_proxy",
]

LAG_FEATURES = [
    "rainfall_mm_lag1",
    "observed_water_table_m_lag1",
]

TARGET = "observed_water_table_m"

# Risk buckets, deliberately using IN-GRES's own category language so the
# dashboard reads as familiar to district officials rather than inventing
# new terminology.
RISK_CATEGORIES = ["Safe", "Semi-Critical", "Critical", "Over-Exploited"]

RISK_COLORS = {
    "Safe": "#2e7d32",
    "Semi-Critical": "#f9a825",
    "Critical": "#ef6c00",
    "Over-Exploited": "#c62828",
}
