from __future__ import annotations

from app.agent import fillers
from app.ws import routes as ws_routes


def test_cached_strings_non_empty_and_distinct():
    assert len(fillers.CACHED_STRINGS) == 4
    assert all(s.strip() for s in fillers.CACHED_STRINGS)
    assert len(set(fillers.CACHED_STRINGS)) == len(fillers.CACHED_STRINGS)


def test_web_module_imports_shared_constants():
    assert ws_routes.TOOL_CALL_FILLER is fillers.WEB_TOOL_FILLER
    assert ws_routes.TURN_FAILED_FALLBACK is fillers.WEB_TURN_FAILED_FALLBACK


def test_filler_debounce_default():
    assert fillers.FILLER_DEBOUNCE_S == 0.25
