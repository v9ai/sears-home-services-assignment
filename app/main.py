"""FastAPI application entrypoint.

The foundation ships only the health probe. Feature agents mount their own routers
(``/ws/call``, ``/twilio/voice``, upload routes, …) from their owned packages.
"""

from fastapi import FastAPI

app = FastAPI(title="Sears Home Services Voice Agent")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
