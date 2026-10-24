# Agent Instructions

## Project

allen - qloo agent

The working POC lives in `alfred-poc/`.
It contains a defensive Qloo facade, a five-stage Alfred agent, and a FastAPI dashboard.

## Commands

- Install: `cd alfred-poc && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- Serve: `cd alfred-poc && .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1 --timeout-keep-alive 75`
- Smoke test: `cd alfred-poc && .venv/bin/python test_app_smoke.py`
- Phase 4 tests: `cd alfred-poc && .venv/bin/python test_phase4.py`
- Facade test: `cd alfred-poc && .venv/bin/python test_bonafini.py`
- Live E2E: `cd alfred-poc && .venv/bin/python test_agent_bonafini.py`
- Build preset: `cd alfred-poc && .venv/bin/python scripts/build_preset.py`
- Lint / typecheck: `cd alfred-poc && .venv/bin/python -m py_compile qloo_facade.py alfred_agent.py profiles.py app.py test_bonafini.py test_agent_bonafini.py test_app_smoke.py test_phase4.py scripts/build_preset.py`

The live server must use one Uvicorn worker.
The lock, cancellation state, shared cache, and Qloo network gate are process-local.

## Concurrency

- Cache hits return before the network gate.
- At most four live Qloo HTTP requests may be in flight across the process.
- Cache and capability state are shared by every `QlooFacade` in one process.
- Stage 1, persona scoring, and the final Stage 4 and Stage 5 calls run in parallel where they are independent.
- Preserve deterministic ordering after every fan-out.
- Stage 4 and Stage 5 results stream as each future completes, and `done` waits for both.

## Models

- `LLM_MODEL` is the offline and preset model.
- `LIVE_LLM_MODEL` is optional and applies only to the dashboard. It defaults to `LLM_MODEL`.
- Offline preset generation stays on `anthropic/claude-sonnet-4.5`.
- The Render blueprint uses `openai/gpt-4o-mini` for live runs.

## Code Style

- Keep the facade dependency-light: `httpx`, `python-dotenv`, and `openai` only.
- Use type hints and small plain functions.
- Never commit `.env` files or generated Qloo response JSON.
- Never use em dashes in generated or UI copy.

## Workflow

- Run the offline smoke and Phase 4 tests before shipping changes.
- Run the live Bonafini E2E tests before shipping changes that touch Qloo or the LLM.
- Rebuild `presets/bonafini_preset.json` after a live run that changes the artifact shape.
- Optional Qloo features must degrade gracefully instead of crashing.
- Keep generated and UI copy free of em dashes and bracketed placeholders.
- Grounded receipt fields and intentional generic contrast fields must survive the cliche scrubber unchanged.

## Deployment

- `render.yaml` uses Render's native Python runtime. No Docker install is required.
- `Procfile` is the fallback process command for other hosts.
- Bind `0.0.0.0`, use `${PORT:-8000}` or `$PORT`, run one Uvicorn worker, and keep a 75 second keep-alive timeout for SSE.
- Set Qloo and LLM secrets in the hosting dashboard, never in the repository.
