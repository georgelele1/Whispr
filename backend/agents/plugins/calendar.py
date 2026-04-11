"""
agents/plugins/calendar.py — Google Calendar plugin.

Handles: schedule fetching and named event search.
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
    r"(show|check|see|get|search|find|pull up|look at|give me|tell me|what.?s)"
    r"\s+(me\s+)?(my\s+)?(schedule|calendar|events?|agenda|appointments?|meetings?)"
    r"|what.?s\s+(on|happening)\s+(today|tomorrow|this week|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"|am\s+i\s+(free|available|busy)\s+(today|tomorrow|on|this|next)"
    r"|do\s+i\s+have\s+(anything|something|a meeting|an appointment)"
    r"|what\s+do\s+i\s+have\s+(today|tomorrow|on|this|next|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"|search\s+(my\s+)?(calendar|schedule)\s+for\s+(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|next|this|yesterday)"
    r"|what.?s\s+on\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"|my\s+(schedule|calendar|events?|agenda)\s+(for|on|this|next|today|tomorrow)?"
    r")\b",
    re.IGNORECASE,
)

_SEARCH = re.compile(
    r"\b(search|find|look for|when is|when.?s|what date is|what day is)\b"
    r".*?\b(exam|test|assignment|deadline|appointment|class|lecture|meeting|event|tutorial|workshop|seminar|session)\b"
    r"|when is (my\s+)?(exam|test|assignment|deadline|appointment|class|lecture|meeting|tutorial)"
    r"|\bsearch\s+(my\s+)?(calendar|schedule)\s+for\s+(?!today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|next|this|yesterday)\S"
    r"|\b(find|search for|look for)\s+(my\s+)?\w[\w\s]{1,30}?(tutorial|class|lecture|exam|meeting|appointment|session|workshop|seminar)\b",
    re.IGNORECASE,
)


def _parse_date(text: str) -> "str | None":
    """Extract a date reference from speech text."""
    t = text.lower().strip()
    if re.search(r'\btoday\b', t):     return "today"
    if re.search(r'\btomorrow\b', t):  return "tomorrow"
    if re.search(r'\byesterday\b', t): return "yesterday"
    m = re.search(r'\b(next|this)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', t)
    if m: return f"{m.group(1)} {m.group(2)}"
    m = re.search(r'\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b', t)
    if m: return m.group(1)
    if re.search(r'\bthis\s+week\b', t): return "this week"
    if re.search(r'\bnext\s+week\b', t): return "next week"
    m = re.search(r'\b(\d{4}-\d{2}-\d{2})\b', t)
    if m: return m.group(1)
    return None


def _extract_event_query(text: str) -> "str | None":
    """Extract the event name from a search phrase.

    Examples:
      "find my COMP9417 tutorial"           → "COMP9417 tutorial"
      "search my calendar for project demo" → "project demo"
      "when is my dentist appointment"      → "dentist appointment"
      "search my calendar for Friday"       → None  (it's a date, not event)
    """
    t = text.strip()

    # "search/find my calendar for <event>"
    m = re.search(
        r'(?:search|find|look\s+up)\s+(?:my\s+)?(?:calendar|schedule)\s+for\s+(.+)',
        t, re.IGNORECASE
    )
    if m:
        result = m.group(1).strip().rstrip(".")
        # Only use if it doesn't look like a date
        if not _parse_date(result):
            return result
        return None

    # "when is [my] <event>"
    m = re.search(r'when\s+is\s+(?:my\s+)?(.+?)(?:\?|$)', t, re.IGNORECASE)
    if m: return m.group(1).strip().rstrip(".")

    # "find/search for [my] <event>"
    m = re.search(
        r'(?:find|search(?:\s+for)?|look\s+for)\s+(?:my\s+)?(.+)',
        t, re.IGNORECASE
    )
    if m: return m.group(1).strip().rstrip(".")

    return None


class CalendarPlugin(WhisprPlugin):
    name        = "calendar"
    description = "Fetch Google Calendar schedule or search for specific events"
    priority    = 20

    def can_handle(self, text: str, context: dict) -> bool:
        if _DENY.search(text):
            return False
        # _SEARCH first — more specific than _FETCH
        return bool(_SEARCH.search(text) or _FETCH.search(text))

    def run(self, text: str, context: dict) -> str:
        try:
            from gcalendar import (
                load_current_email, get_schedule, search_events,
                extract_calendar_intent, extract_search_intent,
            )
            email = load_current_email()
            if not email:
                return "No Google Calendar connected. Say 'connect calendar' to set it up."

            # Use raw_text for best intent extraction
            raw = context.get("raw_text", text)

            if _SEARCH.search(text):
                # Named event search — extract event name from speech
                si    = extract_search_intent(raw)
                query = _extract_event_query(raw) or si.get("query") or raw
                result = search_events(
                    query=query,
                    user_id=email,
                    calendar_filter=si.get("calendar") or "all",
                )
            else:
                # Schedule fetch — extract date from speech
                cal  = extract_calendar_intent(raw)
                date = cal.get("date") or _parse_date(raw) or "today"
                result = get_schedule(
                    date=date,
                    user_id=email,
                    calendar_filter=cal.get("calendar") or "all",
                )

            # Friendly empty responses
            if not result or not result.strip():
                return "Your calendar is clear — no events found."
            if "no events found" in result.lower():
                date_m = re.search(
                    r'(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|this week|next week)',
                    raw, re.IGNORECASE
                )
                day = date_m.group(0).capitalize() if date_m else "that day"
                return f"Your calendar is clear for {day} — no events scheduled."
            return result

        except Exception as e:
            print(f"[calendar] failed: {e}", file=sys.stderr)
            return f"Could not fetch calendar: {e}"


plugin = CalendarPlugin()