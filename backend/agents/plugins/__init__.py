"""
agents/plugins/__init__.py — Plugin registry with fast regex routing.

Single-tier routing (0ms):
  Each plugin's can_handle() — fast regex pre-check only.
  If nothing matches → return None → caller runs the refiner.

To add a new plugin: create a file, export plugin = MyPlugin(). Done.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import List, Optional

_backend_root = str(Path(__file__).resolve().parents[2])
if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)

from agents.plugins.base import WhisprPlugin

_PLUGINS: List[WhisprPlugin] = []
_LOADED  = False


def _discover() -> List[WhisprPlugin]:
    plugins    = []
    plugin_dir = Path(__file__).parent
    for path in sorted(plugin_dir.glob("*.py")):
        if path.name.startswith("_") or path.name == "base.py":
            continue
        module_name = f"agents.plugins.{path.stem}"
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "plugin") and isinstance(mod.plugin, WhisprPlugin):
                plugins.append(mod.plugin)
                print(f"[plugins] loaded: {mod.plugin.name} (priority={mod.plugin.priority})", file=sys.stderr)
        except Exception as e:
            print(f"[plugins] failed to load {path.name}: {e}", file=sys.stderr)
    return sorted(plugins, key=lambda p: p.priority)


def get_plugins() -> List[WhisprPlugin]:
    global _PLUGINS, _LOADED
    if not _LOADED:
        _PLUGINS = _discover()
        _LOADED  = True
    return _PLUGINS


def find_plugin(text: str, context: dict) -> Optional[WhisprPlugin]:
    """Find the right plugin using fast regex can_handle() checks.

    Returns the first matching plugin sorted by priority, or None
    if nothing matches — caller then runs the refiner directly.

    No LLM call here. Runs in 0ms.
    """
    for plugin in get_plugins():
        try:
            if plugin.can_handle(text, context):
                print(f"[plugins] matched → {plugin.name}", file=sys.stderr)
                return plugin
        except Exception as e:
            print(f"[plugins] {plugin.name}.can_handle error: {e}", file=sys.stderr)

    return None  # no match → refiner handles it