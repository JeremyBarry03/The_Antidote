# Antidote UI only

This folder contains 25 files: the approved dashboard's browser code, styles,
font/license assets, this guide and the application license. No backend, models,
datasets, tests, npm installation, lockfile, build tooling or component reference
examples are included. The full source handoff retains those development files.

Upload this entire `Frontend/` folder at the team repository root. The page is
`tracking/index.html`; keep the relative module and asset paths intact. The
existing live dashboard and previous handoffs were not modified.

## Connect your backend

Serve `tracking/` as the static web root over HTTP, with API routes on the same
origin. Opening the HTML directly as a `file://` page will not connect the API.
There is no frontend build step. Use current Chrome, Edge, Firefox or Safari.
The page will show connection feedback until a compatible API is available; it
does not include mock predictions or a standalone demo backend.

The network helper is `api()` in `tracking/app.mjs`. Frame request construction
is `frameURL()` in that file. Change those if your service uses another base URL
or authentication. The coastal-map config request is in `tracking/coastal.js`.

### Required routes

| Route | Response or asset |
| --- | --- |
| `GET /api/config` | `{ "mapbox_public_token": "pk.<public token>" }`; optional map config |
| `GET /api/fleet/catalog` | Replay bounds, initial time, activity windows and attack-control definitions |
| `GET /api/fleet/frame?time=<seconds>&poisoning=<URL-encoded JSON>` | Current causal vessel reports and model outputs for the chosen scenario |
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
`conflicting_bin_positions` and `no_reports`. Simulator poison labels alone do
not trigger warnings. Warnings appear only while model C is selected.

Optional `comparison_inputs` explains matching forecasts after an older gap:
`normal_reports`, `poisoned_reports`, `withheld_reports`, `modified_reports`,
`history_minutes`, `normal_recent_reports`, `poisoned_recent_reports`, and
`recent_inputs_differ`. See `tracking/eta-comparison.mjs` for presentation.
Return non-2xx failures as `{ "error": "Readable message" }`.

## Files

`app.mjs` coordinates the page. `arc-*` files implement the native UI controls.
`coastal.js` draws the original map. The other ES modules handle vessel motion,
arrival presentation, name-tag layout, feed history, ETA comparison, anomaly
notices and timeline navigation. `style.css` includes the arrival presentation
rules that previously lived in a separate stylesheet. These browser presentation
modules are required to preserve the current interface; they do no model training
or backend inference.

`tracking/THIRD_PARTY_NOTICES.md` records component and font sources.
`tracking/assets/GeistMono-OFL.txt` and `LICENSE` retain the relevant licenses.
