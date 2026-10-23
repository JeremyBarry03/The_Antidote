<<<<<<< Updated upstream
# AIS reliability replay

The existing vanilla JavaScript page uses focused ES modules with strict JSDoc
contracts checked by TypeScript. It needs no frontend build or Node runtime to
serve. Python continues to own scenario generation, feature extraction, and ETA
inference. No models are trained or changed by this UI.

## Start
=======
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

All seven controls call the existing report attacks. Reporting gaps start ten
minutes after each approach begins and last for the selected duration; they do
not move with the replay clock. Noise/drift strength and position-jump settings
are described by each control's explanation. Attacks are seeded and compose in
the order gap, drift, deterioration, position jump, then missing fields. Original
records, frozen artifacts and reference crossings stay unchanged. Display audit
labels are attached after inference; withheld events contain no measurements.

C uses its trained input guard. Experimental missing-speed, course and class
repairs are still opt-in through the existing single-attack API endpoints;
the dashboard does not silently combine unevaluated repair policies. Reporting
gap warnings use the existing observable cadence detector and clear when reports
resume. This integration does not claim new calibration or robustness results.

## Checks

```powershell
# From Frontend
npm run check
npm test
# From Data_Science
python -m pytest tests -q
```
>>>>>>> Stashed changes

From `Data_Science`, with the existing trained artifacts present:

```powershell
python -m Optimized_Model serve --port 8765
```

Open `http://127.0.0.1:8765`. Opening the HTML as a file cannot call the replay API.
The local service exposes only the HTML and the replay JavaScript/CSS assets.

## Optional Mapbox basemap

The coordinate plot works without an account, token, or map-network connection.
The server automatically reads `.env` from the repository root (beside
`CODE_GUIDELINES.md`), regardless of the current working folder. Set a public
token there using the template in `.env.example`:

<<<<<<< Updated upstream
```dotenv
MAPBOX_TOKEN=<your public token>
```
=======
The Python service serves the SDK from `Frontend/node_modules/mapbox-gl/dist`
after `npm ci`. Public map configuration and network access are required for
the geographic basemap. Keep existing Mapbox/OpenStreetMap attribution. Without
a geographic map the UI can render the coordinate fallback.
>>>>>>> Stashed changes

The local `.env` is ignored by Git and is not served as a browser asset. Restart
the server after editing it. `MAPBOX_PUBLIC_TOKEN` is also supported; explicit
process environment variables override `.env` values. The existing start command
needs no token assignment. `python-dotenv` is pinned in the Python requirements.

You can still enter a token in **Map settings** and choose **Use Mapbox** for a
temporary page-only override. That field is cleared after submission, and its
value is not saved to browser storage or the `.env` file.

Use your account's public token with URL restrictions covering the actual local
origin. Never supply a secret `sk.` token. The optional SDK and CSS are pinned to
Mapbox GL JS **3.32.0**, matching the development typing dependency. Network or
authorization failures retain the coordinate plot. Mapbox account usage terms
and map-load billing apply: https://docs.mapbox.com/mapbox-gl-js/guides/pricing/.
The renderer draws received reports and the analytical crossing reference; it
does not call a Directions API or generate a predicted vessel route. The
inspector can additionally draw original positions of already delivered reports.

## Demo walkthrough

1. Start with **Normal reports**. Approaches are listed chronologically. The page
   initially selects decision index 20 or the approach midpoint, whichever comes
   first, without selecting a vessel by model success. Play restarts at the
   beginning when it reaches the last decision.
2. Choose **Incorrect positions** and enable **Show simulated changes**. Inspect
   a red point or use the record selector to see its original/delivered position,
   event/delivery times, and injected displacement. Known fault labels are
   audience-only and do not enter any predictor.
3. Expand the additional experiments. Compare 10%, 25%, and 50% prevalence at
   fixed volume, then exact or slightly different repeated messages. The
   counts cover the model's evidence window before shared deduplication; the
   map and selector show at most 150 recent reports. Copies are not independent
   trajectories. Guard consolidation is not a count of detected faults.
4. Compare normal, delayed, incorrect-position, and combined conditions at the
   same clock. A 15-minute delay continues delivering old reports; it is not a
   permanent freeze. ETA shifts compare against the normal-input replay of the
   same model and decision. All A/B/C condition forecasts use the same feed.
5. Play or scrub, then reveal the recorded analytical crossing and errors.
   Changing decision, approach, or scenario hides the outcome again. The chart
   reads saved unattended evaluation forecasts using the same first configured
   evaluation seed as live snapshots, and returns only past/current decisions.
6. Use the full-cohort MAE/coverage tables, reserved drift condition, and explicit
   failure buttons. Small repetition effects and the failed acceptance policy
   remain visible. A selected failure is labeled as a failure example.

**Simulate verified update** supplies a historical report already measured at
the decision time and records walkthrough duration in `human_verification.jsonl`.
It is explicitly human assisted. Revealing truth preserves the verified
forecasts; it does not replace them with unattended forecasts or rewrite the
saved timeline. Time/condition changes reset the intervention. The inspector is
fixed while the verified result is displayed.

Arrival remains the original east-to-west analytical crossing at longitude
−76.30, latitude 36.95–37.05, rather than verified docking. Delays and input
corruptions are simulations. This is not evidence of poisoning in NOAA records
or a validated deployment safety policy. C still fails on some approaches.

## Development checks

From `Frontend` (Node 22.22 or compatible):

```powershell
npm ci
npm run check
npm test
```

Vitest exercises UI behavior under jsdom, including hidden outcomes, request
races, verification/reveal preservation, and map truth-layer separation. The
existing Python suite covers causal delivery, model inputs, inspection, counts,
and saved timeline boundaries: `python -m pytest tests -q` from `Data_Science`.

The API module owns network calls; `types.d.ts` documents additive backend
contracts. Mapbox uses the same GeoJSON builder as the coordinate plot. No
frontend ML feature calculation duplicates the Python pipeline.
