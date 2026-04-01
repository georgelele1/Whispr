"""
Google Calendar integration for Whispr.

Per-user OAuth2 — each Google account gets its own token stored locally,
keyed by the user's actual Google email address.

First run opens a browser for one-time Google approval.
Subsequent runs refresh silently using the stored token.

CLI:
    python gcalendar.py connect     # first-time OAuth
    python gcalendar.py get-email   # print saved Google email
    python gcalendar.py today       # print today's schedule
    python gcalendar.py tomorrow    # print tomorrow's schedule
"""
from __future__ import annotations

import getpass
import io as _io
import json
import os
import sys
import threading
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytz
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

# Swallow [env] line connectonion prints on import
_real_stdout = sys.stdout
sys.stdout   = _io.StringIO()
try:
    from connectonion import Agent
finally:
    sys.stdout = _real_stdout

APP_NAME         = "Whispr"
SCOPES           = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]
REDIRECT_URI     = "http://localhost:8765/callback"
CREDENTIALS_FILE = Path(__file__).resolve().parent / "credentials.json"
DEFAULT_TZ       = "Australia/Sydney"


# =========================================================
# Token storage  (keyed by Google email, not system username)
# =========================================================

def _tokens_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support" / APP_NAME / "tokens"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(home))) / APP_NAME / "tokens"
    else:
        base = home / ".local" / "share" / APP_NAME / "tokens"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _token_path(email: str) -> Path:
    safe = email.replace("@", "_at_").replace(".", "_")
    return _tokens_dir() / f"{safe}.json"


def _current_email_file() -> Path:
    return _tokens_dir() / f"{getpass.getuser()}_current_email.txt"


def save_current_email(email: str) -> None:
    _current_email_file().write_text(email, encoding="utf-8")


def load_current_email() -> str | None:
    path = _current_email_file()
    return path.read_text(encoding="utf-8").strip() or None if path.exists() else None


# =========================================================
# OAuth flow  (browser-based, one-time per Google account)
# =========================================================

def run_oauth_flow() -> tuple[Credentials, str]:
    """Open browser for Google login, save token, return (credentials, email)."""
    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE), scopes=SCOPES, redirect_uri=REDIRECT_URI,
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline", include_granted_scopes="true",
    )

    auth_code   = {"value": None}
    server_done = threading.Event()

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if urlparse(self.path).path == "/callback":
                params = parse_qs(urlparse(self.path).query)
                auth_code["value"] = params.get("code", [None])[0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(
                    b"<html><body style='font-family:sans-serif;text-align:center;padding:60px'>"
                    b"<h2>Whispr connected to Google Calendar</h2>"
                    b"<p>You can close this tab.</p></body></html>"
                )
                server_done.set()

        def log_message(self, *_):
            pass

    threading.Thread(
        target=lambda: HTTPServer(("localhost", 8765), _Handler).handle_request(),
        daemon=True,
    ).start()

    print("Opening browser for Google login...", file=sys.stderr)
    webbrowser.open(auth_url)
    server_done.wait(timeout=120)

    if not auth_code["value"]:
        raise RuntimeError("Google login timed out or was cancelled.")

    flow.fetch_token(code=auth_code["value"])
    creds = flow.credentials

    import google.auth.transport.requests as _gtr
    email = _gtr.AuthorizedSession(creds).get(
        "https://www.googleapis.com/oauth2/v3/userinfo"
    ).json().get("email", getpass.getuser())

    _token_path(email).write_text(creds.to_json(), encoding="utf-8")
    save_current_email(email)
    print(f"Token saved for: {email}", file=sys.stderr)
    return creds, email


# =========================================================
# Auth  (in-memory cache — one disk read + zero OAuth per process)
# =========================================================

_creds_cache: dict[str, Credentials] = {}


def get_credentials(user_id: str | None = None) -> tuple[Credentials, str]:
    """Return (valid_credentials, google_email).

    Only triggers OAuth browser flow if NO valid token exists anywhere.
    Once a token is saved it persists until explicitly disconnected.

    Priority:
        1. In-memory cache (valid)
        2. In-memory cache (expired + refresh_token) → silent refresh
        3. Token file on disk (valid)
        4. Token file on disk (expired + refresh_token) → silent refresh
        5. OAuth browser flow — only if no token found at all
    """
    email = user_id or load_current_email()

    if email and email in _creds_cache:
        cached = _creds_cache[email]
        if cached.valid:
            return cached, email
        if cached.expired and cached.refresh_token:
            try:
                cached.refresh(Request())
                _token_path(email).write_text(cached.to_json(), encoding="utf-8")
                _creds_cache[email] = cached
                return cached, email
            except Exception:
                pass

    if email:
        path = _token_path(email)
        if path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(path), SCOPES)
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    path.write_text(creds.to_json(), encoding="utf-8")
                if creds and creds.valid:
                    _creds_cache[email] = creds
                    return creds, email
            except Exception:
                pass

    print("[calendar] no valid token found — starting OAuth flow", file=sys.stderr)
    creds, email = run_oauth_flow()
    _creds_cache[email] = creds
    return creds, email


# =========================================================
# Shared helpers
# =========================================================

def _get_calendars(service: Any, calendar_filter: str) -> list:
    all_cals = service.calendarList().list().execute().get("items", [])
    if calendar_filter == "all":
        return all_cals
    return [c for c in all_cals if calendar_filter.lower() in c.get("summary", "").lower()]


def _sort_events(events: list) -> list:
    return sorted(events, key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))


def _fmt_event(event: dict) -> str:
    raw     = event["start"].get("dateTime", event["start"].get("date", ""))
    summary = event.get("summary", "Untitled event")
    cal     = event.get("_cal", "")
    try:
        time_str = datetime.fromisoformat(raw).strftime("%I:%M %p")
    except Exception:
        time_str = raw
    return f"  - {time_str}: {summary} [{cal}]"


def _fmt_event_with_date(event: dict) -> str:
    raw     = event["start"].get("dateTime", event["start"].get("date", ""))
    summary = event.get("summary", "Untitled event")
    cal     = event.get("_cal", "")
    try:
        dt = datetime.fromisoformat(raw)
        return f"  - {dt.strftime('%a %d %b')} {dt.strftime('%I:%M %p')}: {summary} [{cal}]"
    except Exception:
        return f"  - {raw}: {summary} [{cal}]"


# =========================================================
# Schedule fetch
# =========================================================

def get_schedule(
    date: str = "today",
    timezone: str = DEFAULT_TZ,
    user_id: str | None = None,
    calendar_filter: str = "all",
) -> str:
    """Fetch and format all events on a given date.

    Args:
        date:            'today', 'tomorrow', or YYYY-MM-DD.
        timezone:        IANA timezone string.
        user_id:         Google email — defaults to last logged-in account.
        calendar_filter: Calendar name substring, or 'all'.
    """
    try:
        creds, email = get_credentials(user_id)
        service = build("calendar", "v3", credentials=creds)

        tz  = pytz.timezone(timezone)
        now = datetime.now(tz)

        if date == "today":
            target = now
        elif date == "tomorrow":
            target = now + timedelta(days=1)
        else:
            try:
                target = tz.localize(datetime.strptime(date, "%Y-%m-%d"))
            except ValueError:
                target = now

        start = target.replace(hour=0,  minute=0,  second=0,  microsecond=0).isoformat()
        end   = target.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()

        all_events = []
        for cal in _get_calendars(service, calendar_filter):
            for event in service.events().list(
                calendarId=cal["id"],
                timeMin=start,
                timeMax=end,
                singleEvents=True,
                orderBy="startTime",
            ).execute().get("items", []):
                event["_cal"] = cal.get("summary", cal["id"])
                all_events.append(event)

        all_events = _sort_events(all_events)

        if not all_events:
            return f"No events found for {date} ({email})."

        lines = [f"Schedule for {date} ({email}):"] + [_fmt_event(e) for e in all_events]
        return "\n".join(lines)

    except Exception as e:
        return f"Could not fetch calendar: {e}"


# =========================================================
# Event search
# =========================================================

def search_events(
    query: str,
    timezone: str = DEFAULT_TZ,
    user_id: str | None = None,
    calendar_filter: str = "all",
    max_results: int = 10,
) -> str:
    """Search for events matching a keyword across the next 365 days.

    Args:
        query:           Search term e.g. 'exam', 'COMP9900', 'dentist'.
        timezone:        IANA timezone string.
        user_id:         Google email — defaults to last logged-in account.
        calendar_filter: Calendar name substring, or 'all'.
        max_results:     Max events to return per calendar.
    """
    try:
        creds, email = get_credentials(user_id)
        service = build("calendar", "v3", credentials=creds)

        tz       = pytz.timezone(timezone)
        now      = datetime.now(tz)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=365)).isoformat()

        all_events = []
        for cal in _get_calendars(service, calendar_filter):
            for event in service.events().list(
                calendarId=cal["id"],
                q=query,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=max_results,
            ).execute().get("items", []):
                event["_cal"] = cal.get("summary", cal["id"])
                all_events.append(event)

        all_events = _sort_events(all_events)

        if not all_events:
            return f"No events found matching '{query}'."

        lines = [f"Events matching '{query}' ({email}):"] + [_fmt_event_with_date(e) for e in all_events]
        return "\n".join(lines)

    except Exception as e:
        return f"Could not search calendar: {e}"


# =========================================================
# LLM intent extraction
# =========================================================

def extract_calendar_intent(text: str) -> dict:
    """Extract date and calendar name from speech.

    Returns {"date": "today|tomorrow|YYYY-MM-DD", "calendar": "name|all"}.
    """
    agent = Agent(
        model="gpt-5",
        name="whispr_calendar_intent",
        system_prompt=(
            "Extract date and calendar from speech. "
            'Reply ONLY with JSON: {"date":"today|tomorrow|YYYY-MM-DD","calendar":"name|all"}. '
            "Default date=today, calendar=all if not mentioned. No explanation."
        ),
    )
    try:
        return json.loads(str(agent.input(text)).strip())
    except Exception:
        return {"date": "today", "calendar": "all"}


def extract_search_intent(text: str) -> dict:
    """Extract search query and calendar filter from speech.
    
    Returns {"query": "exam", "calendar": "all|name"}.
    """
    agent = Agent(
        model="gpt-5",
        name="whispr_search_intent",
        system_prompt=(
            "Extract a calendar search query from speech. "
            'Reply ONLY with JSON: {"query":"search term","calendar":"name|all"}. '
            "query = the specific thing being searched for (e.g. exam, dentist, COMP9900). "
            "calendar = calendar name if mentioned, else all. No explanation."
        ),
    )
    try:
        return json.loads(str(agent.input(text)).strip())
    except Exception:
        return {"query": text.strip(), "calendar": "all"}


# =========================================================
# CLI
# =========================================================

if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "today"

    if command == "get-email":
        email = load_current_email()
        print(json.dumps({"ok": email is not None, "email": email}, ensure_ascii=False))

    elif command == "connect":
        try:
            existing = load_current_email()
            if existing:
                path = _token_path(existing)
                if path.exists():
                    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
                    if creds and creds.valid:
                        print(json.dumps({"ok": True, "email": existing}, ensure_ascii=False))
                        sys.exit(0)
                    if creds and creds.expired and creds.refresh_token:
                        creds.refresh(Request())
                        path.write_text(creds.to_json(), encoding="utf-8")
                        print(json.dumps({"ok": True, "email": existing}, ensure_ascii=False))
                        sys.exit(0)
            _, email = run_oauth_flow()
            print(json.dumps({"ok": True, "email": email}, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"ok": False, "email": None, "error": str(e)}, ensure_ascii=False))

    elif command == "disconnect":
        email = load_current_email()
        if email:
            _token_path(email).unlink(missing_ok=True)
            _current_email_file().unlink(missing_ok=True)
            _creds_cache.pop(email, None)
            print(json.dumps({"ok": True, "email": None, "disconnected": email}, ensure_ascii=False))
        else:
            print(json.dumps({"ok": False, "email": None, "error": "no account connected"}, ensure_ascii=False))

    else:
        print(get_schedule(date=command))