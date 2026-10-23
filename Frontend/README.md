# Antidote UI only

Deployment integration now lives in [the repository deployment guide](../README.md).
The notes below describe the original UI handoff contract. The repository now
also includes the FastAPI adapter, chart jobs, and Netlify/Render configurations.
Production Mapbox assets use the pinned official CDN rather than `/map-assets`.

This folder contains 34 files: the approved dashboard's browser code, styles,
font/license assets, this guide and the application license. No backend, models,
datasets, tests, npm installation, lockfile, build tooling or component reference
examples are included. The full source handoff retains those development files.

Upload this entire `Frontend/` folder at the team repository root. The page is
`tracking/index.html`; keep the relative module and asset paths intact. The
live dashboard is not changed by packaging. This is a frontend-only replacement
for the earlier upload; the team's backend must implement the routes below.

## Included interface

- All six graphs: Monthly ETA error, Average ETA change, Arrival convergence,
  Poisoning stress curve, Poisoning impact and Forecast stability.
- Slider-linked graph scenarios, model legends, smooth monthly Y-axis refitting,
  keyboard/hover inspection, numeric progress, coverage and Retry states.
- The project overview and rubric-aligned brief, active-vessel timeline without
  idle gaps, date pickers, playback controls and vessel name tags.
- Independent original/disrupted ETA comparison, replay clock and time to the
  recorded crossing, plus Antidote ETAs for every vessel on the map.
- Seven data-poisoning controls, red field-audit highlighting and the dark-red
  anomaly popup with white outline and a prominent human-review prompt.

The frontend displays supplied inference results. Backend inference, attack
generation, model artifacts and datasets remain the team's responsibility.

## Connect your backend

Serve `tracking/` as the static web root over HTTP, with API routes on the same
origin. Opening the HTML directly as a `file://` page will not connect the API.
There is no frontend build step. Use current Chrome, Edge, Firefox or Safari.
The page will show connection feedback until a compatible API is available; it
does not include mock predictions or a standalone demo backend.

The network helper is `api()` in `tracking/app.mjs`. Frame request construction
is `frameURL()` in that file. Change those if your service uses another base URL
or authentication. Monthly graph requests are in `tracking/monthly-chart.mjs`.
The coastal-map config request is in `tracking/coastal.js`.

### Required routes

| Route | Response or asset |
| --- | --- |
| `GET /api/config` | `{ "mapbox_public_token": "pk.<public token>" }`; optional map config |
| `GET /api/fleet/catalog` | Replay bounds, initial time, activity windows and attack-control definitions |
| `GET /api/fleet/frame?time=<seconds>&poisoning=<URL-encoded JSON>` | Current causal vessel reports and model outputs for the chosen scenario |
| `GET /api/fleet/monthly?poisoning=<JSON>&client=<tab ID>` | Shared asynchronous monthly/sequence/convergence/insight job; poll with `?job=<id>` |
| `GET /api/fleet/stress` | Independent asynchronous report-delay experiment; use `?retry=1` after a failed run |
| `GET /map-assets/mapbox-gl.js` | Mapbox GL JS 3.32.0 SDK, served by the team's host |
| `GET /map-assets/mapbox-gl.css` | Matching SDK stylesheet |

The SDK itself is not vendored. Serve its pinned distribution at the asset URLs
above, or update the two Mapbox tags in `tracking/index.html` to your approved
SDK hosting URLs. Public map configuration and network access are required for
the geographic basemap. Keep existing Mapbox/OpenStreetMap attribution. Without
a geographic map the UI can render the coordinate fallback.

### Catalog shape

`start`, `end` and `initial_time` are UTC Unix seconds. `windows` is an array of
`{ id, start, arrival }` records for timeline navigation. `attack_controls` is an
array of `{ id, label, maximum, unit, description }`. The backend supplies those
labels, bounds and explanations; the UI does not implement the attacks.

Existing control IDs: `reporting_gap` (0–60 minutes), `missing_speed`,
`missing_course`, `missing_vessel_class`, `sensor_drift`, `sensor_deterioration`,
and `position_jump` (each 0–100). The client sends their numeric settings in the
`poisoning` JSON query. Return the applied settings as `frame.poisoning`.

### Frame and vessel shape

The frame contains `{ time, ships, poisoning, poisoning_active }`.
Each vessel needs:

- `id`, `mmsi`, `name`, `arrival` (recorded crossing UTC seconds), `arrived`.
- `crossing_position`: `[longitude, latitude]` once the recorded crossing is
  reached; null before arrival. Retain terminal frames long enough for cleanup.
- `reports`: records with stable `record_id`, `time`, `delivered`, `longitude`,
  `latitude`, `speed`, `course` and `vessel_type`. Times are UTC seconds; speed is
  knots and course is degrees. Only expose reports already delivered by the
  frame clock. The client filters future timestamps too.
- `predictions`: current-scenario outputs keyed `A`, `B`, `C` (Poly, XGBoost,
  Antidote), each with `available`, `eta` and `error`. Missing outputs use null,
  never zero. Error is predicted minus actual arrival in minutes.
- `nominal_predictions`: independent clean-data outputs for the identical vessel,
  model and decision time. `poisoned_predictions`: the attacked run's outputs,
  or null if every attack is off. `prediction_time` is the shared decision clock.
  Do not populate both columns from one prediction object.

For audited feed highlighting, reports may carry `poisoned_fields`,
`attack_names`, `original_values`, `original_longitude` and `original_latitude`.
Use frontend field names (`speed`, `course`, `longitude`, `latitude`,
`vessel_type`). `audit_events` may describe already-due withheld reports with
`withheld: true`, stable IDs/times and null measurements. Audit labels must be
attached after inference; they are display evidence, not model inputs.

Antidote warnings read `age_minutes` and `diagnostics` with `state` and `reasons`.
Recognized input reasons are `implausible_position_jump`,
`conflicting_bin_positions`, `no_reports` and `reporting_gap`; stale received
reports and unavailable Antidote forecasts can also produce warnings. Simulator
poison labels alone do not trigger warnings. The map uses model C (Antidote);
the comparison table and graphs retain all three models.

Optional `comparison_inputs` explains matching forecasts after an older gap:
`normal_reports`, `poisoned_reports`, `withheld_reports`, `modified_reports`,
`history_minutes`, `normal_recent_reports`, `poisoned_recent_reports`, and
`recent_inputs_differ`. See `tracking/eta-comparison.mjs` for presentation.
Return non-2xx failures as `{ "error": "Readable message" }`.

## Monthly graph API

Six populated analysis panels sit below the existing replay. The monthly,
sequence, convergence, paired impact and stability views follow the seven sliders
with an attack boundary at March 15; the report-delay stress sweep is separate.
Serve `GET /api/fleet/monthly?poisoning=<JSON>&client=<tab ID>`, returning a 202
job snapshot (`job_id`, `status`, `phase`, `completed`, `total`) or a 200 ready
result. Poll with `GET /api/fleet/monthly?job=<job_id>`. A snapshot can also report
`error` (with readable `error`) or `superseded`.
The visible loader shows only `completed / total`; phase explanations remain
available to assistive technology. Numeric counts must reflect actual work.

The ready result has `status: "ready"`, epoch-second `start`, `end` (exclusive),
`cutover`, `poisoning_active`, `affected_reports`, `seed`, `matched_decisions`,
`scheduled_decisions`, `approaches`, `vessels`, `methodology`, `source`, `caveat`
and `days`. Each day has epoch-second `day`, `poisoned`, coverage counts and
`models.A/B/C` entries with `mean_error`, `mae`, `clean_mean_error`, `clean_mae`,
`available_decisions` and `unavailable_decisions`. Errors are minutes, using
predicted ETA minus actual crossing. Missing forecasts must remain null. Use
identical decisions for all models and clean/scenario comparisons; average
checkpoints within an approach, then weight approaches equally within a UTC day.
Preserve all pre-March-15 reports and only attack new reports after the cutover.
The ready payload also needs `sequence`: `window_minutes: 30`, `approaches`,
`vessels`, `matched_instances`, `methodology`, `coverage_note` and `samples`.
Each sample has `minute` (0–30), `scheduled_instances`, `matched_instances`,
`vessels`, and `models.A/B/C` entries with `mean_eta_shift`,
`clean_mean_eta_shift`, `mean_remaining_minutes` and
`clean_mean_remaining_minutes`. ETA shifts are minutes from each model's own
initial predicted arrival, computed within each approach before averaging.
These samples share the first graph's inference job and poisoning scenario.
The `convergence` field contains 12 final-hour five-minute bins (`minute`,
`from_minutes`, `to_minutes`, coverage and A/B/C `mae`, `clean_mae`), plus totals,
methodology and coverage notes. The separate stress endpoint returns 202 progress
(`status`, `phase`, `completed`, `total`) or a 200 ready result with five samples
at `minute` 0, 2, 5, 10, 15. Each has coverage and A/B/C `mae`,
`available_decisions`, `unavailable_decisions`. Its fixed delay experiment is
independent of the poisoning sliders; errors and source definitions are in docs.

The `insights` field supplies `impact` and `stability`. Impact contains per-model
`mae_clean`, `mae_scenario`, `added_mae` for the matched post-cutover period,
plus coverage and methodology. Stability contains seven elapsed-minute samples,
one fixed supported cohort across all models and both scenarios, and per-model
`movement`/`updates` entries with `mean`, `median`, `p10`, `p90`, `clean_mean`.
Movement is absolute change from the initial ETA; updates are absolute changes
from the prior five-minute ETA. The spread is observed vessel variability, not
a confidence interval. Preserve explicit excluded sequence counts and null means.
The source handoff includes the complete adapters and contract in integration docs.
The UI expects actual backend inference, not preselected degradation curves.

## Files

`app.mjs` coordinates the page. `arc-*` files implement the native UI controls.
`coastal.js` draws the original map. The other ES modules handle vessel motion,
arrival presentation, name-tag layout, feed history, ETA comparison, anomaly
notices, all-vessel Antidote ETAs, timeline navigation and monthly analysis.
`chart-status.mjs` shares numeric progress presentation across graphs.
`introduction.css` styles the project overview and map overlays.
`style.css` includes the arrival presentation
rules that previously lived in a separate stylesheet. These browser presentation
modules are required to preserve the current interface; they do no model training
or backend inference.

`tracking/THIRD_PARTY_NOTICES.md` records component and font sources.
`tracking/assets/GeistMono-OFL.txt` and `LICENSE` retain the relevant licenses.
