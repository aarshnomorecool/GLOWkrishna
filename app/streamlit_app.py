"""
GLOW dashboard — fallback path per claude.md ("start on the fallback path
to get an ugly-but-working end-to-end demo fast"): Streamlit + Plotly +
Folium, single codebase, no separate frontend build.

Run: streamlit run app/streamlit_app.py
"""

import copy
import json
import sys
from pathlib import Path

import folium
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import GEO_DIR, PROCESSED_DIR, RISK_CATEGORIES, RISK_COLORS, TEHSIL_NAMES  # noqa: E402
from src.simulate import SandboxInputs, load_models, project_drawdown_curve, run_all_tehsils  # noqa: E402

ENRICHED_PATH = PROCESSED_DIR / "nagpur_blocks_enriched.csv"
STATUS_PATH = PROCESSED_DIR / "tehsil_status.csv"
GEOJSON_PATH = GEO_DIR / "nagpur_tehsils.geojson"

st.set_page_config(page_title="GLOW — Nagpur Groundwater Outlook", layout="wide")


@st.cache_data
def load_enriched() -> pd.DataFrame:
    return pd.read_csv(ENRICHED_PATH)


@st.cache_data
def load_status() -> pd.DataFrame:
    return pd.read_csv(STATUS_PATH)


@st.cache_data
def load_geojson() -> dict:
    return json.loads(GEOJSON_PATH.read_text())


@st.cache_resource
def get_model_bundle():
    return load_models()


def missing_artifacts() -> list:
    missing = []
    for p in (ENRICHED_PATH, STATUS_PATH, GEOJSON_PATH):
        if not p.exists():
            missing.append(str(p))
    return missing


missing = missing_artifacts()
if missing:
    st.error(
        "Model artifacts / processed data not found:\n\n"
        + "\n".join(f"- {m}" for m in missing)
        + "\n\nRun `python scripts/generate_synthetic_data.py` then `python -m src.train` first."
    )
    st.stop()

enriched = load_enriched()
status = load_status()
geojson_data = load_geojson()
bundle = get_model_bundle()

if "selected_tehsil" not in st.session_state:
    st.session_state.selected_tehsil = status.sort_values("latest_human_residual_m", ascending=False).iloc[0]["tehsil"]

# ---------------------------------------------------------------- sidebar --
st.sidebar.title("GLOW")
st.sidebar.caption("Groundwater Level Outlook & Water-policy Intelligence — Nagpur district pilot")

st.sidebar.subheader("Select block")
selected = st.sidebar.selectbox(
    "Tehsil", TEHSIL_NAMES, index=TEHSIL_NAMES.index(st.session_state.selected_tehsil)
)
st.session_state.selected_tehsil = selected

st.sidebar.subheader("Policy Sandbox")
st.sidebar.caption("Sliders perturb the block's latest conditions and re-run both model stages live.")
rainfall_pct = st.sidebar.slider("Rainfall change (%)", -50, 50, 0, step=5)
drip_pct = st.sidebar.slider("Drip-irrigation adoption (%)", 0, 100, 0, step=5)
borewell_pct = st.sidebar.slider("Borewell growth (%/yr)", -10, 20, 0, step=1)

if st.sidebar.button("Reset sliders"):
    st.rerun()

map_view = st.sidebar.radio("Map colors show:", ["Current policy scenario", "Today (no changes)"], index=0)

inputs = SandboxInputs(
    rainfall_pct_change=rainfall_pct,
    drip_irrigation_adoption_pct=drip_pct,
    borewell_growth_pct=borewell_pct,
)
scenario_df = run_all_tehsils(enriched, bundle, inputs)

# ------------------------------------------------------------------ title --
st.title("GLOW — Nagpur District Groundwater Outlook")
st.caption(
    "Splits water-table depletion into natural climate-driven and human-attributable "
    "components, and lets officials simulate policy interventions before spending public funds. "
    "**Synthetic pilot data** — see README for what's real vs. placeholder."
)

# ------------------------------------------------------------ summary strip --
display_df = scenario_df if map_view == "Current policy scenario" else status.rename(
    columns={"latest_human_residual_m": "human_residual_pred_m"}
)
counts = display_df["risk_category"].value_counts().reindex(RISK_CATEGORIES).fillna(0).astype(int)

cols = st.columns(4)
for col, cat in zip(cols, RISK_CATEGORIES):
    with col:
        st.markdown(
            f"""<div style="border-left:6px solid {RISK_COLORS[cat]}; padding:8px 12px;
            background:rgba(127,127,127,0.08); border-radius:4px;">
            <div style="font-size:0.85em; opacity:0.75;">{cat}</div>
            <div style="font-size:1.8em; font-weight:600;">{counts[cat]}</div>
            <div style="font-size:0.75em; opacity:0.6;">of 14 blocks</div>
            </div>""",
            unsafe_allow_html=True,
        )

st.write("")

# --------------------------------------------------------------- map + panel --
map_col, panel_col = st.columns([3, 2])

with map_col:
    st.subheader("Nagpur district — risk map")
    st.caption(f"Coloring: **{map_view}**. Click a block to inspect it below.")

    status_lookup = display_df.set_index("tehsil")

    geo = copy.deepcopy(geojson_data)
    for feat in geo["features"]:
        name = feat["properties"]["tehsil"]
        row = status_lookup.loc[name]
        feat["properties"]["risk_category"] = row["risk_category"]
        feat["properties"]["human_residual_m"] = round(float(row["human_residual_pred_m"]), 2)

    center_lat = sum(f["geometry"]["coordinates"][0][0][1] for f in geo["features"]) / len(geo["features"])
    center_lon = sum(f["geometry"]["coordinates"][0][0][0] for f in geo["features"]) / len(geo["features"])
    # CartoDB's "positron" alias now gates its tiles behind an API key (shows
    # "API KEY REQUIRED" watermarks without one). OpenStreetMap's tile server
    # needs no key and is the most reliable free option for this.
    m = folium.Map(location=[center_lat, center_lon], zoom_start=9, tiles="OpenStreetMap")

    def style_function(feature, _selected=st.session_state.selected_tehsil):
        name = feature["properties"]["tehsil"]
        category = feature["properties"]["risk_category"]
        is_selected = name == _selected
        return {
            "fillColor": RISK_COLORS.get(category, "#999999"),
            "color": "#111111" if is_selected else "#555555",
            "weight": 3 if is_selected else 1,
            "fillOpacity": 0.75 if is_selected else 0.55,
        }

    folium.GeoJson(
        geo,
        name="tehsils",
        style_function=style_function,
        highlight_function=lambda f: {"weight": 3, "fillOpacity": 0.9},
        tooltip=folium.GeoJsonTooltip(
            fields=["tehsil", "risk_category", "human_residual_m"],
            aliases=["Tehsil:", "Risk category:", "Human-attributable residual (m):"],
        ),
    ).add_to(m)

    map_output = st_folium(m, height=520, use_container_width=True, key="nagpur_map")

    legend_html = " &nbsp;&nbsp; ".join(
        f'<span style="display:inline-block;width:10px;height:10px;background:{RISK_COLORS[c]};'
        f'border-radius:2px;margin-right:4px;"></span>{c}'
        for c in RISK_CATEGORIES
    )
    st.markdown(legend_html, unsafe_allow_html=True)

    clicked = map_output.get("last_active_drawing") if map_output else None
    if clicked and clicked.get("properties", {}).get("tehsil"):
        clicked_tehsil = clicked["properties"]["tehsil"]
        if clicked_tehsil != st.session_state.selected_tehsil:
            st.session_state.selected_tehsil = clicked_tehsil
            st.rerun()

with panel_col:
    tehsil = st.session_state.selected_tehsil
    row_status = status[status["tehsil"] == tehsil].iloc[0]
    row_scenario = scenario_df[scenario_df["tehsil"] == tehsil].iloc[0]

    st.subheader(tehsil)
    badge_color = RISK_COLORS[row_scenario["risk_category"]]
    st.markdown(
        f"""<span style="background:{badge_color}; color:white; padding:3px 10px;
        border-radius:12px; font-size:0.85em; font-weight:600;">{row_scenario['risk_category']}</span>
        <span style="opacity:0.7; font-size:0.85em;"> under current sandbox scenario</span>""",
        unsafe_allow_html=True,
    )

    st.markdown("**Plain-language summary**")
    today_cat = row_status["risk_category"]
    scenario_cat = row_scenario["risk_category"]
    if scenario_cat == today_cat:
        shift_text = "no change in risk category from today's classification."
    else:
        order = {c: i for i, c in enumerate(RISK_CATEGORIES)}
        shift_text = (
            f"a **downgrade** from today's **{today_cat}** to **{scenario_cat}**."
            if order[scenario_cat] > order[today_cat]
            else f"an **improvement** from today's **{today_cat}** to **{scenario_cat}**."
        )
    st.write(
        f"Over the recorded period, an estimated **{row_status['human_pct']:.0f}%** of the change in "
        f"{tehsil}'s water table is attributable to human activity (borewell density, cropping patterns, "
        f"irrigation), with the remainder explained by natural rainfall/temperature variation. "
        f"Under the sliders set on the left, the model projects {shift_text}"
    )

    st.markdown("**Drawdown curve** (depth to water, lower is better)")
    curve = project_drawdown_curve(enriched, bundle, tehsil, inputs, horizon_years=10)
    fig = go.Figure()
    for segment, dash in [("Historical", "solid"), ("Projected", "dash")]:
        sub = curve[curve["segment"] == segment]
        fig.add_trace(go.Scatter(
            x=sub["year"], y=sub["water_table_m"], mode="lines+markers",
            name=segment, line=dict(dash=dash),
        ))
    fig.update_layout(
        height=280, margin=dict(l=10, r=10, t=10, b=10),
        yaxis=dict(autorange="reversed", title="m below ground"),
        xaxis=dict(title=None),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, width="stretch")

    st.markdown("**Attribution split** (natural vs. human-attributable, full-period trend)")
    fig2 = go.Figure(go.Bar(
        x=[row_status["natural_pct"], row_status["human_pct"]],
        y=["Attribution"], orientation="h",
        marker_color=["#5c8fd6", "#d67c5c"],
        text=[f"Natural {row_status['natural_pct']:.0f}%", f"Human {row_status['human_pct']:.0f}%"],
        textposition="inside",
    ))
    fig2.update_layout(
        height=110, margin=dict(l=10, r=10, t=10, b=10),
        barmode="stack", showlegend=False,
        xaxis=dict(visible=False, range=[0, 100]), yaxis=dict(visible=False),
    )
    st.plotly_chart(fig2, width="stretch")

    with st.expander("Scenario numbers"):
        st.write(
            {
                "Climate baseline (stage 1) prediction, m": round(float(row_scenario["baseline_pred_m"]), 3),
                "Human-attributable residual (stage 2) prediction, m": round(float(row_scenario["human_residual_pred_m"]), 3),
                "Projected total, m below ground": round(float(row_scenario["projected_water_table_m"]), 3),
            }
        )

st.divider()
st.caption(
    "GLOW (formerly AQUASENSE) — Smart India Hackathon PS 1696. Model: interpretable "
    "two-stage RandomForest (monotonic-constrained) — see claude.md for full architecture notes."
)
