"""FastAPI HTTP-surface drift guards.

The app is assembled from feature-owned routers (`app.main.include_router(...)`), so a
refactor in any one feature can silently drop a route the frontend or Twilio depends on.
These tests pin the public HTTP surface (via the OpenAPI schema — the stable, public
view), confirm each owned router is actually mounted, and exercise the health probe and
the last-resort exception handler. Fully hermetic: no DB, no network, no container.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import WebSocketRoute

import app.main as app_main
from app.main import app
from app.phone import phone_router
from app.recordings.routes import router as recordings_router
from app.uploads.routes import router as upload_router
from app.voice.routes import router as voice_router
from app.ws.routes import router as ws_router

# The HTTP surface the frontend (recordings/upload pages) and Twilio (voice webhook)
# depend on. A drift here means a browser fetch or a Twilio webhook 404s in production.
EXPECTED_HTTP_ROUTES = {
    ("GET", "/healthz"),
    ("GET", "/api/recordings"),
    ("GET", "/api/recordings/{recording_id}"),
    ("GET", "/api/recordings/{recording_id}/audio/{seq}"),
    ("GET", "/api/recordings/{recording_id}/call-audio"),
    ("GET", "/api/recordings/{recording_id}/twilio-audio/{twilio_recording_sid}"),
    ("GET", "/api/upload/{token}"),
    ("POST", "/api/upload/{token}"),
    ("POST", "/twilio/voice"),
}


def _openapi_routes() -> set[tuple[str, str]]:
    schema = app.openapi()
    return {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method in operations
    }


def test_openapi_route_inventory_has_no_drift():
    actual = _openapi_routes()
    missing = EXPECTED_HTTP_ROUTES - actual
    assert not missing, f"expected routes went missing from the app: {sorted(missing)}"


def test_no_unexpected_public_api_routes_appeared():
    """New /api or /twilio surface should be a deliberate change to EXPECTED_HTTP_ROUTES,
    not an accident — catch additions too, ignoring the framework's own /docs, /openapi."""
    actual = _openapi_routes()
    surfaced = {
        (m, p) for (m, p) in actual if p.startswith(("/api/", "/twilio/")) or p == "/healthz"
    }
    unexpected = surfaced - EXPECTED_HTTP_ROUTES
    assert not unexpected, f"new public routes not in the pinned inventory: {sorted(unexpected)}"


def test_owned_feature_routers_are_mounted_on_the_app():
    """Each feature's router object is actually included in the assembled app — guards
    against an include_router(...) line being dropped during a refactor."""
    # original_router values are APIRouter instances (unhashable) — compare by identity.
    mounted = [getattr(r, "original_router", None) for r in app.routes]
    for router in (ws_router, phone_router, recordings_router, upload_router):
        assert any(m is router for m in mounted), f"router not mounted: {router!r}"


def _ws_paths(router) -> set[str]:
    paths: set[str] = set()
    for route in router.routes:
        if isinstance(route, WebSocketRoute):
            paths.add(route.path)
        for inner in getattr(route, "routes", None) or []:
            if isinstance(inner, WebSocketRoute):
                paths.add(inner.path)
    return paths


def test_websocket_endpoints_are_declared():
    # The two live-audio transports: the web bridge and the Twilio Media Streams adapter.
    assert "/ws/call" in _ws_paths(ws_router)
    assert "/ws/twilio" in _ws_paths(voice_router)


def test_healthz_returns_ok():
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_unhandled_exception_returns_plaintext_500():
    """The last-resort handler must turn any uncaught error into a logged, plain-text 500
    (never a bare stack trace or a spoken 'application error' with no log trail)."""
    probe_app = FastAPI()
    probe_app.add_exception_handler(Exception, app_main._log_uncaught_exception)

    @probe_app.get("/boom")
    async def _boom() -> dict[str, str]:
        raise RuntimeError("kaboom")

    client = TestClient(probe_app, raise_server_exceptions=False)
    resp = client.get("/boom")
    assert resp.status_code == 500
    assert resp.text == "internal server error"
    assert resp.headers["content-type"].startswith("text/plain")
