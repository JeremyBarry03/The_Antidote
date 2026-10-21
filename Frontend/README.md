# AIS reliability replay

The existing vanilla JavaScript page uses focused ES modules with strict JSDoc
contracts checked by TypeScript. It needs no frontend build or Node runtime to
serve. Python continues to own scenario generation, feature extraction, and ETA
inference. No models are trained or changed by this UI.

## Start

From `Data_Science`, with the existing trained artifacts present:

```powershell
python -m Optimized_Model serve --port 8765
```

Open `http://127.0.0.1:8765`. Opening the HTML as a file cannot call the replay API.
The local service exposes only the HTML and the replay JavaScript/CSS assets.

## Fleet product view

The home page is a month-wide fleet replay. The current bundle includes 242
supported March 2024 cargo/tanker approaches from 218 vessels. It opens at the
earliest real window with three concurrent approaches (March 2, 07:45 UTC),
selected by traffic density rather than model success. It does not invent or
reschedule vessels to keep the map busy. Quiet archive periods remain quiet;
use the month scrubber or **Next traffic** to move through them.

**60×** means one simulated minute per real second. Playing all 31 days takes
12.4 hours; 600× and 3,600× are available for a shorter demonstration. Select
Regression, XGBoost, or The Antidote to change every ship's displayed forecast.
Click a ship or its feed row for individual reports. The fullscreen button
expands the product console and its controls. A vessel and its complete
delivered track fade for eight simulated minutes after the recorded crossing.

The delivery-delay slider accepts 0–60 minutes. The position slider affects
0–100% of messages, with an offset of 0.1–2 nautical miles at fixed message
count. Fault selection is deterministic for the fixed seed. The API runs the
real fitted A/B/C predictors on the shared delivered feed at the chosen clock;
it does not interpolate errors between saved presets. Red data fields and
original-coordinate tooltips are simulator audit annotations added after
inference. C's alert uses observable age and consistency, not those labels.

The input-guard switch changes C's served feature summary. Degraded-example
training and quality features remain part of the frozen C bundle. Guard-off
is an exploratory serving ablation, not a retrained model or a calibrated
operational policy. Consolidated/removed messages are not proven detected faults.

Graphs begin with actual model calls over the preceding 30 minutes at five-minute
steps, then add live minute frames. The plotted window retains at most 120
sample frames. MAE, RMSE, and MSE use equal approach weighting over common
supported pre-crossing forecasts; unavailable forecasts stay in the separately
shown current coverage. Changing fault/guard settings or scrubbing resets the
window. Historical errors use the original crossing labels only for scoring.
They would not be available prospectively to an operator.

March includes training, development, and previously inspected exploratory data.
These dynamic scores are explicitly not protected evaluation. The saved April
evaluation is separately disclosed below the charts and remains fixed. Actual
date partitions are displayed; the demo does not assume an 80/10/10 split.

Vessel movement is interpolated along already delivered reports at animation-frame
frequency; trail uploads are bounded to 10 Hz. Movement can trail the latest
message while completing a segment. It never extrapolates future positions or
changes the feed, forecasts, or metrics. Pause freezes the movement cursor;
seeking and changing faults snap to the requested snapshot. Reduced motion uses
report-by-report positioning. The former single-vessel comparison is retired.

### Fleet API

- `GET /api/fleet/catalog`: March boundaries, traffic windows, cohort, seed, gate,
  and the actual data partitions.
- `GET /api/fleet/frame?time=<UTC epoch seconds>&delay=15&fraction=0.25&offset=0.5&guard=true`:
  causal delivered reports, fitted forecasts, retrospective scores and
  post-inference audit fields for the active approaches.
- `GET /api/fleet/history` with the same parameters: measured comparison samples
  at or before the requested clock. No future frames are returned.

The service validates finite control values and March boundaries, and bounds
its in-memory frame/stream caches. No original source, model, saved evaluation,
or review log is written by fleet playback.

The vessel-class v2 repository change added two fields while the current
artifact bundle retained the legacy fitted schema. Loading now recognizes only
the two exact reviewed source revisions of that schema migration for legacy
feature lists. Config/model hashes and all other implementation hashes remain
strict. No bundle metadata was rewritten and no model was retrained. Spot checks
against the original implementation preserved exact feature/forecast values
across 36 model/scenario/partition combinations.

## Optional Mapbox basemap

The coordinate plot works without an account, token, or map-network connection.
The server automatically reads `.env` from the repository root (beside
`CODE_GUIDELINES.md`), regardless of the current working folder. Set a public
token there using the template in `.env.example`:

```dotenv
MAPBOX_TOKEN=<your public token>
```

The local `.env` is ignored by Git and is not served as a browser asset. Restart
the server after editing it. `MAPBOX_PUBLIC_TOKEN` is also supported; explicit
process environment variables override `.env` values. The existing start command
needs no token assignment. `python-dotenv` is pinned in the Python requirements.

Use your account's public token with URL restrictions covering the actual local
origin. Never supply a secret `sk.` token. The optional SDK and CSS are pinned to
Mapbox GL JS **3.32.0**, matching the development typing dependency. Network or
authorization failures retain the coordinate plot. Mapbox account usage terms
and map-load billing apply: https://docs.mapbox.com/mapbox-gl-js/guides/pricing/.
The renderer draws delivered tracks and the analytical crossing reference.
It does not call a Directions API or generate a predicted vessel route.

## Development checks

From `Frontend` (Node 22.22 or compatible):

```powershell
npm ci
npm run check
npm test
```

Vitest exercises UI behavior under jsdom, including hidden outcomes, request
races, verification/reveal preservation, and map truth-layer separation. The
fleet checks cover common-case scoring, approach weighting and MAE/MSE/RMSE.
Motion checks cover interpolation, shortest-angle turns, pause continuity,
seeking, removal, and the absence of future extrapolation. The targeted Python
checks also cover fleet delivery cutoffs, future-frame
exclusion, fade/removal, and refusal of unreviewed inference migrations. The
existing Python suite covers causal delivery, model inputs, inspection, counts,
and saved timeline boundaries: `python -m pytest tests -q` from `Data_Science`.

The API module owns network calls; `types.d.ts` documents additive backend
contracts. Mapbox uses the same GeoJSON builder as the coordinate plot. No
frontend ML feature calculation duplicates the Python pipeline.
