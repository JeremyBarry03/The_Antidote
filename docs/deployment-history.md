# Historical deployment preparation notes

> Superseded by the root README on October 28, 2026. These notes preserve the original deployment preparation record, including statements that were true only at that time. They do not describe current hosting or verification status. Do not apply the paid Render Blueprint as part of retiring the deployment.

The static dashboard in `Frontend/tracking` calls a FastAPI service in
`Data_Science/server.py`. The HTTP adapter reuses `FleetService`, the existing
attacks and mitigations, and the hash-verified frozen A/B/C serving bundle.
It never trains models or downloads source datasets during startup.

Deployment has **not** been performed. Review the changes and validation report
below before committing/pushing or creating hosting resources.

## Run locally

Use Python 3.11. From `Data_Science`:

```sh
python -m pip install -r requirements-dev.txt
python -m uvicorn server:app --host 0.0.0.0 --port 8765 --workers 1
```

`GET http://localhost:8765/health` returns 200 only after all three frozen models
and the replay bundle have loaded. Missing/corrupt artifacts produce 503 and a
readable API error; the detailed cause appears in server logs. `/api/config`
exposes only a `pk.` public Mapbox token, never a secret token.

For the complete local site, use Netlify Dev with the API rewrite pointing to
an HTTPS backend, or a local HTTP reverse proxy that serves `Frontend/tracking`
at `/` and forwards `/api/*` to port 8765. The old research CLI server remains
available unchanged, but it does not implement the new chart endpoints.
Opening `index.html` as a local file does not connect an API.

## Render backend

1. Review and push the deployment changes to `JeremyBarry03/2026_WM_Hackathon`
   on `main` when ready. No commit/push is performed by this preparation task.
2. In Render, connect GitHub and create a Blueprint from the repository's root
   `render.yaml`. Alternatively create a Python Web Service with root directory
   `Data_Science`, branch `main`, build command
   `pip install -r requirements.txt`, start command
   `uvicorn server:app --host 0.0.0.0 --port $PORT --workers 1`, and health path
   `/health`.
3. The Blueprint selects Python 3.11.14, one instance and the paid `1c-2g`
   compute plan (1 CPU, 2 GB). Review the plan/cost before applying it.
   This is a starting configuration, not a measured capacity guarantee.
4. Supply a public Mapbox token when prompted, or leave it empty for the
   coordinate fallback. Restrict the token's allowed URLs to your frontend.
5. Apply the Blueprint. After `/health` returns 200, copy the service's HTTPS
   origin for Netlify's `RENDER_BACKEND_URL`.

Automatic Render deploys follow commits to `main`. Validate the Blueprint with
`render blueprints validate render.yaml` when the CLI/account connection is
available. Local validation against Render's live JSON schema passed; platform
validation and a Linux/Render startup have not been performed.

## Netlify frontend

1. Import the same GitHub repository. Choose production branch `main`.
2. The root `netlify.toml` supplies base `Frontend`, publish directory `tracking`,
   and an empty build command. There is no frontend compilation step.
3. Set **`RENDER_BACKEND_URL`** in Netlify environment variables with **Builds**
   scope, for every deploy context you enable. Use the real HTTPS origin copied
   from Render, without an API path, query, credentials or fragment.
4. Deploy after the backend is healthy. A local Netlify Build Plugin reads that
   environment variable in `onPreBuild`, prepends a forced 200 proxy rewrite from
   `/api/*` to the backend's `/api/:splat`, and copies the existing overview page
   and downloads into the publish directory. It fails the deploy if the backend
   origin is missing/invalid. This hook runs even though the build command is
   empty. A plain drag-and-drop upload does not run the hook.
5. Open the site root: `tracking/index.html` is the homepage. `/tracking/*`
   aliases retain existing replay/font links. `/overview/` and its downloads
   retain the current interface's navigation.

The browser continues to use relative `/api` requests. No fake backend hostname
is committed. Netlify does not interpolate environment variables in redirect
URLs, which is why the local plugin sets the rewrite. Changing the backend URL
requires a fresh Netlify deploy. The Mapbox SDK and CSS use the pinned official
3.32.0 CDN; map attribution and fallback behavior remain unchanged.

## Configuration and artifacts

| Variable | Service | Meaning |
| --- | --- | --- |
| `ANTIDOTE_CONFIG` | Render | Config path, relative to `Data_Science` or absolute; defaults to `Optimized_Model/config_data_eval.json` |
| `PYTHON_VERSION` | Render | Blueprint pins `3.11.14`; local `.python-version` selects 3.11 |
| `PORT` | Render | Supplied by Render; bind on `0.0.0.0` |
| `MAPBOX_PUBLIC_TOKEN` | Render | Optional public `pk.` token returned by `/api/config` |
| `CORS_ORIGINS` | Render | Optional comma-separated exact origins for direct browser-to-API development; wildcard rejected; empty for Netlify same-origin proxy |
| `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` | Render | Blueprint sets 1 to limit native-thread contention |
| `RENDER_BACKEND_URL` | Netlify Builds | Required actual Render HTTPS origin, read by the local plugin |

The repository already tracks the portable bundle at
`Data_Science/artifacts/data_eval/optimized`: `serving_bundle.json`,
`serving_replay.joblib`, two `frozen_baselines/*/model.joblib` files and
`models/C_nominal.joblib`. A is Poly, B is ordinary XGBoost and served C is the
existing nominal Antidote artifact plus its current conditional mitigations.
The manifest verifies artifact hashes, inference source hashes and scientific
settings. All three models are loaded once per process. Only load trusted
joblib artifacts: deserialization can execute Python code.

This deployment uses the original bundled March 2024 evaluation observations
with the frozen 2023-trained models. It does not require the large original
training/calibration CSVs. The bundle contains the terminal crossing positions.
For an authorized alternate bundle, provision its complete files before startup,
use a config whose paths resolve to that bundle and its baseline config, and set
`ANTIDOTE_CONFIG`. Do not bypass hashes or retrain to make deployment pass.
Supplying raw CSVs alone does not satisfy this production adapter. Keep private
datasets, credentials, `.env` and `.netlify` state out of Git.

## Analysis behavior and operating limits

`/api/fleet/monthly` creates or reuses a scenario job, returns 202 promptly,
and accepts `?job=<job_id>` for polling. Ready/error snapshots return 200 with
their status. Retrying the same failed scenario starts a new job. `/api/fleet/stress`
uses its own job; `?retry=1` retries a failed stress job. Unknown/evicted IDs return
400 with a readable error. A full queue returns 429. Invalid frame settings return
400; missing serving artifacts return 503. All API responses disable caching.

The new read-only chart adapter computes actual frozen-model forecasts, not
preselected curves. Daily and convergence errors match decisions across A/B/C
and both input arms, then weight approaches equally. Sliders apply only to reports
on/after March 15 in these chart jobs; earlier values and deliveries stay clean.
Playback retains its existing per-approach attack behavior. Sequence plots start
at each approach's first scheduled decision. Stability uses one supported cohort
at all seven five-minute offsets. Stress adds a fixed 0/2/5/10/15-minute delivery
delay and matches checkpoints across every model/delay. Missing forecasts remain
null. Counts and methodology are included in each result. Simulated interventions
are labeled **Simulated disruption** and never represented as source-data facts.
These dashboard reductions do not modify or replace existing research results.

One background analysis worker serializes jobs and shares an inference lock with
playback. The queue/result cache holds at most eight jobs; jobs are deduplicated
by scenario, and completed results can be evicted. `client` is accepted for the
frontend contract; changing sliders queues another scenario rather than cancelling
another viewer's job. Run **one Uvicorn worker and one Render instance**: queues
and results are in memory and disappear on restart/deploy. For multiple instances
or durable jobs, add a shared job store/worker before scaling. No database or
persistent disk is provisioned for this single-instance setup.

Full-month analysis is computationally expensive: this bundle has 243 approaches,
5,382 scheduled decisions, plus up to 7,533 sequence checkpoints per monthly job.
Jobs may take many minutes and contend with playback; full-month runtime and
production memory/latency have not been benchmarked. Eight cached scenarios are
not eight simultaneous inference workers. Netlify's proxy request timeout does
not cover an entire analysis because each request only starts/polls it. Avoid a
sleeping backend for reliable playback and polling. This is a single-instance
research deployment, not a proven high-traffic production capacity claim.

Review [Render compute plans](https://render.com/docs/compute-plans) and
[pricing](https://render.com/pricing), and [Netlify pricing](https://www.netlify.com/pricing/)
before creating resources. Expect paid backend compute and applicable Netlify and
Mapbox usage charges. No hosting resources or billable deployments were created.

## Verification and deployment smoke checks

From `Data_Science`:

```sh
python -m pytest tests -q
```

From `Frontend`:

```sh
npm run check
npm test
node --test netlify/backend-proxy/proxy.smoke.mjs
```

Local validation on Windows/Python 3.11.9:

- Existing Python suite: **612 passed**.
- New production API suite: **5 passed**, using the actual shipped models and
  replay. Covers all eight attacks, causal delivery, independent clean forecasts,
  unavailable bundle handling, input validation, retryable failed jobs, and the
  six-chart payloads through completed asynchronous jobs on a reduced two-approach
  cohort. A full 243-approach chart job has **not** been run to completion.
- TypeScript check passed. Netlify proxy/static overview packaging: **2 passed**.
- Uvicorn started with the production host/worker settings and an allocated port;
  `/health` returned 200 after about 9 seconds, catalog returned 243 approaches,
  a poisoned playback frame returned A/B/C outputs, and monthly job creation
  returned a job ID. The process was stopped after the smoke check.
- The static homepage and 27 referenced local assets/modules returned HTTP 200.
  A real bundled replay with maximum position jump produced a `review` diagnostic.
- Existing frontend suite: **14 passed, 8 failed**. The same eight failures occur
  with the original HTML restored: five catalog/date-picker assertions, two
  mitigation/feed-update assertions, and the startup assertion expecting an
  explicit `mitigate=true` query parameter. They remain unresolved; no frontend
  JavaScript behavior was changed for this deployment task.
- Live Render JSON schema accepted the Blueprint. Both pinned Mapbox SDK URLs
  returned HTTP 200. Render CLI/account validation is unavailable because the
  plugin reported that Render is not connected and the CLI is not installed.

After deploying, verify both the Render origin and the Netlify origin:

```sh
curl --fail https://YOUR_RENDER_ORIGIN/health
curl --fail https://YOUR_NETLIFY_ORIGIN/api/config
curl --fail https://YOUR_NETLIFY_ORIGIN/api/fleet/catalog
```

Copy `initial_time` from the catalog into
`/api/fleet/frame?time=<initial_time>&poisoning=%7B%22missing_speed%22%3A100%7D`.
Check available A/B/C outputs, unchanged `nominal_predictions` when changing
controls, and report timestamps/deliveries no later than the frame clock. Start
`/api/fleet/monthly?poisoning=%7B%7D`, poll the returned job ID until ready, and
check all six graphs in the browser; poll `/api/fleet/stress` independently.
Check coordinate fallback without a token and the geographic map with an allowed
public token. Hosted end-to-end behavior, authenticated Netlify build execution,
Linux startup and real Mapbox rendering remain manual deployment checks.
