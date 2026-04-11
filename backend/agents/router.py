"""
agents/router.py — Plugin-based routing.

Discovers all plugins in agents/plugins/ and routes to the first match.
To add a new capability: add a plugin file — no changes here needed.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_backend_root = str(_Path(__file__).resolve().parents[2])
if _backend_root not in _sys.path:
    _sys.path.insert(0, _backend_root)

import re
import sys
from typing import List

from storage import apply_dictionary_corrections


def _load_snippet_triggers() -> List[str]:
    try:
        from snippets import load_snippets
        return [
            item["trigger"]
            for item in load_snippets().get("snippets", [])
            if item.get("enabled", True) and str(item.get("trigger", "")).strip()
        ]
    except Exception:
        return []


def quick_clean(text: str) -> str:
    """Remove fillers/stutters before routing — 0ms, no LLM."""
    text    = apply_dictionary_corrections(text)
    fillers = re.compile(
        r"\b(uh+|um+|er+|hmm+|ah+|oh+|like|so|basically|actually|"
        r"you know|kind of|sort of|right|okay so|well)\b[,]?\s*",
        re.IGNORECASE,
    )
    text = fillers.sub(" ", text)
    text = re.sub(r"\b(\w+)\s+\1\b", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def route(
    raw_text        : str,
    clean_text      : str,
    snippet_triggers: list,
    app_name        : str = "",
    target_language : str = "",
    user_context    : str = "",
    effective_app   : str = "",
) -> str | None:
    """Find the right plugin and run it.

    Returns:
        str  — plugin output
        None — no plugin matched, caller runs refiner
    """
    from agents.plugins import find_plugin

    from agents.plugins.knowledge import session_context
    context = {
        "raw_text":         raw_text,
        "app_name":         effective_app or app_name,
        "target_language":  target_language,
        "user_context":     user_context,
        "snippet_triggers": snippet_triggers,
        "session":          session_context(),
    }

    plugin = find_plugin(clean_text, context)
    if plugin:
        try:
            return plugin.run(clean_text, context)
        except Exception as e:
            print(f"[router] plugin {plugin.name} failed: {e}", file=sys.stderr)

    print("[router] no plugin → refine", file=sys.stderr)
    return None