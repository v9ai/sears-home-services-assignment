"""Flag-off equivalence (requirements.md → Included; validation.md gate 3).

`LIBRARY_RAG_ENABLED` unset/off must leave the tool registry byte-equivalent to
today's agent: `search_appliance_library` absent, exact same tool set as every
other feature already registers. Turning the flag on registers exactly one more
tool and nothing else changes.
"""

from __future__ import annotations

import importlib

import pytest

from app.tools import library_tools, registry

_BASELINE_TOOLS = {
    "identify_appliance",
    "record_symptom",
    "get_troubleshooting_steps",
    "update_case_file",
    "find_technicians",
    "book_appointment",
    "send_image_upload_link",
    "check_image_analysis",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LIBRARY_RAG_ENABLED", raising=False)
    yield
    monkeypatch.delenv("LIBRARY_RAG_ENABLED", raising=False)


def _reload_library_tools() -> None:
    importlib.reload(library_tools)


def test_flag_unset_module_tools_list_is_empty() -> None:
    _reload_library_tools()
    assert library_tools.TOOLS == []


def test_flag_unset_registry_is_byte_equivalent_to_baseline() -> None:
    _reload_library_tools()
    tools = registry.get_tools()
    names = {fn.__name__ for fn in tools}
    assert names == _BASELINE_TOOLS
    assert "search_appliance_library" not in names


@pytest.mark.parametrize("falsy_value", ["", "0", "false", "False", "no", "off"])
def test_flag_falsy_values_keep_tool_unregistered(
    monkeypatch: pytest.MonkeyPatch, falsy_value: str
) -> None:
    monkeypatch.setenv("LIBRARY_RAG_ENABLED", falsy_value)
    _reload_library_tools()
    assert library_tools.TOOLS == []


@pytest.mark.parametrize("truthy_value", ["1", "true", "True", "yes", "on"])
def test_flag_truthy_values_register_the_tool(
    monkeypatch: pytest.MonkeyPatch, truthy_value: str
) -> None:
    monkeypatch.setenv("LIBRARY_RAG_ENABLED", truthy_value)
    _reload_library_tools()
    names = {fn.__name__ for fn in library_tools.TOOLS}
    assert names == {"search_appliance_library"}

    registry_names = {fn.__name__ for fn in registry.get_tools()}
    assert registry_names == _BASELINE_TOOLS | {"search_appliance_library"}


def test_importing_library_tools_with_flag_off_has_no_qdrant_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Import-time only: no Qdrant client, no embedding model touched. We assert this
    by confirming `app.knowledge.library_store` need not even be imported yet — the
    module only imports it lazily inside the tool function body — and that reloading
    the flag-off module doesn't create a `_store` singleton as a side effect."""
    from app.knowledge import library_store

    library_store.set_store(None)  # reset any singleton a prior test may have created
    _reload_library_tools()
    assert library_tools.TOOLS == []
    assert library_store._store is None
