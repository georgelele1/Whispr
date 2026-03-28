"""
Google Calendar integration for Whispr.

Per-user OAuth2 — each machine user gets their own token stored locally.
First run opens a browser for one-time Google approval; subsequent runs
refresh silently.

Usage:
    python gcalendar.py today
    python gcalendar.py tomorrow
"""

from __future__ import annotations

import getpass
import json
import os
import sys
import threading
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytz
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from connectonion import Agent

APP_NAME         = "Whispr"
SCOPES           = ["https://www.googleapis.com/auth/calendar.readonly"]
REDIRECT_URI     = "http://localhost:8765/callback"
CREDENTIALS_FILE = Path(__file__).resolve().parent / "credentials.json"


# =========================================================
# Per-user token storage
# =========================================================

def tokens_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support" / APP_NAME / "tokens"
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(home))) / APP_NAME / "tokens"
    else:
        base = home / ".local" / "share" / APP_NAME / "tokens"
    base.mkdir(parents=True, exist_ok=True)
    return base


def token_path(user_id: str) -> Path:
    safe = user_id.replace("@", "_").replace(".", "_")
    return tokens_dir() / f"{safe}.json"


# =========================================================
# OAuth flow (browser-based, one-time per user)
# =========================================================

def run_oauth_flow(user_id: str) -> Credentials:
    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE), scopes=SCOPES, redirect_uri=REDIRECT_URI,
    )
    auth_url, _ = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent",
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
                self.wfile.write(b"""
                    <html><body style='font-family:sans-serif;text-align:center;padding:60px'>
                    <h2>Whispr connected to Google Calendar</h2>
                    <p>You can close this tab.</p>
                    </body></html>
                """)
                server_done.set()
        def log_message(self, *_): pass

    server = HTTPServer(("localhost", 8765), _Handler)
    threading.Thread(target=lambda: server.handle_request(), daemon=True).start()

    print("Opening browser for Google login...", file=sys.stderr)
    webbrowser.open(auth_url)
    server_done.wait(timeout=120)

    if not auth_code["value"]:
        raise RuntimeError("Google login timed out or was cancelled.")

    flow.fetch_token(code=auth_code["value"])
    creds = flow.credentials
    token_path(user_id).write_text(creds.to_json(), encoding="utf-8")
    print(f"Token saved for: {user_id}", file=sys.stderr)
    return creds


# =========================================================
# Auth
# =========================================================

def get_credentials(user_id: str | None = None) -> Credentials:
    """Return valid credentials, refreshing or re-authenticating as needed."""
    if user_id is None:
        user_id = getpass.getuser()

    path  = token_path(user_id)
    creds = None

    if path.exists():
        creds = Credentials.from_authorized_user_file(str(path), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    if creds and creds.valid:
        return creds

    return run_oauth_flow(user_id)


# =========================================================
# Intent extraction  (combined date + calendar in one call)
# =========================================================

def extract_calendar_intent(text: str) -> dict:
    """Extract date and calendar name from transcribed speech in one agent call.

    Returns {"date": "today|tomorrow|YYYY-MM-DD", "calendar": "name|all"}.
    Prompt kept minimal to avoid token bloat (was causing 14s latency).
    """
    agent = Agent(
        model="gpt-5",
        name="whispr_calendar_intent",
        system_prompt=(
            "Extract date and calendar from speech. "
            "Reply ONLY with JSON: {\"date\":\"today|tomorrow|YYYY-MM-DD\",\"calendar\":\"name|all\"}. "
            "Default date=today, calendar=all if not mentioned. No explanation."
        ),
    )
    try:
        return json.loads(str(agent.input(text)).strip())
    except Exception:
        return {"date": "today", "calendar": "all"}


def extract_date_from_text(text: str) -> str:
    """Lightweight date-only extraction (used when calendar name is not needed)."""
    result = extract_calendar_intent(text)
    return result.get("date", "today")


# =========================================================
# Schedule fetcher
# =========================================================

def get_schedule(date: str = "today", timezone: str = "Australia/Sydney") -> str:
    try:
        creds   = get_credentials(user_id)
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

        # Get all calendars
        calendars = service.calendarList().list().execute().get("items", [])

        all_events = []
        for cal in calendars:
            cal_id = cal["id"]
            cal_name = cal.get("summary", cal_id)

            events = service.events().list(
                calendarId=cal_id,
                timeMin=start,
                timeMax=end,
                singleEvents=True,
                orderBy="startTime",
            ).execute().get("items", [])

            for event in events:
                event["_calendar_name"] = cal_name  # tag which calendar it came from
                all_events.append(event)

        # Sort all events by start time
        all_events.sort(key=lambda e: e["start"].get("dateTime", e["start"].get("date", "")))

        if not all_events:
            return f"No events found for {date}."

        lines = [f"Schedule for {date}:"]
        for event in all_events:
            start_raw = event["start"].get("dateTime", event["start"].get("date", ""))
            summary = event.get("summary", "Untitled event")
            cal_name = event.get("_calendar_name", "")

            try:
                time_str = datetime.fromisoformat(raw).strftime("%I:%M %p")
            except Exception:
                time_str = raw
            lines.append(f"  - {time_str}: {summary} [{cal}]")

        return "\n".join(lines)

    except Exception as e:
        return f"Could not fetch calendar: {e}"

# =========================================================
# CLI
# =========================================================

if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else "today"
    print(get_schedule(date=date_arg))