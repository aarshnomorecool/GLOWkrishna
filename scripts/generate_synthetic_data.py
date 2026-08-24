"""
Generates a STAND-IN dataset shaped exactly like the real Tier-1 pipeline
described in claude.md (CGWB/India-WRIS water table, IMD rainfall/temperature,
data.gov.in crop stats, Minor Irrigation Census borewell counts).

This exists so the modeling and dashboard layers can be built and demoed
before the real data-ingestion scripts (WFS pulls, datagovindia API calls)
are wired up. It is NOT real groundwater data. Swap this file's output for
real pulls into data/raw/ + a real cleaning step without touching any
downstream code, since the column schema is what the rest of the pipeline
depends on, not this generator.

Run: python scripts/generate_synthetic_data.py
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.config import (  # noqa: E402
    GEO_DIR,
    PROCESSED_DIR,
    SEASONS,
    TEHSILS,
    YEAR_END,
    YEAR_START,
)

RNG = np.random.default_rng(42)

# Seasonal natural-climate patterns (rough Vidarbha climatology, illustrative).
SEASON_RAINFALL_MM = {"Pre-Monsoon": 60, "Monsoon": 650, "Post-Monsoon": 120, "Winter": 20}
SEASON_TEMP_C = {"Pre-Monsoon": 34, "Monsoon": 27, "Post-Monsoon": 26, "Winter": 21}


def _tehsil_hydrogeology_params(rng):
    """Per-tehsil fixed traits that make some blocks structurally worse off
    than others (shallow hard-rock aquifer vs. alluvial, cropping pattern
    baseline, etc.) — otherwise every tehsil would look identical."""
    params = {}
    for name in TEHSILS:
        params[name] = {
            "base_depth_m": rng.uniform(7.0, 18.0),          # natural depth-to-water baseline
            "soil_recharge_factor": rng.uniform(0.55, 0.95),  # fraction of rain that recharges
            "crop_intensity_base": rng.uniform(20, 55),       # 0-100 scale
            "borewell_base": rng.uniform(5, 25),              # wells per sq km
            "irrigation_base": rng.uniform(15, 50),           # 0-100 scale
            "agri_growth_rate": rng.uniform(0.4, 2.2),        # how fast extraction pressure rises/yr
        }
    return params


def generate() -> pd.DataFrame:
    hydro = _tehsil_hydrogeology_params(RNG)
    years = list(range(YEAR_START, YEAR_END + 1))
    rows = []

    for tehsil in TEHSILS:
        p = hydro[tehsil]
        prev_water_table = p["base_depth_m"]

        for i, year in enumerate(years):
            years_elapsed = i  # drives cumulative agricultural intensification
            for season in SEASONS:
                # --- Natural features ---
                rainfall = max(
                    0.0,
                    RNG.normal(SEASON_RAINFALL_MM[season] * (1 + RNG.uniform(-0.05, 0.05)), SEASON_RAINFALL_MM[season] * 0.22),
                )
                temperature = RNG.normal(SEASON_TEMP_C[season], 1.3)
                recharge_proxy = float(np.clip(p["soil_recharge_factor"] * (rainfall / 700.0) + RNG.normal(0, 0.03), 0, 1.2))

                # --- Anthropogenic features (trend upward over the 15 yrs = intensification) ---
                crop_water_intensity_index = float(np.clip(
                    p["crop_intensity_base"] + p["agri_growth_rate"] * years_elapsed + RNG.normal(0, 3), 0, 100
                ))
                borewell_density = float(max(
                    0.0, p["borewell_base"] + 0.35 * p["agri_growth_rate"] * years_elapsed + RNG.normal(0, 1.0)
                ))
                irrigation_census_proxy = float(np.clip(
                    p["irrigation_base"] + 0.9 * p["agri_growth_rate"] * years_elapsed + RNG.normal(0, 2.5), 0, 100
                ))

                # --- Climate baseline (natural-only signal) ---
                rain_z = (rainfall - SEASON_RAINFALL_MM[season]) / max(SEASON_RAINFALL_MM[season], 1)
                climate_baseline = (
                    p["base_depth_m"]
                    - 3.0 * rain_z
                    - 4.0 * (recharge_proxy - 0.5)
                    + 0.05 * (temperature - 27)
                    + RNG.normal(0, 0.25)
                )

                # --- Human-attributable residual (what stage-2 should recover) ---
                human_residual = (
                    0.035 * crop_water_intensity_index
                    + 0.06 * borewell_density
                    + 0.02 * irrigation_census_proxy
                    + RNG.normal(0, 0.3)
                )

                observed_water_table_m = max(0.5, climate_baseline + human_residual)

                rows.append({
                    "tehsil": tehsil,
                    "year": year,
                    "season": season,
                    "rainfall_mm": round(rainfall, 1),
                    "temperature_c": round(temperature, 1),
                    "recharge_proxy": round(recharge_proxy, 3),
                    "crop_water_intensity_index": round(crop_water_intensity_index, 2),
                    "borewell_density": round(borewell_density, 2),
                    "irrigation_census_proxy": round(irrigation_census_proxy, 2),
                    "observed_water_table_m": round(observed_water_table_m, 3),
                    # kept only for sanity-checking the generator itself; not
                    # a feature and not used by the model at inference time.
                    "_true_human_residual_m": round(human_residual, 3),
                })

    df = pd.DataFrame(rows)
    # SEASONS is in true chronological order (Pre-Monsoon -> Monsoon ->
    # Post-Monsoon -> Winter); sorting by season name alphabetically would
    # scramble that before the lag features below are computed.
    season_rank = {s: i for i, s in enumerate(SEASONS)}
    df["_season_rank"] = df["season"].map(season_rank)
    df = df.sort_values(["tehsil", "year", "_season_rank"]).drop(columns="_season_rank").reset_index(drop=True)

    # Lag features (extraction/depletion effects aren't instantaneous —
    # see "Temporal lag" in claude.md's Known Challenges).
    df["rainfall_mm_lag1"] = df.groupby("tehsil")["rainfall_mm"].shift(1)
    df["observed_water_table_m_lag1"] = df.groupby("tehsil")["observed_water_table_m"].shift(1)
    df = df.dropna().reset_index(drop=True)

    return df


def generate_geojson() -> dict:
    """Simplified placeholder polygons (small squares centered on each
    tehsil's approximate centroid). Real boundaries should come from GSDA
    GIS layers or the datameet community boundary repo per claude.md —
    this exists purely so the choropleth has something to render."""
    half = 0.055  # degrees, ~6km — deliberately small to limit overlap
    features = []
    for name, (lat, lon) in TEHSILS.items():
        coords = [[
            [lon - half, lat - half],
            [lon + half, lat - half],
            [lon + half, lat + half],
            [lon - half, lat + half],
            [lon - half, lat - half],
        ]]
        features.append({
            "type": "Feature",
            "properties": {"tehsil": name},
            "geometry": {"type": "Polygon", "coordinates": coords},
        })
    return {"type": "FeatureCollection", "features": features}


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    GEO_DIR.mkdir(parents=True, exist_ok=True)

    df = generate()
    out_csv = PROCESSED_DIR / "nagpur_blocks.csv"
    df.to_csv(out_csv, index=False)
    print(f"Wrote {len(df):,} rows -> {out_csv}")

    geojson = generate_geojson()
    out_geo = GEO_DIR / "nagpur_tehsils.geojson"
    out_geo.write_text(json.dumps(geojson, indent=2))
    print(f"Wrote {len(geojson['features'])} tehsil polygons -> {out_geo}")


if __name__ == "__main__":
    main()
