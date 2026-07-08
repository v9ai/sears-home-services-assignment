"""Tool auto-discovery.

Adding a tool = adding a file (COORDINATION.md §1): each feature drops an
``app/tools/<feature>_tools.py`` exposing a module-level ``TOOLS: list``. This module
imports every sibling and concatenates their ``TOOLS`` — no shared registry is edited.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any

import app.tools as _tools_pkg

_EXCLUDED = {"registry"}


def get_tools() -> list[Any]:
    """Discover and return every tool exported by ``app/tools/*.py``."""
    discovered: list[Any] = []
    for module_info in pkgutil.iter_modules(_tools_pkg.__path__):
        name = module_info.name
        if name in _EXCLUDED:
            continue
        module = importlib.import_module(f"{_tools_pkg.__name__}.{name}")
        module_tools = getattr(module, "TOOLS", None)
        if module_tools:
            discovered.extend(module_tools)
    return discovered


TOOLS: list[Any] = get_tools()
