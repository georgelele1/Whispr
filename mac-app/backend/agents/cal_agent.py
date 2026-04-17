"""
agents/cal_agent.py — Calendar fetch and search subagent.

Reads from Mac Calendar (EventKit) via gcalendar.py.

Events:
  after_user_input → inject_date     (temporal grounding)
  before_llm       → inject_language (language rule)
"""
from __future__ import annotations

import json
from datetime import datetime

import pytz
from storage import get_agent_model
from connectonion import Agent, after_user_input, before_llm

from agents.plugins.lang       import inject_language
from agents.plugins.visibility import show_summary

DEFAULT_TZ = "Australia/Sydney"


def _inject_date(agent) -> None:
    """after_user_input — inject today's date and timezone."""
    tz  = pytz.timezone(DEFAULT_TZ)
    now = datetime.now(tz)
    agent.current_session["messages"].append({
        "role":    "system",
        "content": (
            f"Current date: {now.strftime('%A, %Y-%m-%d')} ({DEFAULT_TZ}). "
            "Use this to resolve relative date references like today, tomorrow, next Monday. "
            "Do NOT assume the user is asking about today unless they explicitly say today."
        ),
    })


def _extract_intent(text: str) -> dict:
    """Single LLM call — decides mode, date/query, and calendar filter."""
    agent = Agent(
        model=get_agent_model(),
        name="whispr_calendar_intent",
        system_prompt=(
            "You extract calendar intent from voice input.\n\n"
            "Decide the mode first:\n"
            "  fetch  — user asks what is ON a specific day "
            "(today, tomorrow, this week, next Monday, etc.)\n"
            "  search — user asks WHEN something is, or asks to find/look up an event "
            "(exam date, dentist appointment, COMP9417 lecture, etc.)\n\n"
            "For fetch reply ONLY with JSON:\n"
            '  {"mode":"fetch","date":"today|tomorrow|this week|next week|YYYY-MM-DD","calendar":"name|all"}\n\n'
            "For search reply ONLY with JSON:\n"
            '  {"mode":"search","query":"<best search term for Mac Calendar>","calendar":"name|all"}\n\n'
            "query must be the most specific term that would match the event title "
            "— include course codes, keywords, or proper nouns from the input.\n"
            "calendar=all unless the user names a specific calendar.\n"
            "No explanation. No markdown. Raw JSON only."
        ),
        on_events=[
            after_user_input(_inject_date),
            before_llm(inject_language),
        ],
    )
    raw = str(agent.input(text)).strip()
    try:
        return json.loads(raw)
    except Exception:
        return {"mode": "search", "query": text.strip(), "calendar": "all"}


def run(text: str, raw_text: str) -> str:
    """Fetch schedule or search calendar based on speech."""
    from gcalendar import get_schedule, search_events

    intent = _extract_intent(raw_text)
    mode   = intent.get("mode", "search")
    cal    = intent.get("calendar") or "all"

    if mode == "fetch":
        date   = intent.get("date") or "today"
        result = get_schedule(date=date, calendar_filter=cal)
    else:
        query  = intent.get("query") or raw_text.strip()
        result = search_events(query=query, calendar_filter=cal)

    if not result or not result.strip() or "no events found" in result.lower():
        return "Your calendar is clear — no events found."
    return result