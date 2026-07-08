"""CORS regression test.

`web` and `app` are separate Cloudflare Worker origins, so every browser-side fetch
from the Next.js app (recordings pages, image upload page) is cross-origin. Without
CORS headers the browser silently fails those fetches -- e.g. the recordings list page
falls back to its empty state ("No calls recorded yet.") even though the API itself
works fine, since curl/server-to-server calls aren't subject to CORS at all.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_cross_origin_request_gets_cors_header():
    client = TestClient(app)
    resp = client.get(
        "/healthz", headers={"Origin": "https://sears-home-services-web.eeeew.workers.dev"}
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "*"
