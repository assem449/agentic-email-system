import time
import re
from datetime import datetime, timedelta
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.state import EmailState
from app.config import GOOGLE_CALENDAR_ID, GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH

SCOPES = ["https://www.googleapis.com/auth/calendar"]

def _get_service():
    creds = None
    token_path = Path(GOOGLE_TOKEN_PATH)

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return build("calendar", "v3", credentials=creds)

def _extract_proposed_time(body: str) -> datetime:
    # Step 6 placeholder: no real NLP date parsing yet.
    # Just defaults to "tomorrow at 10am" so we can confirm the API call works.
    tomorrow = datetime.now() + timedelta(days=1)
    return tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)

def calendar_handler(state: EmailState) -> EmailState:
    start = time.perf_counter()

    service = _get_service()
    proposed_start = _extract_proposed_time(state["body"])
    proposed_end = proposed_start + timedelta(minutes=30)

    event_body = {
        "summary": f"Meeting re: {state['subject'] or 'email request'}",
        "description": f"Auto-scheduled from email.\n\nOriginal message:\n{state['body']}",
        "start": {"dateTime": proposed_start.isoformat(), "timeZone": "America/Toronto"},
        "end": {"dateTime": proposed_end.isoformat(), "timeZone": "America/Toronto"},
    }

    created_event = service.events().insert(
        calendarId=GOOGLE_CALENDAR_ID,
        body=event_body,
    ).execute()

    state["response"] = (
        f"Meeting scheduled for {proposed_start.strftime('%A, %b %d at %I:%M %p')}. "
        f"Calendar link: {created_event.get('htmlLink')}"
    )
    state["handler_used"] = "calendar"
    state["tokens_used"] = 0
    state["latency_ms"] = (time.perf_counter() - start) * 1000
    return state