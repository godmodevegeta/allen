# Agent Instructions

## Project

allen - qloo agent

The working POC lives in `alfred-poc/`.
It contains a defensive Qloo facade, a five-stage Alfred agent, and a FastAPI dashboard.

## Commands

- Install: `cd alfred-poc && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- Serve: `cd alfred-poc && .venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1`
- Smoke test: `cd alfred-poc && .venv/bin/python test_app_smoke.py`
- Facade test: `cd alfred-poc && .venv/bin/python test_bonafini.py`
- Live E2E: `cd alfred-poc && .venv/bin/python test_agent_bonafini.py`
- Build preset: `cd alfred-poc && .venv/bin/python scripts/build_preset.py`
- Lint / typecheck: `cd alfred-poc && .venv/bin/python -m py_compile qloo_facade.py alfred_agent.py profiles.py app.py test_bonafini.py test_agent_bonafini.py test_app_smoke.py scripts/build_preset.py`

The live server must use one Uvicorn worker.
The lock and cancellation state are process-local.

## Code Style

- Keep the facade dependency-light: `httpx`, `python-dotenv`, and `openai` only.
- Use type hints and small plain functions.
- Never commit `.env` files or generated Qloo response JSON.

## Workflow

- Run the live Bonafini E2E tests before shipping changes.
- Rebuild `presets/bonafini_preset.json` after a live run that changes the artifact shape.
- Optional Qloo features must degrade gracefully instead of crashing.
- Keep generated and UI copy free of em dashes and bracketed placeholders.
