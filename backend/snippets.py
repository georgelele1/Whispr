"""
Snippets module for Whispr.

Manages voice shortcuts that expand to full text.
e.g. user says "give me my calendar link" -> pastes full Calendly URL
e.g. user says "what's my schedule for tomorrow" -> fetches Google Calendar events

Storage: ~/Library/Application Support/Whispr/snippets.json
CLI:
    python snippets.py cli list
    python snippets.py cli add <trigger> <expansion>
    python snippets.py cli remove <trigger>
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

APP_NAME = "Whispr"
SNIPPETS_FILE = "snippets.json"

# Triggers that are handled dynamically (not static expansions)
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
    path = storage_path()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# =========================================================
# CRUD operations
# =========================================================

def list_all() -> Dict[str, Any]:
    """Return all snippets."""
    data = load_snippets()
    return {"ok": True, "snippets": data.get("snippets", []), "count": len(data.get("snippets", []))}


def add_snippet(trigger: str, expansion: str) -> Dict[str, Any]:
    """Add a new snippet or update an existing one."""
    trigger   = str(trigger or "").strip()
    expansion = str(expansion or "").strip()

    if not trigger:
        return {"ok": False, "error": "trigger is required"}
    if not expansion:
        return {"ok": False, "error": "expansion text is required"}

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
    filtered = [s for s in snippets if str(s.get("trigger", "")).lower() != trigger.lower()]

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
# Agent-based intent detection (single call for all triggers)
# =========================================================

def should_expand_snippets(text: str, triggers: List[str]) -> List[str]:
    """Ask the agent once which triggers, if any, are being requested."""
    agent = Agent(
        model="gpt-5",
        name="whispr_snippet_detector",
        system_prompt=(
            "You are a snippet intent detector for a voice transcription app. "
            "Given transcribed speech and a list of snippet triggers, "
            "return ONLY a JSON array of triggers the user is requesting to expand or insert. "
            "Only include a trigger if the user clearly intends to use that snippet. "
            "Return an empty array [] if none apply. "
            "No explanation, no markdown, just the raw JSON array."
        )
    )

    result = agent.input(
        f"Transcribed text: {text}\n"
        f"Available triggers: {json.dumps(triggers)}\n"
        f"Which triggers is the user requesting? Reply with JSON array only."
    )

    try:
        matched = json.loads(str(result).strip())
        return matched if isinstance(matched, list) else []
    except Exception:
        return []


# =========================================================
# Dynamic trigger handlers
# =========================================================

def handle_dynamic_trigger(trigger: str, text: str) -> str:
    """Handle triggers that require dynamic data rather than static expansion."""
    trigger_lower = trigger.lower()

    if trigger_lower == "calendar":
        try:
            from gcalendar import get_schedule, extract_calendar_intent
            intent          = extract_calendar_intent(text)
            date            = intent.get("date", "today")
            calendar_filter = intent.get("calendar", "all")
            user_id         = getpass.getuser()
            return get_schedule(date=date, user_id=user_id, calendar_filter=calendar_filter)
        except Exception as e:
            return f"Could not fetch calendar: {str(e)}"

    return text


# =========================================================
# Expansion logic
# =========================================================

def apply_snippets(text: str) -> str:
    """Expand snippet triggers in the text using agent-based intent detection.

    Makes a single agent call to detect which triggers, if any, the user
    is requesting. Dynamic triggers (like calendar) fetch live data.
    Static triggers expand to their stored text.
    """
    if not text or not text.strip():
        return text

    data = load_snippets()

    snippets = {
        item["trigger"]: item["expansion"]
        for item in data.get("snippets", [])
        if item.get("enabled", True)
        and str(item.get("trigger", "")).strip()
        and str(item.get("expansion", "")).strip()
    }

    if not snippets:
        return text

    matched_triggers = should_expand_snippets(text, list(snippets.keys()))

    result = text
    for trigger in matched_triggers:
        if trigger in snippets:
            if trigger.lower() in DYNAMIC_TRIGGERS:
                result = handle_dynamic_trigger(trigger, text)
            else:
                result = snippets[trigger]
            break

    return result


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
            result = list_all()
            print(json.dumps(result, ensure_ascii=False))

        elif command == "add":
            trigger   = sys.argv[3] if len(sys.argv) > 3 else ""
            expansion = sys.argv[4] if len(sys.argv) > 4 else ""
            result    = add_snippet(trigger, expansion)
            print(json.dumps(result, ensure_ascii=False))

        elif command == "remove":
            trigger = sys.argv[3] if len(sys.argv) > 3 else ""
            result  = remove_snippet(trigger)
            print(json.dumps(result, ensure_ascii=False))

        elif command == "toggle":
            trigger = sys.argv[3] if len(sys.argv) > 3 else ""
            enabled = sys.argv[4].lower() not in ("false", "0", "no") if len(sys.argv) > 4 else True
            result  = toggle_snippet(trigger, enabled)
            print(json.dumps(result, ensure_ascii=False))

        elif command == "expand":
            text     = sys.argv[3] if len(sys.argv) > 3 else ""
            expanded = apply_snippets(text)
            print(json.dumps({"ok": True, "original": text, "expanded": expanded}, ensure_ascii=False))

        else:
            print(json.dumps({"ok": False, "error": f"unknown command: {command}"}, ensure_ascii=False))

        sys.exit(0)

    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        print(f"ERROR: {str(e)}", file=sys.stderr)
        sys.exit(1)