"""
Snippets module for Whispr.

Manages voice shortcuts that expand to full text.
e.g. user says "my schedule link" -> pastes full Calendly URL

Storage: ~/Library/Application Support/Whispr/snippets.json
CLI:
    python snippets.py cli list
    python snippets.py cli add <trigger> <expansion>
    python snippets.py cli remove <trigger>
    python snippets.py cli expand <text>
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

APP_NAME = "Whispr"
SNIPPETS_FILE = "snippets.json"


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
    trigger = str(trigger or "").strip()
    expansion = str(expansion or "").strip()

    if not trigger:
        return {"ok": False, "error": "trigger is required"}
    if not expansion:
        return {"ok": False, "error": "expansion text is required"}

    data = load_snippets()
    snippets = data.get("snippets", [])

    # check if trigger already exists - update it
    for item in snippets:
        if str(item.get("trigger", "")).lower() == trigger.lower():
            item["expansion"] = expansion
            item["enabled"] = True
            save_snippets(data)
            return {"ok": True, "updated": True, "snippet": item}

    # new entry
    entry = {
        "trigger": trigger,
        "expansion": expansion,
        "enabled": True,
    }
    snippets.append(entry)
    data["snippets"] = snippets
    save_snippets(data)
    return {"ok": True, "updated": False, "snippet": entry}


def remove_snippet(trigger: str) -> Dict[str, Any]:
    """Remove a snippet by trigger."""
    trigger = str(trigger or "").strip()
    if not trigger:
        return {"ok": False, "error": "trigger is required"}

    data = load_snippets()
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
# Expansion logic
# =========================================================

def apply_snippets(text: str) -> str:
    """Expand all matching snippet triggers in the text.

    Scans for each enabled trigger and replaces it with the
    expansion text. Matching is case-insensitive and uses word
    boundaries so partial matches inside longer words don't fire.
    """
    if not text or not text.strip():
        return text

    data = load_snippets()
    result = text

    for item in data.get("snippets", []):
        if not item.get("enabled", True):
            continue

        trigger = str(item.get("trigger", "")).strip()
        expansion = str(item.get("expansion", "")).strip()
        if not trigger or not expansion:
            continue

        # triggers starting with "/" are literal prefix matches
        # other triggers use word boundary matching
        if trigger.startswith("/"):
            # literal replacement (case-insensitive)
            pattern = re.escape(trigger)
        else:
            pattern = rf"\b{re.escape(trigger)}\b"

        result = re.sub(pattern, expansion, result, flags=re.IGNORECASE)

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
            # python snippets.py cli add <trigger> <expansion>
            trigger = sys.argv[3] if len(sys.argv) > 3 else ""
            expansion = sys.argv[4] if len(sys.argv) > 4 else ""
            result = add_snippet(trigger, expansion)
            print(json.dumps(result, ensure_ascii=False))

        elif command == "remove":
            # python snippets.py cli remove <trigger>
            trigger = sys.argv[3] if len(sys.argv) > 3 else ""
            result = remove_snippet(trigger)
            print(json.dumps(result, ensure_ascii=False))

        elif command == "toggle":
            # python snippets.py cli toggle <trigger> <true|false>
            trigger = sys.argv[3] if len(sys.argv) > 3 else ""
            enabled = sys.argv[4].lower() not in ("false", "0", "no") if len(sys.argv) > 4 else True
            result = toggle_snippet(trigger, enabled)
            print(json.dumps(result, ensure_ascii=False))

        elif command == "expand":
            # python snippets.py cli expand <text>
            text = sys.argv[3] if len(sys.argv) > 3 else ""
            expanded = apply_snippets(text)
            print(json.dumps({"ok": True, "original": text, "expanded": expanded}, ensure_ascii=False))

        else:
            print(json.dumps({"ok": False, "error": f"unknown command: {command}"}, ensure_ascii=False))

        sys.exit(0)

    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        print(f"ERROR: {str(e)}", file=sys.stderr)
        sys.exit(1)
