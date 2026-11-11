"""Calendar handler: stages a proposed meeting; never writes to the calendar.

Routing a message here does three things and nothing else:
  1. extracts a proposed time from the body (naive fuzzy parse, see below),
  2. stages a pending record keyed by a confirmation token (app/pending.py),
  3. returns a draft reply proposing that time to the sender.

The calendar event is created only when the operator confirms the record
through POST /pending/{token}/confirm (app/main.py), which calls
insert_event() below. A misrouted email therefore produces a discardable
proposal, not a booked appointment.

Date extraction is deliberately simple and NOT validated: dateutil's fuzzy
parser over the whole body, falling back to the same time tomorrow when it
finds nothing. time_source records which happened, so the operator can see
a fallback before confirming. Evaluation replaces this handler with a fixed
stub (eval_run.py), so neither parsing nor the API round trip is in any
reported latency.
"""
import time
from datetime import datetime, timedelta
from pathlib import Path

from dateutil import parser as dateparser

from app import pending
from app.config import (CALENDAR_TIMEZONE, GOOGLE_CALENDAR_ID,
                        GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH,
                        MEETING_MINUTES)
from app.state import EmailState

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_service():
    # Imported here so staging (and the tests) need no Google libraries;
    # only the confirmation path talks to the API.
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

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


def _extract_proposed_time(body: str, now: datetime = None):
    """Returns (datetime, 'parsed' | 'fallback')."""
    now = now or datetime.now()
    try:
        parsed = dateparser.parse(body, fuzzy=True, default=now)
    except (ValueError, OverflowError):
        parsed = None
    if parsed is None or parsed == now:
        return now + timedelta(days=1), "fallback"
    return parsed, "parsed"


def _draft_text(start: datetime, time_source: str) -> str:
    # Sent to the email's sender if the user sends the draft, so it must not
    # contain the confirmation token or claim anything is booked.
    if time_source == "parsed":
        return (f"Thanks for reaching out. Would {start.strftime('%A, %b %d at %I:%M %p')} "
                f"work for a {MEETING_MINUTES}-minute meeting? I'll send a calendar "
                "invitation once it's confirmed.")
    return ("Thanks for reaching out, I'd be happy to meet. Could you suggest a "
            "few times that work for you?")


def calendar_handler(state: EmailState) -> EmailState:
    start_t = time.perf_counter()

    proposed_start, time_source = _extract_proposed_time(state["body"])
    proposed_end = proposed_start + timedelta(minutes=MEETING_MINUTES)

    token = pending.stage(
        email_id=state.get("email_id"), sender=state.get("sender"),
        subject=state.get("subject"), body=state["body"],
        start_iso=proposed_start.isoformat(), end_iso=proposed_end.isoformat(),
        timezone=CALENDAR_TIMEZONE, time_source=time_source,
    )

    state["response"] = _draft_text(proposed_start, time_source)
    state["confirmation_token"] = token
    state["handler_used"] = "calendar"
    state["tokens_used"] = 0
    state["input_tokens"] = 0
    state["output_tokens"] = 0
    state["latency_ms"] = (time.perf_counter() - start_t) * 1000
    return state


def insert_event(record: dict, event_id: str, service=None) -> dict:
    """The only calendar write in the system. Called by pending.confirm().

    Uses a deterministic event id, so a retry after a crash between the
    insert and the database update finds the existing event instead of
    creating a second one.
    """
    from googleapiclient.errors import HttpError

    service = service or _get_service()
    body = {
        "id": event_id,
        "summary": f"Meeting re: {record['subject'] or 'email request'}",
        "description": ("Confirmed from an email proposal.\n\n"
                        f"From: {record['sender']}\n\n{record['body']}"),
        "start": {"dateTime": record["start_iso"], "timeZone": record["timezone"]},
        "end": {"dateTime": record["end_iso"], "timeZone": record["timezone"]},
    }
    try:
        return service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=body).execute()
    except HttpError as e:
        if getattr(e, "status_code", None) == 409 or getattr(e.resp, "status", None) == 409:
            return service.events().get(calendarId=GOOGLE_CALENDAR_ID,
                                        eventId=event_id).execute()
        raise
