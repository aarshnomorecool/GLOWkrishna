# GLOW Frontend — Buttons, Interactions & Process Rules

Source of truth for how the separated frontend behaves.
Files: `frontend/index.html` (markup) · `frontend/styles.css` (styling) · `frontend/app.js` (behavior).
Backend: `src/api.py` serves `GET /` → `index.html`, `GET /styles.css`, `GET /app.js`,
`GET /assets/nagpur_tehsils.geojson`, `GET /api/tehsils`, `POST /api/simulate`.

Deliberately removed: the sidebar SVG logo (`svg.brand-mark`, all `.brand-mark` CSS —
the sidebar now shows plain "GLOW / Vidarbha pilot" text only) and the entire 3D hero
(Three.js CDN, `#hero-canvas`, `.hero canvas` CSS, `initHero()` and its call —
the hero is a static banner). No ML retraining happens at request time; the UI only
calls inference endpoints. Do not retrain until the new dataset is provided.

## 0. Global principles

1. API-first with preview fallback. On load the app tries `GET /api/tehsils`. If it fails,
   the dashboard keeps working on built-in preview constants (`TEHSILS[].base`, `humanRatio`)
   with simplified linear slider effects. A console warning is logged; the UI does not block.
2. Inference only. Slider/report/map actions never retrain. `POST /api/simulate` runs the
   persisted two-stage models on one perturbed row per tehsil and returns scores + drawdown.
3. Single selection at a time. `state.selectedTehsil` (dashboard detail) and
   `state.sandboxFocus` (sandbox chart + map highlight) each hold at most one tehsil id.
4. Risk buckets are fixed: score `< 35` Safe · `< 55` Semi-Critical · `< 75` Critical ·
   otherwise Over-Exploited. Colors/tokens live in CSS variables; labels in `RISK` (app.js).

## 1. App shell / navigation

- Five sidebar buttons (`.navitem[data-view]`): Dashboard, Policy Sandbox, Reports,
  Data Sources, How It Works.
- Rule: clicking a nav item calls `switchView(view)` — removes `.active` from all
  `.view` sections, adds it to `#view-<name>`, toggles `.active` on nav items, updates
  `#view-title-text`, scrolls `#main` to top.
- Rule: entering the Sandbox view always triggers a full simulation run
  (`renderSandbox()` → `runSimulationImmediate()`). Other views render on demand.

## 2. Dashboard view

### 2.1 Stat-strip filter chips (`#stat-strip`)
- Four chips rendered from live counts per risk bucket (Safe / Semi-Critical / Critical /
  Over-Exploited), each showing label, swatch, count, "tehsils".
- Rule: click toggles `dashboardFilter` between that key and `null` (single-filter only),
  then re-renders the strip (active chip gets `.filtered`) and the dashboard map.
- Rule: when a filter is active, the Nagpur pilot shape gets `.dimmed` (opacity 0.22)
  unless its current risk equals the filter key.

### 2.2 Nagpur tehsil map (`svg#tehsil-map`)
- Shows all 14 Nagpur tehsils as real Survey of India polygons
  (`data/geo/nagpur_tehsils.geojson`, via `/assets/nagpur_tehsils.geojson`), projected
  to fit 640×460 (margin 26) from a SINGLE global fit so shared borders coincide
  exactly with no gaps. Every tehsil is interactive (`.is-pilot`, pointer cursor) and
  filled with its OWN risk color (`var(--safe|semi|critical|over)` from that tehsil's
  live score). Labels show short tehsil codes (NGP-U, KAM, …) at precomputed
  inside-polygon anchors (`labelLon`/`labelLat` in the GeoJSON).
- Rule: click on any tehsil calls `onClick(<that tehsil id>)` → `selectTehsil(id)`.
- Rule: hovering any tehsil shows `#map-tooltip` positioned at the cursor with
  "<b>name</b> · risk label"; mouse-leave hides it. Tooltip only exists on the
  dashboard map (the sandbox map passes no hover handlers).
- Rule: the selected tehsil's shape gets `.selected` (dark 3px stroke).

### 2.3 Tehsil detail panel
- Empty state (`#detail-empty`) shows until a selection exists. `selectTehsil(id)` hides
  it, shows `#detail-content`, and sets: `#detail-name`, badge (`#detail-badge` background
  / text / dot from risk key), `#detail-statement` via `plainLanguage()` —
  "<Name> is <label>. Roughly <human>% of its stress traces back to extraction and
  cropping, not rainfall." — then draws both charts, writes the attribution legend
  (Human extraction `<human>%` / Natural climate `<natural>%`), and re-renders the map.
- Drawdown chart (`#drawdown-chart`): two lines — "Observed / projected" (solid history,
  dashed `[5,4]` segment from `splitIndex` onward) vs "Climate-only baseline" (dashed
  `[2,3]`). Data priority: (1) `state.scenarioData.tehsil.drawdown` when sliders are active
  for that tehsil, (2) `state.baselineData[tid].drawdown` at default sliders,
  (3) local synthetic fallback. Y-axis: "metres below ground".
- Attribution donut (`#attrib-chart`): doughnut, cutout 68%, no legend;
  Human slice `var(--critical)`, Natural slice `var(--aquifer)`.
- Buttons:
  - "Open in Sandbox" (`#open-in-sandbox-btn`): no-op when nothing is selected; otherwise
    sets `state.sandboxFocus = state.selectedTehsil` and switches to the Sandbox view.
  - "Export report" (`#export-report-btn`): creates a report scoped to the selected tehsil
    (or district-wide if none), switches to Reports view, toasts "Report generated".

## 3. Policy Sandbox view

- Focus label (`#sandbox-focus-name`) always shows the focused tehsil's display name.
- Sliders and their rules:

  | Slider | Element | Range | Default | Label rule |
  |---|---|---|---|---|
  | Rainfall change | `#slider-rainfall` | −30…+30 step 1 | 0 | `#val-rainfall` shows signed `%` (`fmtPct`: "+5%", "−3%", "0%") |
  | Drip-irrigation adoption | `#slider-drip` | 0…100 step 1 | 20 | `#val-drip` shows plain `"20%"` (no sign) |
  | Borewell growth | `#slider-borewell` | −20…+50 step 1 | 0 | `#val-borewell` shows signed `%` |

- Rule: `input` events update `state.sliders` + the value label immediately, then call
  `debouncedRunSimulation()` (180 ms trailing debounce; rapid drags produce one request).
- Rule: `runSimulationImmediate()` re-writes all three value labels, awaits
  `POST /api/simulate {rainfall, drip, borewell, tehsil_id}`, stores the response in
  `state.scenarioData`, then re-renders the sandbox map and the focus drawdown chart.
- Sandbox map (`svg#tehsil-map-sandbox`): same renderer, driven by `state.sliders`;
  click sets `state.sandboxFocus` and runs an immediate (non-debounced) simulation.
  No tooltip, no filter dimming on this map.
- "Reset sliders" (`#reset-sliders-btn`): restores `{rainfall: 0, drip: 20, borewell: 0}`,
  writes the values back into all three inputs, runs immediately, toasts "Sliders reset".
- "Save scenario" (`#save-scenario-btn`): unshifts
  `"<Focus> · rain <±%>, drip <n>%, wells <±%>"` + `"Saved just now"` + a copy of
  `state.sliders` onto `state.scenarios`, re-renders the list, toasts "Scenario saved".
- Saved-scenario "Load" buttons: restore the stored slider copy into `state.sliders`,
  write all three inputs, run immediately, toast "Scenario loaded".
- Empty scenario list shows "No scenarios saved yet."

## 4. Reports view

- "Generate report" (`#generate-report-btn`): creates a report for the selected tehsil
  (or district-wide), prepends it, re-renders, toasts "Report generated".
- `addReport(tehsilId)` rule: scope = tehsil display name or "District-wide"; risk =
  that tehsil's label or "Mixed"; human% = that tehsil's split or the 14-tehsil mean;
  date = `en-IN` "02 Sep 2026" style; filename = `GLOW_<sanitized-scope>.pdf`
  (non-alphanumerics → `_`); status always "Ready"; newest first.
- Empty list shows the "No reports yet…" illustration.
- Row buttons: "View" opens the detail modal (Scope / Risk category / Human share /
  Generated rows + "Download PDF" button that closes the modal and toasts
  `"Downloaded <file>"`); "Download" toasts directly without opening the modal.

## 5. Data Sources view (`#source-grid`)

- Six cards from `SOURCES`: four Tier 1 (`CGWB / India-WRIS`, `IMD Pune`, `data.gov.in`,
  `Minor Irrigation Census`) start `connected`; two Tier 2 (`GSDA Nagpur`, `MSEDCL power`,
  dashed border) start `pending` ("Not connected" / "Never synced").
- Rule (Tier 1 "Sync now"): rewrites that card's `#src-sync-<i>` to "Last synced just now"
  and toasts `"Synced <name>"`. No state change.
- Rule (Tier 2 "Connect"): sets `status = "connected"`, re-renders the grid (pill flips to
  "Connected", button becomes disabled), toasts `"Connected <name>"`.

## 6. How It Works view (`#steps-grid`)

- Four cards (Ingest & align · Two-stage model · Risk classification · Policy Sandbox),
  each with short `desc`, hidden `more`, and a "Tap for detail" hint.
- Rule: clicking a card toggles `.expanded`, which shows/hides its `.step-more` block.

## 7. Topbar: search, alerts, profile

- Search (`#search-input` / `#search-results`): case-insensitive substring match on tehsil
  names. Empty query closes the dropdown. Zero matches shows
  `No tehsil matches "<raw input>"`. Each match is a button with name + risk swatch;
  clicking it switches to Dashboard, selects the tehsil, clears the input, closes the
  dropdown. Clicking anywhere outside `.search-wrap` closes the dropdown.
- Alerts bell (`#alerts-btn` → `#alerts-dropdown`): list is the top-4 tehsils by current
  score (desc), each row "<Name> crossed into <label> this quarter. / 2 days ago" with a
  risk-colored dot. Clicking a row closes the dropdown, switches to Dashboard, selects
  that tehsil. The bell always shows the red `.badge-dot` (static indicator, not a count).
- Dropdown rule (shared): bell/avatar buttons toggle with `stopPropagation`; opening one
  closes the other; any document click closes all; clicks inside a dropdown do not close it.
- Avatar (`#profile-btn` → `#profile-dropdown`): "District Officer" header,
  "Preferences" opens the modal (see §8), "Sign out" closes the dropdown and toasts
  "Signed out" (no navigation).

## 8. Modal, toasts, preferences

- Modal (`#modal-overlay` / `#modal-body`): `openModal(html)` injects content and adds
  `.open`. Clicking the overlay backdrop itself (not its children) closes it; every modal
  also has an `.modal-close` button. Report modals contain a "Download PDF" button that
  closes the modal and toasts the filename.
- Preferences modal rows: "Dark mode" toggle (`#theme-toggle`) flips `state.theme`,
  sets `document.documentElement[data-theme]`, re-renders open charts via
  `refreshOpenCharts()` (re-select dashboard tehsil, re-run sandbox when visible), and
  toasts on/off. "Compact numbers" toggle (`#compact-toggle`) flips
  `state.compactNumbers` state only (no visual change wired yet).
- Toasts (`#toast-stack`): dark pill + check icon + message; auto-dismiss after 2.6 s
  with a 200 ms fade/slide. Fire-and-forget; no stacking limit or action buttons.

## 9. Startup & data processes (`init()` order)

1. `fetchTehsilsFromAPI()` → `GET /api/tehsils` fills `state.baselineData` keyed by id
   and sets `apiConnected`; on failure the app continues in preview mode.
2. `loadNagpurTehsilBoundaries()` → fetches local `/assets/nagpur_tehsils.geojson`
   (Survey of India polygons, ids pre-matched to the 14 app tehsils); keeps the
   response only if all 14 tehsils match; projects lon/lat bounds to the 640×460
   viewBox with one global fit so shared borders align exactly.
3. Render stat strip → dashboard map → both legends → alerts → sources → steps → reports.
4. `runSimulationImmediate()` (default sliders, default focus `nagpur-urban`).
5. `selectTehsil("nagpur-urban")` so the detail panel is never empty on first paint.
6. Map "Loading Nagpur tehsil boundaries…" text shows inside any map SVG while
   `tehsilFeatures` is empty (e.g. offline boundaries).
