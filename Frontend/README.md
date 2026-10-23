# Antidote dashboard

The dashboard at `tracking/index.html` is connected to the Python service in
`Data_Science/Optimized_Model`. There is no frontend build step or second web
server. The older single-vessel replay remains at `/eta_replay.html`.

## Run locally

From the repository root, install the pinned browser dependencies once:

```powershell
cd Frontend
npm ci
cd ../Data_Science
python -m pip install -r requirements-dev.txt
python -m Optimized_Model serve --port 8765
```

Open <http://127.0.0.1:8765>. The service redirects to `/tracking/`, serves all
browser assets and the pinned Mapbox SDK, and exposes the fleet API on the same
origin. The default config is `Optimized_Model/config_vessel_class_v2.json`;
its prepared replay dataset and frozen A/B/C models must already exist. A clone
does not include these ignored artifacts or source CSVs. Follow
`../Data_Science/Optimized_Model/README.md` to acquire data and prepare/train them.
The service rejects incompatible artifacts; it does not train models on startup.

For the coastal basemap, set `MAPBOX_PUBLIC_TOKEN=pk.<public token>` in the
repository root `.env` (or your environment). Only public `pk.` tokens are
exposed. The coordinate fallback works without a token.

## Connected behavior

The fleet catalog uses the protected evaluation approaches when available,
otherwise the exploratory partition. Each frame runs Poly (A), ordinary XGBoost
(B), and Antidote (C) on reports delivered by the selected UTC clock. Clean and
attacked forecasts are computed independently at that same clock; attacks off
leaves the poisoned column empty. Errors refer to the original analytical harbor
crossing, not docking. Vessels are labeled by source MMSI because the prepared
histories do not contain vessel names.

All eight controls call the existing report attacks, including location drift.
The speed-drift slider uses under-reporting. Over-reporting remains available
through the backend experiment API.
Reporting gaps start ten
minutes after each approach begins and last for the selected duration; they do
not move with the replay clock. Noise/drift strength and position-jump settings
are described by each control's explanation. Attacks are seeded and compose in
the order gap, speed drift, location drift, deterioration, position jump, then missing fields. Original
records, frozen artifacts and reference crossings stay unchanged. Display audit
labels are attached after inference; withheld events contain no measurements.

C uses its trained input guard plus the existing strategies through
`Optimized_Model/fleet_mitigations.py`. Mitigations are built into Antidote;
the dashboard always enables them without a separate repair switch. Missing speed/course
can be reconstructed independently from checked original position history;
class recovery uses consistent received MMSI metadata. Gaussian noise and speed
drift use their existing conditional sensor reconstruction. Gap and navigation
consistency detectors provide warnings; the position-jump detector never repairs
coordinates. The per-vessel Antidote status lists applied estimates and review
requirements. Underlined feed cells expose derived estimates in their tooltip;
displayed measurements remain the actual received values. A/B, raw quality
features, source files, clocks and trained models stay unchanged.

Selected position faults pause position-based sensor/missing-navigation repairs.
Noise plus speed drift pauses their overlapping sensor corrections. These are
explicit experiment reference policies, not automatic fault classification.
Detectors continue to inspect the unmodified received stream. Metadata recovery
is independent of navigation and may still operate. Compatible repairs can run
together, but combined-attack accuracy has not been established or calibrated.

Location drift warns by default. The dashboard does not add simulated reference
fixes. The backend's explicit `trusted_fixes=true` experiment adds original-position
reference fixes from the first report in each five-minute bin.
Each fix becomes available only at its measurement/delivery clock; the
existing five-minute projection expiry and navigation checks still apply.
This is an oracle-reference simulation, not a deployed independent data source.
It is available only with location drift, mitigations on, and no speed, course,
noise, speed-drift or position-jump attack. Original crossing outcomes never
become repair inputs. No previous calibration is transferred to these repairs.

## Checks

```powershell
# From Frontend
npm run check
npm test
# From Data_Science
python -m pytest tests -q
```

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

The Python service serves the SDK from `Frontend/node_modules/mapbox-gl/dist`
after `npm ci`. Public map configuration and network access are required for
the geographic basemap. Keep existing Mapbox/OpenStreetMap attribution. Without
a geographic map the UI can render the coordinate fallback.

### Catalog shape

`start`, `end` and `initial_time` are UTC Unix seconds. `windows` is an array of
`{ id, start, arrival }` records for timeline navigation. `attack_controls` is an
array of `{ id, label, maximum, unit, description }`. The backend supplies those
labels, bounds and explanations; the UI does not implement the attacks.

Existing control IDs: `reporting_gap` (0–60 minutes), `missing_speed`,
`missing_course`, `missing_vessel_class`, `sensor_drift`, `location_drift`, `sensor_deterioration`,
and `position_jump` (each 0–100). The client sends their numeric settings in the
`poisoning` JSON query. Return the applied settings as `frame.poisoning`.

For backend experiment controls the same frame route accepts
`mitigate=true|false` (default true; the dashboard always sends true),
`trusted_fixes=true|false` (default false; always false in the dashboard), and `drift_direction=under|over`
(default under). Invalid flags or unsupported trusted-fix combinations return
400. The catalog includes `mitigation_defaults`; `frame.mitigations` echoes the
selected options. Each ship includes `mitigation` with `enabled`, `strategies`,
`features_changed`, `estimated_values`, `reference_simulated`, and an explicit
uncalibrated ETA policy. Strategy results contain status, detection, applied
count, review requirement and the original strategy diagnostics. Display reports
optionally contain `estimated_values`; these never overwrite received fields.

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
`conflicting_bin_positions`, `no_reports` and `reporting_gap`. Simulator poison labels alone do
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
