"""FastAPI application entrypoint.

The foundation ships only the health probe. Feature agents mount their own routers
(``/ws/call``, ``/twilio/voice``, upload routes, …) from their owned packages.
"""

from fastapi import FastAPI

from app.ws.routes import router as ws_router

app = FastAPI(title="Sears Home Services Voice Agent")

app.include_router(ws_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
