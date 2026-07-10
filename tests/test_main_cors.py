"""CORS regression test.

`web` and `app` are separate Cloudflare Worker origins, so every browser-side fetch
from the Next.js app (recordings pages, image upload page) is cross-origin. Without
CORS headers the browser silently fails those fetches -- e.g. the recordings list page
falls back to its empty state ("No calls recorded yet.") even though the API itself
works fine, since curl/server-to-server calls aren't subject to CORS at all.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from app.main import app

WEB_ORIGIN = "https://sears-home-services-web.eeeew.workers.dev"


def _cors_kwargs() -> dict:
    for mw in app.user_middleware:
        if mw.cls is CORSMiddleware:
            return mw.kwargs
    raise AssertionError("CORSMiddleware is not installed on the app")


def test_cross_origin_request_gets_cors_header():
    client = TestClient(app)
    resp = client.get("/healthz", headers={"Origin": WEB_ORIGIN})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "*"


def test_preflight_allows_the_frontends_method_and_headers():
    """The browser's OPTIONS preflight for a cross-origin JSON fetch must succeed and
    advertise the method + custom headers, or the real request never fires."""
    client = TestClient(app)
    resp = client.options(
        "/api/upload/some-token",
        headers={
            "Origin": WEB_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert resp.status_code in (200, 204)
    assert resp.headers.get("access-control-allow-origin") == "*"
    allow_methods = resp.headers.get("access-control-allow-methods", "")
    assert "POST" in allow_methods or "*" in allow_methods
    # allow_headers=["*"] → the middleware echoes the requested header back.
    allow_headers = resp.headers.get("access-control-allow-headers", "").lower()
    assert "content-type" in allow_headers or "*" in allow_headers


def test_wildcard_origin_is_never_paired_with_credentials():
    """Security posture (recordings spec Decision 2 — no auth/cookies): allow_origins='*'
    is only safe because credentials are OFF. A '*'-plus-credentials combo is both
    rejected by browsers and a CSRF-shaped footgun; assert it can never ship."""
    kwargs = _cors_kwargs()
    assert kwargs["allow_origins"] == ["*"]
    # allow_credentials must be falsy (unset defaults to False in Starlette).
    assert not kwargs.get("allow_credentials", False)

    # And behaviorally: no allow-credentials:true header comes back on a CORS request.
    client = TestClient(app)
    resp = client.get("/healthz", headers={"Origin": WEB_ORIGIN})
    assert resp.headers.get("access-control-allow-credentials") != "true"


def test_cors_policy_allows_all_methods_and_headers():
    kwargs = _cors_kwargs()
    assert kwargs["allow_methods"] == ["*"]
    assert kwargs["allow_headers"] == ["*"]
