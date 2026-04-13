"""
agents/calendar.py — Calendar fetch and search subagent.

Events:
  after_user_input → inject_date    (temporal grounding)
  before_llm       → inject_language (language plugin)

No profile, dictionary, eval, or snippet updates.
Calendar returns raw schedule data — not user-facing refined text.
"""
from __future__ import annotations

import json
import re
import sys
import io as _io
from datetime import datetime

import pytz

_real = sys.stdout
sys.stdout = _io.StringIO()
from connectonion import Agent, after_user_input, before_llm, on_complete
sys.stdout = _real

from agents.plugins.lang   import inject_language
from agents.plugins.visibility import show_summary

DEFAULT_TZ = "Australia/Sydney"

_SEARCH = re.compile(
    r"\b(search|find|look for|when is|when.?s)\b"
    r".*?\b(exam|test|assignment|deadline|appointment|class|lecture|meeting|tutorial|workshop)\b"
    r"|\bsearch\s+(my\s+)?(calendar|schedule)\s+for\s+"
    r"(?!today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
    re.IGNORECASE,
)


def _inject_date(agent) -> None:
    """after_user_input — inject today's date and timezone."""
    tz  = pytz.timezone(DEFAULT_TZ)
    now = datetime.now(tz)
    agent.current_session["messages"].append({
        "role":    "system",
        "content": (
            f"Current date: {now.strftime('%A, %Y-%m-%d')}. "
            f"Current time: {now.strftime('%H:%M')} ({DEFAULT_TZ}). "
            "Use this to resolve relative references like today, tomorrow, next Monday."
        ),
    })


def _set_intent(agent) -> None:
    agent.current_session["whispr_intent"] = "calendar"


def _extract_intent(text: str, mode: str) -> dict:
    """Extract date/query and calendar filter from speech."""
    if mode == "search":
        system  = (
            "Extract a calendar search query from speech. "
            'Reply ONLY with JSON: {"query":"search term","calendar":"name|all"}. '
            "No explanation."
        )
        default = {"query": text.strip(), "calendar": "all"}
    else:
        system  = (
            "Extract date and calendar from speech. "
            'Reply ONLY with JSON: {"date":"today|tomorrow|YYYY-MM-DD","calendar":"name|all"}. '
            "Default date=today, calendar=all. No explanation."
        )
        default = {"date": "today", "calendar": "all"}

    agent = Agent(
        model="gpt-5.4",
        name="whispr_calendar_intent",
        system_prompt=system,
        on_events=[
            after_user_input(_inject_date),
            before_llm(inject_language),
        ],
    )
    raw = str(agent.input(text)).strip()
    return json.loads(raw) if raw.startswith("{") else default


def run(text: str, raw_text: str) -> str:
    """Fetch schedule or search calendar."""
    from gcalendar import load_current_email, get_schedule, search_events

    email = load_current_email()
    if not email:
        return "No Google Calendar connected."

    if _SEARCH.search(text):
        intent = _extract_intent(raw_text, "search")
        result = search_events(
            query           = intent.get("query") or raw_text,
            user_id         = email,
            calendar_filter = intent.get("calendar") or "all",
        )
    else:
        intent = _extract_intent(raw_text, "fetch")
        result = get_schedule(
            date            = intent.get("date") or "today",
            user_id         = email,
            calendar_filter = intent.get("calendar") or "all",
        )

    if not result or not result.strip() or "no events found" in result.lower():
        return "Your calendar is clear — no events found."
    return result