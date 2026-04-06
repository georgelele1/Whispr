"""
agents/plugins/snippets_plugin.py — Voice snippets plugin.

Handles: explicit shortcut expansion by trigger word.

Fixes vs previous version:
  - Removed import of DYNAMIC_TRIGGERS (never existed in snippets.py → ImportError)
  - Match against raw_text (context key) not clean_text so filler-stripped
    words like "my" don't break trigger matching
  - Relaxed _EXPLICIT: trigger word alone (without a verb prefix) now works
  - Calendar dynamic triggers handled inline without the missing constant
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_backend_root = str(_Path(__file__).resolve().parents[2])
if _backend_root not in _sys.path:
    _sys.path.insert(0, _backend_root)

import re
import sys

from agents.plugins.base import WhisprPlugin

# Verb prefixes that signal an explicit snippet request.
# We also accept bare trigger words (no prefix) — see can_handle.
_EXPLICIT = re.compile(
    r"\b(give me|insert|paste|use|show me|open|pull up|get me|expand)\b",
    re.IGNORECASE,
)

# Triggers that resolve dynamically at runtime (not a static string in the json)
_DYNAMIC_TRIGGER_KEYWORDS = {"calendar", "schedule", "today's schedule", "my schedule"}


class SnippetsPlugin(WhisprPlugin):
    name        = "snippets"
    description = "Expand user-defined voice shortcuts by trigger word"
    priority    = 30

    def can_handle(self, text: str, context: dict) -> bool:
        triggers = context.get("snippet_triggers", [])
        if not triggers:
            return False

        # Use raw_text for matching — clean_text may have had "my" stripped
        # by the filler remover, breaking triggers like "my zoom link"
        match_text = context.get("raw_text", text)

        # Accept if an explicit verb prefix is present OR the text contains
        # a trigger on its own (user just says the trigger word directly)
        has_verb    = bool(_EXPLICIT.search(match_text))
        has_trigger = any(t.lower() in match_text.lower() for t in triggers)

        return has_trigger and (has_verb or _is_short_trigger_only(match_text, triggers))

    def run(self, text: str, context: dict) -> str:
        try:
            from snippets import load_snippets

            snippets = {
                item["trigger"].lower(): item["expansion"]
                for item in load_snippets().get("snippets", [])
                if item.get("enabled", True)
                and str(item.get("trigger", "")).strip()
                and str(item.get("expansion", "")).strip()
            }

            # Match against raw_text so filler-stripping doesn't hide the trigger
            match_text = context.get("raw_text", text).lower()

            for trigger, expansion in snippets.items():
                if trigger in match_text:
                    # Dynamic: calendar / schedule triggers
                    if any(kw in trigger for kw in _DYNAMIC_TRIGGER_KEYWORDS):
                        try:
                            from gcalendar import get_schedule, load_current_email
                            email = load_current_email()
                            if email:
                                return get_schedule(date="today", user_id=email)
                            return "No Google Calendar connected."
                        except Exception as cal_err:
                            print(f"[snippets] calendar dynamic error: {cal_err}", file=sys.stderr)
                            return expansion  # fall back to stored expansion

                    # URL snippets — wrap in a natural label
                    if expansion.startswith(("http://", "https://")):
                        label = trigger.title()
                        return f"{label} ({expansion})"

                    # Plain text expansion
                    return expansion

            return text

        except Exception as e:
            print(f"[snippets] plugin failed: {e}", file=sys.stderr)
            return text


def _is_short_trigger_only(text: str, triggers: list) -> bool:
    """Return True if the whole utterance is essentially just the trigger word/phrase."""
    stripped = text.strip().lower()
    for t in triggers:
        if stripped == t.lower():
            return True
        # Allow minor surrounding words: "my zoom link", "the zoom link please"
        if re.fullmatch(
            r"(my |the |a |please |can i (have|get) )?" + re.escape(t.lower()) + r"( please)?",
            stripped,
        ):
            return True
    return False


plugin = SnippetsPlugin()