"""
Google Calendar integration for Whispr.

Fetches events for a given date using OAuth2 credentials.
Supports multiple users — each user gets their own token stored locally.

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

APP_NAME = "Whispr"
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
REDIRECT_URI = "http://localhost:8765/callback"
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
# OAuth flow
# =========================================================

def run_oauth_flow(user_id: str) -> Credentials:
    """Open browser for Google login and capture the callback token."""

    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_FILE),
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    auth_code = {"value": None}
    server_done = threading.Event()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/callback":
                params = parse_qs(parsed.query)
                auth_code["value"] = params.get("code", [None])[0]
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"""
                    <html><body style='font-family:sans-serif;text-align:center;padding:60px'>
                    <h2>Whispr is connected to Google Calendar</h2>
                    <p>You can close this tab and return to Whispr.</p>
                    </body></html>
                """)
                server_done.set()

        def log_message(self, *args):
            pass

    server = HTTPServer(("localhost", 8765), CallbackHandler)
    thread = threading.Thread(target=lambda: server.handle_request())
    thread.start()

    print(f"Opening browser for Google login...", file=sys.stderr)
    webbrowser.open(auth_url)

    server_done.wait(timeout=120)

    if not auth_code["value"]:
        raise RuntimeError("Google login timed out or was cancelled.")

    flow.fetch_token(code=auth_code["value"])
    creds = flow.credentials

    path = token_path(user_id)
    path.write_text(creds.to_json(), encoding="utf-8")
    print(f"Token saved for user: {user_id}", file=sys.stderr)

    return creds


# =========================================================
# Auth
# =========================================================

def get_credentials(user_id: str = None) -> Credentials:
    """Get valid credentials for user, triggering OAuth flow if needed."""
    if user_id is None:
        user_id = getpass.getuser()

    path = token_path(user_id)
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
# Date extraction via agent
# =========================================================

def extract_date_from_text(text: str) -> str:
    """Use agent to extract the intended date from transcribed text."""
    agent = Agent(
        model="gpt-5",
        name="whispr_date_extractor",
        system_prompt=(
            "You extract a date reference from transcribed speech. "
            "Return only one of: 'today', 'tomorrow', or a date in YYYY-MM-DD format. "
            "If no date is mentioned, return 'today'. "
            "No explanation, no punctuation, just the date string."
        )
    )
    result = str(agent.input(text)).strip()
    return result if result else "today"


# =========================================================
# Calendar intent extraction
# =========================================================

def extract_calendar_intent(text: str) -> dict:
    """Extract both date and which calendar the user wants."""
    agent = Agent(
        model="gpt-5",
        name="whispr_calendar_intent",
        system_prompt=(
            "Extract the date and calendar name from transcribed speech. "
            "Return ONLY a JSON object with keys 'date' and 'calendar'. "
            "For date: 'today', 'tomorrow', or YYYY-MM-DD. "
            "For calendar: the calendar name mentioned, or 'all' if none specified. "
            "No explanation, just the JSON object."
        )
    )
    result = str(agent.input(text)).strip()
    try:
        return json.loads(result)
    except Exception:
        return {"date": "today", "calendar": "all"}


# =========================================================
# Schedule fetcher
# =========================================================

def get_schedule(date: str = "today", timezone: str = "Australia/Sydney") -> str:
    try:
        creds = get_credentials(user_id)
        service = build("calendar", "v3", credentials=creds)

        tz = pytz.timezone(timezone)
        now = datetime.now(tz)

        if date == "today":
            target = now
        elif date == "tomorrow":
            target = now + timedelta(days=1)
        else:
            try:
                parsed = datetime.strptime(date, "%Y-%m-%d")
                target = tz.localize(parsed)
            except ValueError:
                target = now

        start = target.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
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
                dt = datetime.fromisoformat(start_raw)
                time_str = dt.strftime("%I:%M %p")
            except Exception:
                time_str = start_raw

            lines.append(f"  - {time_str}: {summary} [{cal_name}]")

        return "\n".join(lines)

    except Exception as e:
        return f"Could not fetch calendar: {str(e)}"

# =========================================================
# CLI test
# =========================================================

if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else "today"
    print(get_schedule(date=date_arg))