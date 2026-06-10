"""
Read-only macOS Calendar agent backed by EventKit.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List

from connectonion import Agent

from storage import get_agent_model, get_target_language


def _iso_datetime(value: str, default: datetime) -> datetime:
    value = str(value or "").strip()
    if not value:
        return default

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed
    except ValueError:
        return default


def _nsdate_to_datetime(value) -> datetime:
    return datetime.fromtimestamp(float(value.timeIntervalSince1970()))


def _request_calendar_access(store, timeout: float = 15.0) -> tuple[bool, str]:
    try:
        import EventKit
    except ImportError:
        return False, "EventKit is unavailable. This tool only works on macOS."

    status = EventKit.EKEventStore.authorizationStatusForEntityType_(
        EventKit.EKEntityTypeEvent
    )

    authorized_statuses = {
        value for value in (
            getattr(EventKit, "EKAuthorizationStatusAuthorized", None),
            getattr(EventKit, "EKAuthorizationStatusFullAccess", None),
        )
        if value is not None
    }

    if status in authorized_statuses:
        return True, ""

    denied_statuses = {
        value for value in (
            getattr(EventKit, "EKAuthorizationStatusDenied", None),
            getattr(EventKit, "EKAuthorizationStatusRestricted", None),
        )
        if value is not None
    }

    if status in denied_statuses:
        return False, (
            "Calendar access is denied. Enable Whispr in "
            "System Settings > Privacy & Security > Calendars."
        )

    completed = threading.Event()
    result = {"granted": False, "error": ""}

    def _completion(granted, error) -> None:
        result["granted"] = bool(granted)
        result["error"] = str(error or "")
        completed.set()

    if hasattr(store, "requestFullAccessToEventsWithCompletion_"):
        store.requestFullAccessToEventsWithCompletion_(_completion)
    else:
        store.requestAccessToEntityType_completion_(
            EventKit.EKEntityTypeEvent,
            _completion,
        )

    deadline = time.monotonic() + timeout
    try:
        from Foundation import NSDate, NSRunLoop

        while not completed.is_set() and time.monotonic() < deadline:
            NSRunLoop.currentRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.1)
            )
    except ImportError:
        completed.wait(timeout)

    if not completed.is_set():
        return False, "Timed out while requesting Calendar permission."

    if not result["granted"]:
        return False, result["error"] or "Calendar permission was not granted."

    return True, ""


def query_calendar_events(
    start_iso: str = "",
    end_iso: str = "",
    search_text: str = "",
    limit: int = 30,
) -> Dict[str, Any]:
    """Return macOS Calendar events in a local date range."""
    try:
        import EventKit
        from Foundation import NSDate
    except ImportError:
        return {
            "ok": False,
            "events": [],
            "error": "EventKit is unavailable. Calendar queries require macOS.",
        }

    now = datetime.now()
    start = _iso_datetime(start_iso, now.replace(hour=0, minute=0, second=0, microsecond=0))
    end = _iso_datetime(end_iso, start + timedelta(days=1))
    if end <= start:
        end = start + timedelta(days=1)

    store = EventKit.EKEventStore.alloc().init()
    granted, error = _request_calendar_access(store)
    if not granted:
        return {"ok": False, "events": [], "error": error}

    start_date = NSDate.dateWithTimeIntervalSince1970_(start.timestamp())
    end_date = NSDate.dateWithTimeIntervalSince1970_(end.timestamp())
    predicate = store.predicateForEventsWithStartDate_endDate_calendars_(
        start_date,
        end_date,
        None,
    )
    events = list(store.eventsMatchingPredicate_(predicate) or [])

    needle = str(search_text or "").strip().lower()
    output: List[Dict[str, Any]] = []

    for event in sorted(
        events,
        key=lambda item: float(item.startDate().timeIntervalSince1970()),
    ):
        title = str(event.title() or "").strip()
        location = str(event.location() or "").strip()
        notes = str(event.notes() or "").strip()

        if needle and needle not in " ".join((title, location, notes)).lower():
            continue

        output.append({
            "title": title or "Untitled event",
            "start": _nsdate_to_datetime(event.startDate()).isoformat(timespec="minutes"),
            "end": _nsdate_to_datetime(event.endDate()).isoformat(timespec="minutes"),
            "all_day": bool(event.isAllDay()),
            "calendar": str(event.calendar().title() or ""),
            "location": location,
            "notes": notes[:500],
        })

        if len(output) >= max(1, min(int(limit or 30), 100)):
            break

    return {
        "ok": True,
        "events": output,
        "count": len(output),
        "range": {
            "start": start.isoformat(timespec="minutes"),
            "end": end.isoformat(timespec="minutes"),
        },
    }


def run(
    user_text: str,
    start_iso: str = "",
    end_iso: str = "",
    search_text: str = "",
) -> str:
    calendar_result = query_calendar_events(
        start_iso=start_iso,
        end_iso=end_iso,
        search_text=search_text,
    )

    if not calendar_result.get("ok"):
        return str(calendar_result.get("error", "Calendar query failed."))

    agent = Agent(
        model=get_agent_model(),
        name="whispr_calendar_agent",
        system_prompt=(
            "You answer questions about the user's macOS Calendar using only the "
            "provided event data. Do not invent events, attendees, dates, or times. "
            "If no events match, say so clearly. Keep the answer concise and useful. "
            f"Respond in {get_target_language()}."
        ),
    )

    return str(agent.input(
        f"User request:\n{user_text}\n\n"
        f"Calendar data:\n{calendar_result}"
    )).strip()
