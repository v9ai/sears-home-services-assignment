"""FastAPI application entrypoint.

The foundation ships only the health probe. Feature agents mount their own routers
(``/ws/call``, ``/twilio/voice``, upload routes, …) from their owned packages.
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.phone import phone_router
from app.recordings.routes import router as recordings_router
from app.uploads.routes import router as upload_router
from app.ws.routes import router as ws_router

app = FastAPI(title="Sears Home Services Voice Agent")


@app.on_event("startup")
async def _prewarm_tts_cache() -> None:
    """O1: warm the constant-string TTS cache in the background at boot."""
    import asyncio

    from app.agent.tts_cache import prewarm

    asyncio.get_running_loop().create_task(prewarm())


# `web` and `app` are separate Cloudflare Worker origins (different subdomains), so
# every browser-side fetch from web/app/recordings/*.tsx and web/app/upload/[token]
# is cross-origin. No auth/cookies on this API (recordings spec Decision 2 — explicit
# no-auth, single-tenant demo posture), so a permissive allow-origins is safe and
# simplest; allow_credentials stays False (required by spec when origins is "*").
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ws_router)
app.include_router(upload_router)
app.include_router(phone_router)

# O10 (latency-engineering): in-container latency probes, flag-gated read-only.
if os.environ.get("LATENCY_PROBE_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
    from app.latency_probe import router as latency_probe_router

    app.include_router(latency_probe_router)
app.include_router(recordings_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
