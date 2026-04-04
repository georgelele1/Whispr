"""
agents/plugins/calendar.py — Google Calendar plugin.

Handles: schedule fetching and event search.
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

_DENY = re.compile(
    r"\b("
    r"(my |the )?(calendar|schedule) is (full|busy|packed|clear|empty|free)"
    r"|don.?t have time|already (booked|scheduled)|cancel(led)? (the |my )?(meeting|appointment)"
    r"|reschedule|missed (the |my )?(meeting|appointment)"
    r")\b",
    re.IGNORECASE,
)

_FETCH = re.compile(
    r"\b("
    r"(show|check|see|get|what.?s|give me|tell me|look at)"
    r"\s+(me\s+)?(my\s+)?(schedule|calendar|events?|agenda|appointments?|meetings?)"
    r"|what.?s\s+(on|happening)\s+(today|tomorrow|this week|next week|monday|tuesday|wednesday|thursday|friday)"
    r"|am\s+i\s+(free|available|busy)\s+(today|tomorrow|on|this|next)"
    r"|do\s+i\s+have\s+(anything|something|a meeting|an appointment)"
    r")\b",
    re.IGNORECASE,
)

_SEARCH = re.compile(
    r"\b(search|find|look for|when is|when.?s|what date is|what day is)\b"
    r".*?\b(exam|test|assignment|deadline|appointment|class|lecture|meeting|event)\b"
    r"|when is (my\s+)?(exam|test|assignment|deadline|appointment|class|lecture|meeting)",
    re.IGNORECASE,
)


class CalendarPlugin(WhisprPlugin):
    name        = "calendar"
    description = (
        "Fetches the user Google Calendar schedule for a date, or searches for "
        "a specific event by keyword. Use when user wants to SEE their schedule "
        "or FIND a specific event like an exam, meeting, or appointment."
    )
    examples    = [
        "check my schedule for today",
        "what is on my calendar tomorrow",
        "when is my exam",
        "find my dentist appointment",
        "show my events for Friday",
    ]
    priority    = 20

    def can_handle(self, text: str, context: dict) -> bool:
        if _DENY.search(text):
            return False
        return bool(_FETCH.search(text) or _SEARCH.search(text))

    def run(self, text: str, context: dict) -> str:
        try:
            from gcalendar import (
                load_current_email, get_schedule, search_events,
                extract_calendar_intent, extract_search_intent,
            )
            email = load_current_email()
            if not email:
                return "No Google Calendar connected. Say 'connect calendar' to set it up."

            if _SEARCH.search(text):
                si = extract_search_intent(text)
                return search_events(
                    query=si.get("query") or text,
                    user_id=email,
                    calendar_filter=si.get("calendar") or "all",
                )
            else:
                cal = extract_calendar_intent(text)
                return get_schedule(
                    date=cal.get("date") or "today",
                    user_id=email,
                    calendar_filter=cal.get("calendar") or "all",
                )
        except Exception as e:
            print(f"[calendar] failed: {e}", file=sys.stderr)
            return f"Could not fetch calendar: {e}"


plugin = CalendarPlugin()