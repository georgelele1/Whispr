"""
Snippets module for Whispr.

Voice shortcuts that expand to full text or live data.
  "give me my zoom link"          → pastes static URL
  "what's my schedule tomorrow"   → calls get_calendar tool → fetches events

Static snippets are listed in the agent system prompt.
Dynamic snippets are registered as tools the agent can call.

Storage: ~/Library/Application Support/Whispr/snippets.json
CLI:
    python snippets.py cli list
    python snippets.py cli add <trigger> <expansion>
    python snippets.py cli remove <trigger>
    python snippets.py cli toggle <trigger> <true|false>
    python snippets.py cli expand <text>
"""

from __future__ import annotations

import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from connectonion import Agent
from app import register_tool

APP_NAME      = "Whispr"
SNIPPETS_FILE = "snippets.json"

# Triggers handled via agent tools (not static text expansion)
DYNAMIC_TRIGGERS = {"calendar"}


# =========================================================
# Paths / storage
# =========================================================

def app_support_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(home))) / APP_NAME
    else:
        base = home / ".local" / "share" / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def storage_path() -> Path:
    return app_support_dir() / SNIPPETS_FILE


def load_snippets() -> Dict[str, Any]:
    path = storage_path()
    if not path.exists():
        return {"snippets": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"snippets": []}


def save_snippets(data: Dict[str, Any]) -> None:
    storage_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# =========================================================
# CRUD
# =========================================================

def list_all() -> Dict[str, Any]:
    """Return all snippets."""
    data = load_snippets()
    return {
        "ok":       True,
        "snippets": data.get("snippets", []),
        "count":    len(data.get("snippets", [])),
    }


def add_snippet(trigger: str, expansion: str) -> Dict[str, Any]:
    """Add a new snippet or update an existing one."""
    trigger   = str(trigger   or "").strip()
    expansion = str(expansion or "").strip()
    if not trigger:   return {"ok": False, "error": "trigger is required"}
    if not expansion: return {"ok": False, "error": "expansion text is required"}

    data     = load_snippets()
    snippets = data.get("snippets", [])

    for item in snippets:
        if str(item.get("trigger", "")).lower() == trigger.lower():
            item["expansion"] = expansion
            item["enabled"]   = True
            save_snippets(data)
            return {"ok": True, "updated": True, "snippet": item}

    entry = {"trigger": trigger, "expansion": expansion, "enabled": True}
    snippets.append(entry)
    data["snippets"] = snippets
    save_snippets(data)
    return {"ok": True, "updated": False, "snippet": entry}


def remove_snippet(trigger: str) -> Dict[str, Any]:
    """Remove a snippet by trigger."""
    trigger = str(trigger or "").strip()
    if not trigger:
        return {"ok": False, "error": "trigger is required"}

    data     = load_snippets()
    snippets = data.get("snippets", [])
    filtered = [
        s for s in snippets
        if str(s.get("trigger", "")).lower() != trigger.lower()
    ]

    if len(filtered) == len(snippets):
        return {"ok": False, "error": f"snippet not found: {trigger}"}

    data["snippets"] = filtered
    save_snippets(data)
    return {"ok": True, "removed": trigger, "remaining": len(filtered)}


def toggle_snippet(trigger: str, enabled: bool = True) -> Dict[str, Any]:
    """Enable or disable a snippet."""
    trigger = str(trigger or "").strip()
    if not trigger:
        return {"ok": False, "error": "trigger is required"}

    data = load_snippets()
    for item in data.get("snippets", []):
        if str(item.get("trigger", "")).lower() == trigger.lower():
            item["enabled"] = bool(enabled)
            save_snippets(data)
            return {"ok": True, "trigger": trigger, "enabled": item["enabled"]}

    return {"ok": False, "error": f"snippet not found: {trigger}"}


# =========================================================
# Dynamic tools
# =========================================================

def get_calendar(date: str = "today", calendar_filter: str = "all") -> str:
    """Fetch Google Calendar events for a given date.

    Args:
        date: 'today', 'tomorrow', or a YYYY-MM-DD string.
        calendar_filter: calendar name to filter by, or 'all' for all calendars.

    Returns:
        Formatted schedule string.
    """
    try:
        from gcalendar import get_schedule
        return get_schedule(
            date=date,
            user_id=getpass.getuser(),
            calendar_filter=calendar_filter,
        )
    except Exception as e:
        return f"Could not fetch calendar: {e}"


# =========================================================
# Snippet expansion agent
# =========================================================

def build_snippet_agent(static_snippets: Dict[str, str]) -> Agent:
    """Build the snippet agent with static snippets in the prompt
    and dynamic tools registered.

    Static snippets are passed directly in the system prompt so the
    agent can return them without a tool call — zero extra latency.
    Dynamic triggers (calendar etc.) are registered as tools so the
    agent can call them with the right arguments extracted from the text,
    replacing the old extract_calendar_intent round-trip.
    """
    static_lines = "\n".join(
        f'  "{t}" → "{e}"'
        for t, e in static_snippets.items()
        if t.lower() not in DYNAMIC_TRIGGERS
    )

    dynamic_lines = "\n".join(
        f'  "{t}" → call the {t} tool'
        for t in DYNAMIC_TRIGGERS
        if t in static_snippets
    )

    agent = Agent(
        model="gpt-5",
        name="whispr_snippet_agent",
        system_prompt=(
            "You are Whispr's snippet expansion agent.\n"
            "Given transcribed speech, decide if the user is requesting a snippet.\n\n"
            + (f"Static snippets — return the expansion text directly:\n{static_lines}\n\n" if static_lines else "")
            + (f"Dynamic snippets — use the registered tool:\n{dynamic_lines}\n\n" if dynamic_lines else "")
            + "Rules:\n"
            "- If a snippet is requested, return ONLY the expanded text.\n"
            "- For dynamic snippets, call the appropriate tool with the correct "
            "  arguments extracted from the user's text (e.g. date, calendar name).\n"
            "- If NO snippet is requested, return the original text UNCHANGED.\n"
            "- Never add explanation, preamble, or extra text."
        ),
    )

    # Register get_calendar as a tool so the agent can call it directly
    # with date and calendar_filter extracted from the transcribed text.
    # This replaces the old two-step: detect intent → hardcoded if/else handler.
    if "calendar" in static_snippets:
        register_tool(agent, get_calendar)

    return agent


def apply_snippets(text: str) -> str:
    """Expand snippet triggers using an agent with registered tools.

    The agent handles both detection and expansion in one call:
    - Static snippets: returned directly from system prompt knowledge
    - Dynamic snippets (calendar): agent calls the tool with correct args
    - No match: original text returned unchanged
    """
    if not text or not text.strip():
        return text

    data     = load_snippets()
    snippets = {
        item["trigger"]: item["expansion"]
        for item in data.get("snippets", [])
        if item.get("enabled", True)
        and str(item.get("trigger",   "")).strip()
        and str(item.get("expansion", "")).strip()
    }

    if not snippets:
        return text

    agent  = build_snippet_agent(snippets)
    result = str(agent.input(text)).strip().strip('"').strip("'").strip()

    # Safety check: if result is empty fall back to original text
    return result if result else text


# =========================================================
# CLI
# =========================================================

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] != "cli":
        print("usage: python snippets.py cli <command> [args...]")
        print("commands: list, add, remove, toggle, expand")
        sys.exit(1)

    command = sys.argv[2] if len(sys.argv) > 2 else "list"

    try:
        if command == "list":
            print(json.dumps(list_all(), ensure_ascii=False))

        elif command == "add":
            trigger   = sys.argv[3] if len(sys.argv) > 3 else ""
            expansion = sys.argv[4] if len(sys.argv) > 4 else ""
            print(json.dumps(add_snippet(trigger, expansion), ensure_ascii=False))

        elif command == "remove":
            trigger = sys.argv[3] if len(sys.argv) > 3 else ""
            print(json.dumps(remove_snippet(trigger), ensure_ascii=False))

        elif command == "toggle":
            trigger = sys.argv[3] if len(sys.argv) > 3 else ""
            enabled = (
                sys.argv[4].lower() not in ("false", "0", "no")
                if len(sys.argv) > 4 else True
            )
            print(json.dumps(toggle_snippet(trigger, enabled), ensure_ascii=False))

        elif command == "expand":
            text     = sys.argv[3] if len(sys.argv) > 3 else ""
            expanded = apply_snippets(text)
            print(json.dumps(
                {"ok": True, "original": text, "expanded": expanded},
                ensure_ascii=False,
            ))

        else:
            print(json.dumps(
                {"ok": False, "error": f"unknown command: {command}"},
                ensure_ascii=False,
            ))

        sys.exit(0)

    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        print(f"ERROR: {str(e)}", file=sys.stderr)
        sys.exit(1)