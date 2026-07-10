"""FastAPI application entrypoint.

The foundation ships only the health probe. Feature agents mount their own routers
(``/ws/call``, ``/twilio/voice``, upload routes, …) from their owned packages.
"""

import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app.phone import phone_router
from app.recordings.routes import router as recordings_router
from app.uploads.routes import page_router as upload_page_router
from app.uploads.routes import router as upload_router
from app.ws.routes import router as ws_router

# Root logging config: without this, module loggers (app.phone, app.agent.*, ...)
# either have no handler at all (Python's "handler of last resort" only prints
# WARNING+) or print with no timestamp/module -- exactly the gap that made prior
# "application error has occurred" incidents undiagnosable from `wrangler tail`.
# LOG_LEVEL is env-controlled so DEBUG-volume per-frame logs stay opt-in.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").strip().upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("app.main")

app = FastAPI(title="Sears Home Services Voice Agent")


@app.exception_handler(Exception)
async def _log_uncaught_exception(request: Request, exc: Exception) -> PlainTextResponse:
    """Last-resort net for HTTP routes: whatever reaches here is what a caller/browser
    sees as a bare 500 (Twilio hears this as "an application error has occurred" on the
    voice webhook) -- log every bit of request context before returning, so the
    incident is diagnosable from logs alone instead of from a spoken error message."""
    logger.exception(
        "unhandled_exception method=%s path=%s query=%s client=%s",
        request.method,
        request.url.path,
        str(request.url.query),
        request.client,
    )
    return PlainTextResponse("internal server error", status_code=500)


@app.on_event("startup")
async def _log_startup() -> None:
    logger.info(
        "app_startup log_level=%s recording_enabled=%s latency_probe=%s",
        os.environ.get("LOG_LEVEL", "INFO"),
        os.environ.get("TWILIO_CALL_RECORDING_ENABLED", "1"),
        os.environ.get("LATENCY_PROBE_ENABLED", ""),
    )


@app.on_event("startup")
async def _register_instrumentation() -> None:
    """2026-07-09-observability-tracing: llama-index dispatcher -> structured logs."""
    from app.agent.instrumentation import register_instrumentation

    register_instrumentation()


@app.on_event("startup")
async def _prewarm_tts_cache() -> None:
    """O1: warm the constant-string TTS cache in the background at boot."""
    import asyncio

    from app.agent.tts_cache import prewarm

    asyncio.get_running_loop().create_task(prewarm())


# The backend serves its own upload page (same-origin), but a permissive
# allow-origins stays for ad-hoc tooling/debug clients. No auth/cookies on this API
# (recordings spec Decision 2 — explicit no-auth, single-tenant demo posture), so
# "*" is safe; allow_credentials stays False (required by spec when origins is "*").
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws_router)
app.include_router(upload_router)
app.include_router(upload_page_router)
app.include_router(phone_router)

# O10 (latency-engineering): in-container latency probes, flag-gated read-only.
if os.environ.get("LATENCY_PROBE_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
    from app.latency_probe import router as latency_probe_router

    app.include_router(latency_probe_router)
app.include_router(recordings_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
