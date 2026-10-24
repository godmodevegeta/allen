# Alfred Backend - Implementation Plan

Source idea: `/Users/shubhamkumar/Developer/Slops/allen/THE_IDEA.md`
Target module: `allen-backend/` (already scaffolded with uv, Python 3.13)
Purpose: JSON API powering Alfred's agentic loop for the Qloo Agentic Hackathon (deadline Oct 30, 2026).

## Decisions locked

- LLM: provider-agnostic via a thin adapter over **LiteLLM**, model chosen by env (`LLM_MODEL`, e.g. `anthropic/claude-sonnet-4-5`, `openai/gpt-5`, `gemini/...`).
- Persistence: **SQLite** via SQLModel (server-side caching of Qloo responses allowed; never commit Qloo data to the public repo).
- Deploy: **Render** (Docker), with a persistent disk for the SQLite file.

## Architecture

```
Frontend (separate module)
        |
        v
FastAPI app (CORS)
  routers: businesses | dna | ask | artifacts | alerts | health
        |
  services: orchestrator (fan-out, merge, rank) | artifacts | alerts
        |
  agent: LiteLLM tool-calling loop + tools -> services (not raw HTTP from the model)
        |
  qloo: httpx client (search, tags, insights, compare, trending, audiences) + cache
        |
  SQLite (SQLModel): businesses, seeds, dna_snapshots, artifacts, alerts, cache, agent_runs
```

## Module layout

```
allen-backend/
  app/
    main.py            # FastAPI app, CORS, router wiring
    config.py          # pydantic-settings: QLOO_API_URL, QLOO_API_KEY, LLM_MODEL, provider keys, CORS origins, DB path
    db.py              # engine, session dependency, create_all
    models.py          # SQLModel tables (see schema below)
    schemas.py         # API request/response models
    qloo/
      client.py        # async httpx client; X-Api-Key header; GET with dotted params; retry/backoff
      types.py         # supported entity types, per-type param allowlist, URN helpers
      cache.py         # SQLite-backed response cache keyed by endpoint+params hash
    taste_dna/
      seeds.py         # onboarding payload -> candidate seeds (LLM extraction + deterministic rules)
      resolver.py      # seeds -> Qloo IDs via /search and /v2/tags
      builder.py       # seed set -> affinity profile per entity type -> DnaSnapshot
      gaps.py          # target audiences/tags -> affinity deltas (Analysis Compare)
    agent/
      loop.py          # tool-calling loop, max steps, trace capture
      tools.py         # qloo_search, qloo_tags, qloo_insights, qloo_compare, qloo_trending, get_taste_dna
      llm.py           # LiteLLM adapter (complete + tool calls)
      prompts.py       # system prompts; receipts + no-hallucination rules
    artifacts/
      brief.py         # positioning brief
      dossier.py       # partnership dossier (multi-filter.type fan-out, merged)
      calendar.py      # seasonal cultural calendar
    alerts/
      runner.py        # proactive cycle: trending + affinity diff vs last snapshot
    services/
      orchestrator.py  # per-filter.type fan-out, merge, rank by affinity; receipts assembly
    routers/
      businesses.py | dna.py | ask.py | artifacts.py | alerts.py | health.py
  tests/
  scripts/
    e2e_smoke.py       # runs onboarding -> DNA -> ask -> one artifact against real API (local only)
  Dockerfile
  render.yaml
```

## API surface (frontend contract)

- `POST /businesses` - onboarding: name, location (city/neighborhood), vertical (cuisine), menu/offerings, vibe descriptors, playlist/music, competitors, goals. Returns business id.
- `GET /businesses/{id}`
- `POST /businesses/{id}/dna` - build Taste DNA (synchronous first; move to background + poll if latency > ~30s). Returns snapshot.
- `GET /businesses/{id}/dna/latest` - current DNA with affinity receipts.
- `POST /businesses/{id}/ask` - `{question}` -> `{answer_markdown, receipts[], trace[]}`. Reactive mode.
- `POST /businesses/{id}/artifacts/{kind}` - kind in `brief | dossier | calendar`. Returns artifact with embedded receipts; `trace` included.
- `GET /businesses/{id}/artifacts`
- `POST /businesses/{id}/alerts/run` - runs one proactive cycle, returns new alerts.
- `GET /businesses/{id}/alerts`
- `GET /health` - process up; `GET /health/qloo` - live 1-entity insights probe.

Receipt shape (reused everywhere): `{entity_id, name, entity_type, affinity, popularity, source: "qloo", params_hash}`.

## Data flow

1. Onboarding: business record stored; LLM + rules extract seed candidates from menu (dishes -> cuisine tags), vibe, playlist, décor, competitors.
2. DNA build: resolve each seed via `/v2/tags` (tags) and `/search` (entities); compose the composite signal (business `place`/`brand` entity + seeds); run `/v2/insights` per entity type of interest (`artist`, `brand`, `movie`, `place`, ...) with `filter.location.query` set to the neighborhood/city; store DnaSnapshot = top affinities per type + gaps vs target audiences.
3. Ask/artifacts: agent loop calls tools; orchestrator fans out one insights call per `filter.type` for cross-category work (brands, person/creators, places) and merges by affinity.
4. Alerts: rerun key affinity queries + Trending Data for DNA-relevant entities; diff vs last snapshot; emit alert artifacts with receipts.

## Qloo integration rules (non-negotiable)

- Base URL from env, hackathon value `https://hackathon.api.qloo.com`; `X-Api-Key` header only.
- `/v2/insights` is GET with dotted query params; `filter.type` required; only the ten supported entity types (`artist`, `book`, `brand`, `destination`, `movie`, `person`, `place`, `podcast`, `tv_show`, `video_game`).
- Validate every tag via `/v2/tags` and every audience URN via audience lookup before use; invalid params are silently ignored and yield empty results.
- Percent-encode `filter.location.query` and dot-params carefully; centralize param building in `qloo/types.py`.
- Never call `/recs` or `/recommendations`.
- All outputs framed as aggregate affinities; no PII ever sent; response cache is private (SQLite) and never exported to the public repo; tests use synthetic fixtures only.

## Agent design

- Tools call backend services (typed, validated), not raw HTTP.
- Loop: max ~12 steps; capture tool trace for the demo UI.
- Hallucination guard: any entity mentioned in an answer must appear in tool outputs of that run; enforce in a post-check step.
- Prompt rules: every recommendation carries a receipt; never imply individual-level knowledge; artifacts use fixed markdown skeletons so output is consistent.

## Persistence schema (SQLite)

- `Business`: profile fields + created_at.
- `Seed`: business_id, kind (entity|tag), raw_text, qloo_id, qloo_type, source (menu|vibe|music|...) , confidence.
- `DnaSnapshot`: business_id, created_at, location used, profile JSON (top affinities per type w/ scores), gaps JSON.
- `Artifact`: business_id, kind, markdown, receipts JSON, trace JSON, created_at.
- `Alert`: business_id, kind, message, receipts JSON, delta JSON, created_at, seen.
- `QlooCacheEntry`: params_hash, endpoint, response JSON, created_at (no TTL required, but add `max_age` for alerts freshness).
- `AgentRun`: business_id, question, steps JSON, answer, created_at.

## Testing

- Unit: param builders, cache keying, seed parsing, receipt assembly - pytest.
- Integration: `respx`-mocked httpx for qloo client; LiteLLM adapter mocked at the boundary.
- Fixtures: synthetic only (no real Qloo payloads committed).
- `scripts/e2e_smoke.py`: real-API smoke run before demo day; run manually, never in CI.

## Deployment (Render)

- Dockerfile: `python:3.13-slim`, uv sync, uvicorn `app.main:app`, `PORT` from env.
- `render.yaml` blueprint: web service + persistent disk mounted at `/var/data` (SQLite path env `DB_PATH=/var/data/alfred.db`).
- Env vars on Render: `QLOO_API_URL`, `QLOO_API_KEY`, `LLM_MODEL`, provider API key(s), `CORS_ORIGINS`.
- Health check path: `/health`.

## Milestones (order of work)

1. M1 - scaffold: config, db, qloo client + cache, `/health`, `/health/qloo`.
2. M2 - onboarding + DNA: seeds, resolver, builder, snapshots.
3. M3 - agent loop: LiteLLM adapter, tools, receipts, trace, `/ask`.
4. M4 - artifacts: brief, dossier (fan-out), calendar.
5. M5 - proactive alerts: trending + diff cycle.
6. M6 - tests, Dockerfile, render.yaml, deploy, e2e smoke.

## Risks / open items

- Seed extraction quality is the "thin wrapper" risk; M2 gets the most polish.
- LiteLLM tool-calling behavior varies by provider; adapter tests must cover 2+ providers before demo.
- Render persistent disk requires a paid instance - confirm plan tier.
- Qloo coverage may be thin for the chosen demo venue; pick a dense city/neighborhood and use tag/location fallbacks.
- Synchronous DNA build may exceed request timeouts on Render; fallback is background task + polling endpoint.
