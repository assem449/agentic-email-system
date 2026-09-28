import time
from dateutil import parser as dateparser
from datetime import datetime, timedelta

from app.state import EmailState
from app.config import GOOGLE_CALENDAR_ID
from app import db
from app.google_auth import get_calendar_service_for

# A meeting-classified email never books a real event by itself anymore.
# It proposes one (a `pending_events` row) and a human approves or
# rejects it via the /admin review endpoints, which call
# create_approved_event() below. This module makes no calendar.insert()
# call on the classify path — only on approval.


def _extract_proposed_time(body: str) -> datetime:
    try:
        return dateparser.parse(body, fuzzy=True, default=datetime.now())
    except Exception:
        return datetime.now() + timedelta(days=1)


def calendar_handler(state: EmailState) -> EmailState:
    """Classify-time node: never touches the Calendar API. Stores a
    proposal for a human to approve, or — if there's no participant
    (the account-free /route-email demo path) — just describes what
    would be proposed."""
    start = time.perf_counter()

    proposed_start = _extract_proposed_time(state["body"])
    proposed_end = proposed_start + timedelta(minutes=30)
    when = proposed_start.strftime("%A, %b %d at %I:%M %p")

    participant_id = state.get("participant_id")

    if participant_id:
        # Keep only a short preview, not the full email body, in what
        # gets persisted for review — same reasoning as the routing log.
        preview = (state["body"] or "")[:300]
        db.create_pending_event(
            participant_id=participant_id,
            gmail_id=state.get("gmail_id") or "",
            sender=state["sender"],
            subject=state["subject"],
            reply_preview=preview,
            proposed_start=proposed_start.isoformat(),
            proposed_end=proposed_end.isoformat(),
        )
        state["response"] = (
            f"Thanks for reaching out — proposing {when}. "
            f"I'll send a calendar invite once it's confirmed on my end."
        )
        state["handler_used"] = "calendar_pending_review"
    else:
        state["response"] = (
            f"[demo mode — no account connected] Would propose {when} "
            f"for human review; no event created."
        )
        state["handler_used"] = "calendar_pending_review_demo"

    state["tokens_used"] = 0
    state["input_tokens"] = 0
    state["output_tokens"] = 0
    state["latency_ms"] = (time.perf_counter() - start) * 1000
    return state


def create_approved_event(participant_id: str, pending_row) -> str:
    """Called only from the human-approval path (app.main's /admin/pending/
    {id}/approve). Actually books the event on that participant's real
    calendar. Returns the event's htmlLink."""
    service = get_calendar_service_for(participant_id)

    event_body = {
        "summary": f"Meeting re: {pending_row['subject'] or 'email request'}",
        "description": (
            f"Auto-proposed from an email, approved by a study reviewer.\n\n"
            f"From: {pending_row['sender']}\n"
            f"Preview: {pending_row['reply_preview']}"
        ),
        "start": {"dateTime": pending_row["proposed_start"], "timeZone": "America/Toronto"},
        "end": {"dateTime": pending_row["proposed_end"], "timeZone": "America/Toronto"},
    }

    created_event = service.events().insert(
        calendarId=GOOGLE_CALENDAR_ID,
        body=event_body,
    ).execute()

    return created_event.get("htmlLink", "")
