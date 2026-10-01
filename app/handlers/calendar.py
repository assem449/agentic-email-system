import time
from dateutil import parser as dateparser
from datetime import datetime, timedelta

from app.state import EmailState
from app.config import GOOGLE_CALENDAR_ID
from app import db
from app.google_auth import NotConnected, get_calendar_service_for

# A meeting-classified email never books a real event by itself anymore.
# It proposes one (a `pending_events` row) and a human approves or
# rejects it — either the participant themselves on their own check-in
# page, or a researcher on /admin — which calls create_approved_event()
# below. This module makes no calendar.insert() call on the classify
# path, only on approval; it does read the calendar (freebusy) at
# classify time, to propose a slot that's actually free.

BUSINESS_START_HOUR = 9
BUSINESS_END_HOUR = 18
SLOT_MINUTES = 30
MEETING_DURATION_MINUTES = 30
SEARCH_WINDOW_DAYS = 5
_MAX_CANDIDATES = 300  # hard cap so a pathological calendar can't loop forever


def _extract_proposed_time(body: str) -> datetime:
    try:
        return dateparser.parse(body, fuzzy=True, default=datetime.now())
    except Exception:
        return datetime.now() + timedelta(days=1)


def _is_business_hours(dt: datetime) -> bool:
    return dt.weekday() < 5 and BUSINESS_START_HOUR <= dt.hour < BUSINESS_END_HOUR


def _round_up_to_slot(dt: datetime) -> datetime:
    dt = dt.replace(second=0, microsecond=0)
    remainder = dt.minute % SLOT_MINUTES
    if remainder:
        dt += timedelta(minutes=SLOT_MINUTES - remainder)
    return dt


def _next_candidate(dt: datetime) -> datetime:
    """Round up to the next slot start, then skip forward over evenings/
    weekends until it lands inside business hours."""
    dt = _round_up_to_slot(dt)
    while not _is_business_hours(dt):
        if dt.hour >= BUSINESS_END_HOUR or dt.weekday() >= 5:
            dt = (dt + timedelta(days=1)).replace(
                hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0
            )
        else:  # before business hours, same day
            dt = dt.replace(hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0)
    return dt


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def find_available_slot(service, calendar_id: str, desired_start: datetime):
    """If `desired_start` (snapped into business hours) is free, use it.
    Otherwise scan forward in SLOT_MINUTES steps, business hours and
    weekdays only, for the first open MEETING_DURATION_MINUTES slot
    within SEARCH_WINDOW_DAYS. Returns (start, end, moved: bool) — moved
    is True only when the returned slot differs from the business-hours
    snap of the originally requested time.

    On any Calendar API failure, falls back to the originally requested
    time rather than blocking the whole proposal on an availability
    check the participant can still review and reject themselves."""
    duration = timedelta(minutes=MEETING_DURATION_MINUTES)
    window_start = min(desired_start, datetime.now())
    window_end = window_start + timedelta(days=SEARCH_WINDOW_DAYS)

    try:
        resp = service.freebusy().query(body={
            "timeMin": window_start.isoformat(),
            "timeMax": window_end.isoformat(),
            "items": [{"id": calendar_id}],
        }).execute()
        busy = [
            (dateparser.parse(b["start"]), dateparser.parse(b["end"]))
            for b in resp["calendars"][calendar_id]["busy"]
        ]
    except Exception:
        return desired_start, desired_start + duration, False

    candidate = _next_candidate(desired_start)
    original = candidate

    for _ in range(_MAX_CANDIDATES):
        candidate_end = candidate + duration
        if candidate_end.hour > BUSINESS_END_HOUR or (
            candidate_end.hour == BUSINESS_END_HOUR and candidate_end.minute > 0
        ):
            candidate = _next_candidate(candidate + timedelta(days=1))
            continue

        # busy[] entries are UTC-aware; compare on equal footing.
        c_start = candidate if candidate.tzinfo else candidate.astimezone()
        c_end = candidate_end if candidate_end.tzinfo else candidate_end.astimezone()
        if not any(_overlaps(c_start, c_end, b_start, b_end) for b_start, b_end in busy):
            return candidate, candidate_end, candidate != original
        candidate = _next_candidate(candidate_end)

    return desired_start, desired_start + duration, False


def calendar_handler(state: EmailState) -> EmailState:
    """Classify-time node: proposes a meeting slot, checked against the
    participant's real calendar availability, for a human (the
    participant, or a researcher reviewer) to approve. Never books
    anything itself — only create_approved_event() does that."""
    start = time.perf_counter()

    requested_time = _extract_proposed_time(state["body"])
    participant_id = state.get("participant_id")

    if participant_id:
        moved = False
        try:
            service = get_calendar_service_for(participant_id)
            proposed_start, proposed_end, moved = find_available_slot(
                service, GOOGLE_CALENDAR_ID, requested_time
            )
        except NotConnected:
            proposed_start = requested_time
            proposed_end = requested_time + timedelta(minutes=MEETING_DURATION_MINUTES)

        when = proposed_start.strftime("%A, %b %d at %I:%M %p")

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
            time_adjusted=moved,
        )

        moved_note = (
            " The time you asked for was already busy on my calendar, so I picked the next open slot."
            if moved else ""
        )
        state["response"] = (
            f"Thanks for reaching out, proposing {when}.{moved_note} "
            f"I'll add this to my calendar once it's confirmed."
        )
        state["handler_used"] = "calendar_pending_review"
    else:
        when = requested_time.strftime("%A, %b %d at %I:%M %p")
        state["response"] = (
            f"[demo mode, no account connected] Would check availability and propose "
            f"around {when} for human review; no event created."
        )
        state["handler_used"] = "calendar_pending_review_demo"

    state["tokens_used"] = 0
    state["input_tokens"] = 0
    state["output_tokens"] = 0
    state["latency_ms"] = (time.perf_counter() - start) * 1000
    return state


def create_approved_event(participant_id: str, pending_row) -> str:
    """Called only from an approval path — app.main's /admin/pending/
    {id}/approve (researcher) or app.checkin's /checkin/{token}/pending/
    {id}/approve (the participant themselves). Actually books the event
    on that participant's real calendar. Returns the event's htmlLink."""
    service = get_calendar_service_for(participant_id)

    event_body = {
        "summary": f"Meeting re: {pending_row['subject'] or 'email request'}",
        "description": (
            f"Auto-proposed from an email, approved via the study.\n\n"
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
