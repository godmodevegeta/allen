"""FastAPI server for the Alfred cultural CMO dashboard.

Run locally with:
    .venv/bin/uvicorn app:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from alfred_agent import AlfredAgent
from profiles import BONAFINI_FULL_PROFILE

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
INDEX_PATH = STATIC_DIR / "index.html"
PRESET_PATH = BASE_DIR / "presets" / "bonafini_preset.json"
FALLBACK_OUTPUT_PATH = BASE_DIR / "alfred_bonafini_output.json"

load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger("alfred.app")
LIVE_LOCK = threading.Lock()
_FINALIZE_STAGE = AlfredAgent.finalize_stage

app = FastAPI(
    title="Alfred",
    version="0.1.0",
    description="Qloo-powered cultural CMO for independent restaurants.",
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _llm_configured() -> bool:
    return bool(
        os.getenv("LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("OPENROUTER_API_KEY")
    )


def _live_model() -> str:
    """Resolve the dashboard model without changing offline preset runs."""
    explicit = os.getenv("LIVE_LLM_MODEL") or os.getenv("LLM_MODEL")
    if explicit:
        return explicit
    if os.getenv("OPENROUTER_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        return "openai/gpt-4o-mini"
    return "gpt-4o-mini"


def _preset_source() -> str:
    if PRESET_PATH.exists():
        return "sanitized"
    if FALLBACK_OUTPUT_PATH.exists():
        return "local-fallback"
    return "missing"


def _safe_error_message(exc: Exception) -> str:
    text = str(exc)
    lowered = text.lower()
    if "api_key" in lowered or "api key" in lowered:
        return (
            "Live agent is not configured. Add QLOO_API_KEY and LLM_API_KEY to .env, "
            "then restart the server."
        )
    if "could not resolve" in lowered:
        return text
    if "restaurant name is required" in lowered or "city or neighborhood" in lowered:
        return text
    if "no usable qloo" in lowered:
        return (
            "Qloo could not find usable signals for this restaurant. "
            "Add 2-3 well-known vibe seeds and try again."
        )
    return (
        "The live pipeline failed. Check the server logs, or load the verified "
        "Bonafini snapshot."
    )


def _parse_seeds(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    seeds = [item.strip() for item in value.split(",") if item.strip()]
    return seeds[:5] or None


def _sse(event: str, payload: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _run_pipeline(
    q: "queue.Queue[Any]",
    cancel_event: threading.Event,
    run_id: str,
    custom: bool,
    name: str,
    city: str,
    goal: str,
    seeds: Optional[List[str]],
) -> None:
    """Execute the five-stage pipeline in a worker thread and stream stage events."""
    lock_acquired = False
    stage = 0
    started = time.perf_counter()
    agent: Optional[AlfredAgent] = None

    def emit(event: str, payload: Dict[str, Any]) -> None:
        q.put((event, payload))

    def cancelled() -> bool:
        if cancel_event.is_set():
            emit(
                "cancelled",
                {
                    "message": "Client disconnected. The run will stop after the current stage.",
                    "run_id": run_id,
                },
            )
            return True
        return False

    try:
        if not LIVE_LOCK.acquire(blocking=False):
            emit(
                "error",
                {
                    "message": "Another live run is in progress. Wait for it to finish or load the verified snapshot.",
                    "stage": 0,
                    "run_id": run_id,
                    "retryable": True,
                },
            )
            return

        lock_acquired = True
        agent = AlfredAgent(model=_live_model())

        if custom:
            stage = 0
            emit(
                "status",
                {
                    "stage": 0,
                    "label": "Bootstrap",
                    "message": "Resolving the restaurant with Qloo search and OpenStreetMap.",
                    "run_id": run_id,
                },
            )
            profile = agent.bootstrap_custom_profile(
                name=name,
                city=city,
                primary_goal=goal,
                vibe_seeds_list=seeds,
            )
            if profile.get("bootstrap_warning"):
                emit(
                    "notice",
                    {
                        "level": "warning",
                        "message": profile["bootstrap_warning"],
                        "run_id": run_id,
                    },
                )
            if cancelled():
                return
        else:
            profile = copy.deepcopy(BONAFINI_FULL_PROFILE)

        stage = 1
        emit(
            "status",
            {
                "stage": 1,
                "label": "Cultural X-Ray",
                "message": "Resolving seeds, taste DNA, peers, and the local heatmap.",
                "run_id": run_id,
            },
        )
        diagnosis = agent.ingest_and_diagnose(profile)
        emit("diagnosis", diagnosis)
        if cancelled():
            return

        stage = 2
        emit(
            "status",
            {
                "stage": 2,
                "label": "Persona Math",
                "message": "Scoring partners and artists for each age slice with Qloo.",
                "run_id": run_id,
            },
        )
        persona_math = _FINALIZE_STAGE(agent.materialize_personas(diagnosis))
        emit("persona_math", persona_math)
        if cancelled():
            return

        stage = 3
        emit(
            "status",
            {
                "stage": 3,
                "label": "Synthetic Focus Group",
                "message": "Three grounded personas are debating the campaign.",
                "run_id": run_id,
            },
        )
        focus_group = _FINALIZE_STAGE(agent.run_focus_group(diagnosis, persona_math))
        emit("focus_group", focus_group)
        if cancelled():
            return

        stage = 4
        emit(
            "status",
            {
                "stage": 4,
                "label": "Execution Pack",
                "message": "Building SEO, menu, SMS, and local collaboration assets.",
                "run_id": run_id,
            },
        )
        emit(
            "status",
            {
                "stage": 5,
                "label": "Gut vs Graph",
                "message": "Generating the blind versus Qloo-grounded control in parallel.",
                "run_id": run_id,
            },
        )

        cancel_requested = False
        errors: List[tuple[int, Exception]] = []
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="alfred-final") as pool:
            futures = {
                pool.submit(agent.generate_execution_pack, diagnosis, focus_group): (
                    "execution_pack",
                    4,
                ),
                pool.submit(
                    agent.generate_gut_vs_graph_control, diagnosis, focus_group
                ): ("gut_vs_graph", 5),
            }
            for future in as_completed(futures):
                event_name, result_stage = futures[future]
                try:
                    result = _FINALIZE_STAGE(future.result())
                except Exception as exc:
                    errors.append((result_stage, exc))
                    continue
                if not cancel_requested:
                    emit(event_name, result)
                if cancelled():
                    cancel_requested = True

        if cancel_requested:
            return
        if errors:
            errors.sort(key=lambda item: item[0])
            stage = errors[0][0]
            raise errors[0][1]

        emit(
            "done",
            {
                "status": "complete",
                "elapsed_seconds": round(time.perf_counter() - started, 1),
                "run_id": run_id,
            },
        )
    except Exception as exc:  # The SSE channel must receive a safe error, not a traceback.
        logger.exception("Live run %s failed at stage %s", run_id, stage)
        emit(
            "error",
            {
                "message": _safe_error_message(exc),
                "stage": stage,
                "run_id": run_id,
                "retryable": True,
            },
        )
    finally:
        if agent is not None:
            llm = getattr(agent, "llm", None)
            if llm is not None and hasattr(llm, "close"):
                try:
                    llm.close()
                except Exception:
                    logger.debug("Could not close LLM client", exc_info=True)
            facade = getattr(agent, "facade", None)
            if facade is not None and hasattr(facade, "close"):
                try:
                    facade.close()
                except Exception:
                    logger.debug("Could not close Qloo client", exc_info=True)
        if lock_acquired:
            LIVE_LOCK.release()
        q.put(None)


@app.get("/", include_in_schema=False)
async def index() -> Any:
    if not INDEX_PATH.exists():
        return JSONResponse(
            {"error": "Dashboard not built. Add static/index.html."},
            status_code=503,
        )
    return FileResponse(INDEX_PATH, media_type="text/html")


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    source = _preset_source()
    return {
        "ok": True,
        "preset_available": source != "missing",
        "preset_source": source,
        "qloo_configured": bool(os.getenv("QLOO_API_KEY")),
        "llm_configured": _llm_configured(),
        "live_busy": LIVE_LOCK.locked(),
        "model": os.getenv("LLM_MODEL", ""),
        "live_model": _live_model(),
    }


@app.get("/health", include_in_schema=False)
async def health_alias() -> Dict[str, Any]:
    return await health()


@app.get("/api/preset/bonafini")
async def bonafini_preset() -> Any:
    source = _preset_source()
    path = PRESET_PATH if source == "sanitized" else FALLBACK_OUTPUT_PATH
    if source == "missing" or not path.exists():
        return JSONResponse(
            {
                "error": "No Bonafini preset is available. Run the live pipeline or build the preset.",
            },
            status_code=503,
        )
    headers = {
        "X-Alfred-Preset": source,
        "Cache-Control": "public, max-age=60",
    }
    return FileResponse(path, media_type="application/json", headers=headers)


@app.get("/api/stream")
async def stream_pipeline(
    request: Request,
    preset: str = Query(default="bonafini", max_length=40),
    name: Optional[str] = Query(default=None, max_length=80),
    city: Optional[str] = Query(default=None, max_length=80),
    goal: Optional[str] = Query(default=None, max_length=300),
    seeds: Optional[str] = Query(default=None, max_length=300),
) -> Any:
    clean_name = (name or "").strip()
    clean_city = (city or "").strip()
    custom = bool(clean_name or clean_city)

    if custom and not (clean_name and clean_city):
        return JSONResponse(
            {"error": "Both restaurant name and city are required."},
            status_code=400,
        )
    if not custom and preset not in ("", "bonafini"):
        return JSONResponse({"error": "Unknown preset."}, status_code=400)

    clean_goal = (goal or "").strip()
    seed_list = _parse_seeds(seeds)
    run_id = uuid.uuid4().hex[:8]
    q: "queue.Queue[Any]" = queue.Queue()
    cancel_event = threading.Event()

    worker = threading.Thread(
        target=_run_pipeline,
        args=(
            q,
            cancel_event,
            run_id,
            custom,
            clean_name,
            clean_city,
            clean_goal,
            seed_list,
        ),
        name=f"alfred-live-{run_id}",
        daemon=True,
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            yield ": connected\n\n"
            worker.start()
            while True:
                try:
                    item = await asyncio.to_thread(q.get, True, 10.0)
                except queue.Empty:
                    if await request.is_disconnected():
                        cancel_event.set()
                        break
                    yield ": ping\n\n"
                    continue

                if item is None:
                    break

                event, payload = item
                yield _sse(event, payload)
        finally:
            cancel_event.set()
            if worker.is_alive():
                logger.info(
                    "SSE client disconnected for run %s; cancellation requested.",
                    run_id,
                )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, workers=1)
