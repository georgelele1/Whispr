"""
Snippets module for Whispr.

Voice shortcuts that expand to full text or live data.
  "give me my zoom link"       → pastes static URL
  "check my schedule tomorrow" → calls get_calendar tool → fetches events

Static snippets are listed in the agent system prompt.
Dynamic snippets (calendar) are registered as agent tools.

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
import sys
from pathlib import Path
from typing import Any, Dict, List

# Shared helpers from app
from app import app_support_dir, register_tool

# Swallow [env] line connectonion prints on import
import io as _io
import sys as _sys
_real_stdout = _sys.stdout
_sys.stdout  = _io.StringIO()
try:
    from connectonion import Agent
finally:
    _sys.stdout = _real_stdout

SNIPPETS_FILE    = "snippets.json"
DYNAMIC_TRIGGERS = {"calendar"}


# =========================================================
# Storage
# =========================================================

def _storage_path() -> Path:
    return app_support_dir() / SNIPPETS_FILE


def load_snippets() -> Dict[str, Any]:
    path = _storage_path()
    if not path.exists():
        return {"snippets": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"snippets": []}


def _save_snippets(data: Dict[str, Any]) -> None:
    _storage_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# =========================================================
# CRUD
# =========================================================

def list_all() -> Dict[str, Any]:
    data = load_snippets()
    return {"ok": True, "snippets": data.get("snippets", []), "count": len(data.get("snippets", []))}


def add_snippet(trigger: str, expansion: str) -> Dict[str, Any]:
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
            _save_snippets(data)
            return {"ok": True, "updated": True, "snippet": item}

    entry = {"trigger": trigger, "expansion": expansion, "enabled": True}
    snippets.append(entry)
    data["snippets"] = snippets
    _save_snippets(data)
    return {"ok": True, "updated": False, "snippet": entry}


def remove_snippet(trigger: str) -> Dict[str, Any]:
    trigger = str(trigger or "").strip()
    if not trigger:
        return {"ok": False, "error": "trigger is required"}

    data     = load_snippets()
    snippets = data.get("snippets", [])
    filtered = [s for s in snippets if str(s.get("trigger", "")).lower() != trigger.lower()]

    if len(filtered) == len(snippets):
        return {"ok": False, "error": f"snippet not found: {trigger}"}

    data["snippets"] = filtered
    _save_snippets(data)
    return {"ok": True, "removed": trigger, "remaining": len(filtered)}


def toggle_snippet(trigger: str, enabled: bool = True) -> Dict[str, Any]:
    trigger = str(trigger or "").strip()
    if not trigger:
        return {"ok": False, "error": "trigger is required"}

    data = load_snippets()
    for item in data.get("snippets", []):
        if str(item.get("trigger", "")).lower() == trigger.lower():
            item["enabled"] = bool(enabled)
            _save_snippets(data)
            return {"ok": True, "trigger": trigger, "enabled": item["enabled"]}

    return {"ok": False, "error": f"snippet not found: {trigger}"}


# =========================================================
# Calendar tool (registered as agent tool — not called directly)
# =========================================================

def get_calendar(date: str = "today", calendar_filter: str = "all") -> str:
    """Fetch Google Calendar events for a given date.

    Args:
        date:            'today', 'tomorrow', or YYYY-MM-DD.
        calendar_filter: calendar name to filter by, or 'all'.
    """
    try:
        from gcalendar import get_schedule
        return get_schedule(date=date, user_id=getpass.getuser(), calendar_filter=calendar_filter)
    except Exception as e:
        return f"Could not fetch calendar: {e}"


# =========================================================
# Snippet expansion agent
# =========================================================

def _build_agent(static_snippets: Dict[str, str]) -> Agent:
    """Build agent with static snippets baked into the prompt and
    the calendar tool registered for dynamic expansion."""
    static_map   = {t: e for t, e in static_snippets.items() if t.lower() not in DYNAMIC_TRIGGERS}
    has_calendar = "calendar" in static_snippets

    static_lines = "\n".join(
        f'  TRIGGER="{t}" → RETURN EXACTLY: {e}'
        for t, e in static_map.items()
    )

    prompt = "You are Whispr's snippet expansion agent.\n"

    if static_lines:
        prompt += (
            "STATIC SNIPPETS — return expansion text directly, NO tool calls:\n"
            f"{static_lines}\n\n"
        )

    if has_calendar:
        prompt += (
            "DYNAMIC — calendar:\n"
            "  If user asks for schedule/events/calendar: call get_calendar(date, calendar_filter).\n"
            "  ONLY call get_calendar for calendar requests. NEVER for other triggers.\n\n"
        )

    prompt += (
        "RULES:\n"
        "1. Static match → return expansion text only. No tools.\n"
        "2. Calendar request → call get_calendar once.\n"
        "3. No match → return original text unchanged.\n"
        "4. No explanation or extra text."
    )

    agent = Agent(model="gpt-5", name="whispr_snippet_agent", system_prompt=prompt)
    if has_calendar:
        register_tool(agent, get_calendar)
    return agent


def apply_snippets(text: str) -> str:
    """Detect and expand snippet triggers using agent + registered tools."""
    if not text or not text.strip():
        return text

    snippets = {
        item["trigger"]: item["expansion"]
        for item in load_snippets().get("snippets", [])
        if item.get("enabled", True)
        and str(item.get("trigger",   "")).strip()
        and str(item.get("expansion", "")).strip()
    }

    if not snippets:
        return text

    result = str(_build_agent(snippets).input(text)).strip().strip('"').strip("'").strip()
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
            enabled = sys.argv[4].lower() not in ("false", "0", "no") if len(sys.argv) > 4 else True
            print(json.dumps(toggle_snippet(trigger, enabled), ensure_ascii=False))

        elif command == "expand":
            text = sys.argv[3] if len(sys.argv) > 3 else ""
            print(json.dumps(
                {"ok": True, "original": text, "expanded": apply_snippets(text)},
                ensure_ascii=False,
            ))

        else:
            print(json.dumps({"ok": False, "error": f"unknown command: {command}"}, ensure_ascii=False))
            sys.exit(1)

        sys.exit(0)

    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)