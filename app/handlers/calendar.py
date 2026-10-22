import json
import re
import time
from datetime import datetime, timedelta
from email.utils import parseaddr
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser

from app.state import EmailState
from app.config import GOOGLE_CALENDAR_ID, LLM_MODEL, STUDY_TIMEZONE
from app import db
from app.google_auth import get_calendar_service_for
from app.handlers.llm import _client

# A meeting-classified email never books a real event by itself. It
# proposes one (a `pending_events` row) and a human approves or rejects it
# — the participant on their own check-in page, or a researcher on /admin
# — which calls create_approved_event() below. This module reads the
# calendar (freebusy) at classify time, to propose a slot that's actually
# free, and never calls calendar.insert() on the classify path.
#
# Two small LLM calls per meeting email: one reads the times the sender
# proposes (date parsers can't read "Wednesday after 2 or Thursday
# morning"), one writes the reply once the calendar has been checked. The
# availability check itself is plain code.

TZ = ZoneInfo(STUDY_TIMEZONE)

# Default scheduling preferences, the same for every participant: weekdays
# 9:00-18:00, 30-minute meetings. A length stated in the email is used
# instead, up to MAX_DURATION_MINUTES.
BUSINESS_START_HOUR = 9
BUSINESS_END_HOUR = 18
SLOT_MINUTES = 30
MEETING_DURATION_MINUTES = 30
MAX_DURATION_MINUTES = 60
SEARCH_WINDOW_DAYS = 7
MIN_LEAD = timedelta(hours=2)  # never propose a slot starting sooner than this

EXTRACT_PROMPT = """Today is {today}. Times are in the {tz} time zone. Read the email and list \
every meeting time the sender proposes, in the order they give them. Reply \
with JSON only, no other text:
{{"options": [{{"date": "YYYY-MM-DD", "start": "HH:MM", "end": "HH:MM" or null}}], \
"duration_minutes": number or null}}
- A specific time ("Thursday at 2 pm") has "end": null.
- A range has an end: "Wednesday after 2 pm" is 14:00-18:00, "Thursday \
morning" 09:00-12:00, "Friday afternoon" 13:00-18:00, "any time Monday" \
09:00-18:00.
- Resolve weekday names to the next such date on or after today.
- For a reschedule, list only the new times, not the old one.
- duration_minutes only if the email states a length ("15 minutes").
- No day or time proposed: "options": [].\
"""

REPLY_PROMPT = """You draft a reply to a meeting request for someone in a university \
community. A human reads the draft before it is sent. Greet the sender by \
name, follow the decision below exactly, mention the time exactly as \
written in it, and do not offer any other time. Keep it to a few friendly \
sentences and end with a sign-off and "[Your name]". Output only the email \
body.

Decision: {decision}\
"""


def _now() -> datetime:
    return datetime.now(TZ)


def _llm(system: str, user: str, max_tokens: int) -> tuple[str, int, int]:
    message = _client.messages.create(
        model=LLM_MODEL, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = next((b.text for b in message.content if b.type == "text"), "")
    return text.strip(), message.usage.input_tokens, message.usage.output_tokens


def _email_text(state: EmailState) -> str:
    name, addr = parseaddr(state.get("sender") or "")
    return f"From: {name or addr}\nSubject: {state['subject']}\n\n{state['body']}"


def parse_options(raw: str) -> tuple[list, int | None]:
    """The extraction call's JSON -> ([(start, end or None)], duration).
    Anything unreadable counts as "no time proposed", which then gets a
    proposal from the calendar instead of a guess."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        return [], None
    options = []
    for o in data.get("options") or []:
        try:
            day = datetime.strptime(o["date"], "%Y-%m-%d").date()
            start = datetime.combine(day, datetime.strptime(o["start"], "%H:%M").time(), TZ)
            end = (datetime.combine(day, datetime.strptime(o["end"], "%H:%M").time(), TZ)
                   if o.get("end") else None)
        except (KeyError, TypeError, ValueError):
            continue
        options.append((start, end))
    duration = data.get("duration_minutes")
    if not isinstance(duration, (int, float)) or duration <= 0:
        duration = None
    return options, int(duration) if duration else None


def _in_hours(start: datetime, end: datetime) -> bool:
    return (start.weekday() < 5 and start.date() == end.date()
            and start.hour >= BUSINESS_START_HOUR
            and (end.hour, end.minute) <= (BUSINESS_END_HOUR, 0))


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def _free(start, end, busy) -> bool:
    return not any(_overlaps(start, end, b_start, b_end) for b_start, b_end in busy)


def _round_up(dt: datetime) -> datetime:
    dt = dt.replace(second=0, microsecond=0)
    remainder = dt.minute % SLOT_MINUTES
    return dt + timedelta(minutes=SLOT_MINUTES - remainder) if remainder else dt


def _first_free(busy, start: datetime, limit: datetime, duration: timedelta):
    """First SLOT_MINUTES-aligned slot of `duration` within business hours,
    starting at or after `start` and ending by `limit`; None if none."""
    slot = _round_up(start)
    while slot + duration <= limit:
        if _in_hours(slot, slot + duration) and _free(slot, slot + duration, busy):
            return slot
        slot += timedelta(minutes=SLOT_MINUTES)
    return None


def choose_slot(busy, options, duration: timedelta, now: datetime):
    """Returns (decision, start): decision is "accepted" (one of the
    sender's times is free, the first that is, in their order), "busy"
    (they proposed times, none free: next free slot instead), "none"
    (no time proposed: next free slot), or "no_slot" (nothing free in the
    search window; start is None)."""
    earliest = now + MIN_LEAD
    for opt_start, opt_end in options:
        if opt_end is None:  # a specific time
            if (opt_start >= earliest and _in_hours(opt_start, opt_start + duration)
                    and _free(opt_start, opt_start + duration, busy)):
                return "accepted", opt_start
        else:  # a range: first free slot inside it
            slot = _first_free(busy, max(opt_start, earliest), opt_end, duration)
            if slot:
                return "accepted", slot
    slot = _first_free(busy, earliest, earliest + timedelta(days=SEARCH_WINDOW_DAYS), duration)
    if slot is None:
        return "no_slot", None
    return ("busy" if options else "none"), slot


def _busy_periods(service, start: datetime, end: datetime) -> list:
    resp = service.freebusy().query(body={
        "timeMin": start.isoformat(), "timeMax": end.isoformat(),
        "items": [{"id": GOOGLE_CALENDAR_ID}],
    }).execute()
    return [(dateparser.parse(b["start"]), dateparser.parse(b["end"]))
            for b in resp["calendars"][GOOGLE_CALENDAR_ID]["busy"]]


def _when(dt: datetime) -> str:
    return dt.strftime("%A, %B %d at %I:%M %p").replace(" 0", " ")


DECISIONS = {
    "accepted": "The time {when} works and is free. Accept it.",
    "busy": "The times the sender proposed are not available. Briefly say so and propose {when} instead.",
    "none": "The sender did not propose a time. Propose {when}.",
    "unavailable": "Availability could not be checked. Do not name any time; write "
                   "[CONFIRM: meeting time] where the time would go.",
}


def calendar_handler(state: EmailState) -> EmailState:
    """Classify-time node: reads the proposed times, checks the
    participant's real calendar, drafts a reply that accepts or proposes a
    time, and queues that time as a pending event for a human to approve.
    Never books anything itself — only create_approved_event() does."""
    start_clock = time.perf_counter()
    participant_id = state.get("participant_id")

    if not participant_id:
        # Account-free /route-email demo and eval runs: nothing to check.
        state["response"] = ("[demo mode, no account connected] Would read the proposed "
                             "times, check the calendar and draft a reply for human review; "
                             "no event created.")
        state["handler_used"] = "calendar_pending_review_demo"
        state["tokens_used"] = state["input_tokens"] = state["output_tokens"] = 0
        state["latency_ms"] = (time.perf_counter() - start_clock) * 1000
        return state

    now = _now()
    raw, in1, out1 = _llm(
        EXTRACT_PROMPT.format(today=now.strftime("%A, %B %d, %Y"), tz=STUDY_TIMEZONE),
        _email_text(state), max_tokens=300,
    )
    options, minutes = parse_options(raw)
    duration = timedelta(minutes=min(minutes or MEETING_DURATION_MINUTES, MAX_DURATION_MINUTES))

    try:
        service = get_calendar_service_for(participant_id)
        busy = _busy_periods(service, now, now + timedelta(days=SEARCH_WINDOW_DAYS + 1))
    except Exception:  # NotConnected, or any Calendar API failure
        busy = None
    if busy is None:
        decision, slot = "unavailable", None
    else:
        decision, slot = choose_slot(busy, options, duration, now)
        if decision == "no_slot":
            decision = "unavailable"

    if slot is not None:
        db.create_pending_event(
            participant_id=participant_id,
            gmail_id=state.get("gmail_id") or "",
            sender=state["sender"],
            subject=state["subject"],
            # A short preview only, not the full body — same reasoning as
            # the routing log.
            reply_preview=(state["body"] or "")[:300],
            proposed_start=slot.isoformat(),
            proposed_end=(slot + duration).isoformat(),
            time_adjusted=decision == "busy",
        )
        state["handler_used"] = "calendar_pending_review"
    else:
        state["handler_used"] = "calendar_unavailable"
        state["needs_review"] = True

    reply, in2, out2 = _llm(
        REPLY_PROMPT.format(decision=DECISIONS[decision].format(when=_when(slot) if slot else "")),
        _email_text(state), max_tokens=400,
    )
    state["meeting_decision"] = decision
    state["response"] = reply
    state["input_tokens"] = in1 + in2
    state["output_tokens"] = out1 + out2
    state["tokens_used"] = state["input_tokens"] + state["output_tokens"]
    state["latency_ms"] = (time.perf_counter() - start_clock) * 1000
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
        "start": {"dateTime": pending_row["proposed_start"], "timeZone": STUDY_TIMEZONE},
        "end": {"dateTime": pending_row["proposed_end"], "timeZone": STUDY_TIMEZONE},
    }

    created_event = service.events().insert(
        calendarId=GOOGLE_CALENDAR_ID,
        body=event_body,
    ).execute()

    return created_event.get("htmlLink", "")
