# Alfred POC

Alfred is a Qloo-powered cultural GTM agent for independent restaurants.
The POC has three layers:

- `qloo_facade.py` is a defensive facade over the eight Qloo tools used by the agent.
- `alfred_agent.py` runs the five-stage diagnosis, persona, focus group, execution, and control workflow.
- `app.py` and `static/index.html` serve the local dashboard and stream live runs over SSE.

The verified demo restaurant is Bonafini, an Italian restaurant at 663 Flatbush Ave in Prospect Lefferts Gardens, Brooklyn.
The dashboard opens with a committed sanitized snapshot and can run the full live pipeline or bootstrap a different restaurant.

## Features

- A Bonafini snapshot that is served locally with no LLM call and no network dependency.
- A single-file dashboard built with Tailwind Play CDN and Leaflet, with no Node or npm build step.
- Four views: Cultural X-Ray, Focus Group, GTM Execution Hub, and Gut vs Graph.
- A five-stage live SSE stream that updates the stepper and panels as each stage completes.
- Parallel Qloo reads with a process-wide network gate and a shared warm cache.
- Parallel Stage 4 and Stage 5 generation, so the slower result no longer blocks the faster one.
- A custom restaurant flow that resolves a name and city through Qloo search, with Nominatim as a fallback.
- Copy-ready outreach email, founder DM, SMS, Instagram caption, and AI search prompts.
- Signal Verified and `qloo_analysis_compare` badges so judges can see which claims are grounded.
- SMS character and segment counts before copy.
- A process-local lock that permits one live run at a time.

## Setup

```bash
cd alfred-poc
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:

- `QLOO_API_KEY` with the Qloo hackathon key.
- `QLOO_BASE_URL` with `https://hackathon.api.qloo.com`.
- `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL` with an OpenAI-compatible endpoint.
- `LLM_MODEL` is the offline and preset model. It stays on `anthropic/claude-sonnet-4.5` for verified snapshot runs.
- `LIVE_LLM_MODEL` is optional and applies only to the live dashboard. It defaults to `LLM_MODEL`.
- The Render blueprint uses `openai/gpt-4o-mini` for live runs to keep latency and cost low.
- `ALFRED_NOMINATIM_USER_AGENT` with a contact string for the public Nominatim fallback.

The code is provider-agnostic.
`openai/gpt-4o-mini` and `anthropic/claude-sonnet-4.5` both work through OpenRouter.

## Run The Dashboard

```bash
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1 --timeout-keep-alive 75
```

Open `http://127.0.0.1:8000`.

The server must run with one worker.
The live lock, cancellation event, HTTP cache, and network gate are process-local, so multiple Uvicorn workers would allow duplicate runs and split the cache.
`--reload` is fine for local development, but the one-worker rule still applies.

The Qloo facade keeps up to ten warm HTTP connections and allows at most four live Qloo requests in flight across the process.
Cache hits return before the network gate, so repeated reads do not consume a slot.
Optional feature probing runs once per server boot in the normal case, and transient failures are retried on the next run.

The dashboard loads the sanitized Bonafini preset immediately.
Use `Re-Run Live Qloo Agent` to stream a fresh five-stage run.
Use `Try Custom Restaurant` to enter a restaurant name, city, goal, and optional comma-separated vibe seeds.
Menu highlights are inferred from Qloo and the LLM for custom restaurants.

## Build The Preset

The committed preset is generated from a verified live run:

```bash
.venv/bin/python test_agent_bonafini.py
.venv/bin/python scripts/build_preset.py
```

`test_agent_bonafini.py` writes the full raw run to `alfred_bonafini_output.json`.
That file is gitignored and must never be committed.
`scripts/build_preset.py` strips raw IDs, signal IDs, comparison dumps, and unused diagnostics, then validates the result before writing `presets/bonafini_preset.json`.
The validator rejects UUIDs, em dashes, and bracketed placeholders.
The sanitized preset is the approved artifact for the dashboard.

The preset endpoint returns a lightweight response and uses a 60 second cache.
If the preset is rebuilt while the browser is open, hard reload the page or wait for the cache to expire.

## Live Run Contract

A live run streams these events in order:

1. `status` for stage 1, then `diagnosis`.
2. `status` for stage 2, then `persona_math`.
3. `status` for stage 3, then `focus_group`.
4. `status` for stage 4 and `status` for stage 5.
5. `execution_pack` and `gut_vs_graph` as each concurrent future finishes.
6. `done` only after both final stages finish, with elapsed seconds and the run ID.

The stepper shows Stage 4 and Stage 5 as active at the same time.
Each result is rendered as soon as it arrives, and `done` waits for both.

Custom runs also emit a stage 0 `status` while the restaurant is resolved, and may emit a `notice` when the Qloo location needs verification.
While a stage is running, the server sends `: ping` heartbeat comments so proxies do not close an idle stream.

Only one live run can execute at a time.
A second request receives an SSE `error` event with `retryable: true`.
When the browser closes the EventSource, the server requests cancellation and checks it between stages.
Concurrent final stages finish before the lock is released.
The UI does not auto-reconnect an EventSource after a stop.

## API

- `GET /` serves `static/index.html`.
- `GET /api/health` reports configuration, preset source, live lock state, `model`, and `live_model`.
- `GET /api/preset/bonafini` serves the sanitized snapshot with `X-Alfred-Preset` and a 60 second cache.
- `GET /api/stream?preset=bonafini` runs the live Bonafini pipeline.
- `GET /api/stream?name=Lilia&city=Brooklyn&goal=Fill%20Tuesdays&seeds=Roberta%27s,A24` bootstraps a custom restaurant.

The custom stream requires both `name` and `city`.
Unknown presets and incomplete custom requests return HTTP 400.
Failures after a stream starts arrive as a safe SSE `error` event rather than a traceback.

## Deployment

`render.yaml` configures a Render native Python web service, so no Docker install is required.
`Procfile` provides the same one-worker command for other process managers.
The root `requirements.txt` points at the POC requirements.

The start command binds `0.0.0.0`, uses `${PORT:-8000}` or `$PORT`, runs exactly one Uvicorn worker, and sets a 75 second keep-alive timeout for long SSE streams.
Set the Qloo and LLM secrets in the hosting dashboard.
The health check path is `/api/health`.

## Testing

Run the offline server and SSE smoke tests:

```bash
.venv/bin/python test_app_smoke.py
```

Run the Phase 4 concurrency, cache, gate, scrubber, and retry tests:

```bash
.venv/bin/python test_phase4.py
```

Run the Qloo facade verification:

```bash
.venv/bin/python test_bonafini.py
```

Run the live Bonafini end-to-end test:

```bash
.venv/bin/python test_agent_bonafini.py
```

Run a syntax check:

```bash
.venv/bin/python -m py_compile qloo_facade.py alfred_agent.py profiles.py app.py test_bonafini.py test_agent_bonafini.py test_app_smoke.py test_phase4.py scripts/build_preset.py
```

The live tests call Qloo and the configured LLM.
Run them before shipping changes that touch the facade or agent.

## Project Layout

- `app.py`: FastAPI routes, preset endpoint, SSE worker, live lock, and cancellation.
- `static/index.html`: the full dashboard, styles, renderers, and copy registry.
- `presets/bonafini_preset.json`: the committed sanitized snapshot.
- `scripts/build_preset.py`: the snapshot sanitizer and validator.
- `profiles.py`: Bonafini profile defaults and custom-profile seed defaults.
- `qloo_facade.py`: the Qloo API wrapper, shared cache, network gate, and optional feature probing.
- `alfred_agent.py`: the five-stage agent, parallel stages, bootstrap helpers, and finalization.
- `test_app_smoke.py`: offline API and SSE tests with a fake agent.
- `test_phase4.py`: offline concurrency and quality regression tests.
- `test_bonafini.py`: live facade checks.
- `test_agent_bonafini.py`: live full-pipeline checks.
- `render.yaml`, `Procfile`, and `requirements.txt`: deployment configuration at the repository root.

## Scope

The app is a single-process Uvicorn deployment with an in-memory event queue and a process-local lock.
The default snapshot is committed, but `.env` files and raw Qloo response JSON are not.
The server must run with one worker.

## License

MIT. See `LICENSE` at the repository root or `alfred-poc/LICENSE`.
