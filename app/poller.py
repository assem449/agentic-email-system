import threading
import time
import traceback
import uuid
from datetime import datetime, timezone

from app import db
from app.google_auth import NotConnected, get_gmail_service_for
from app.gmail_client import (
    ensure_labels,
    add_labels,
    fetch_unread_emails,
    create_draft_reply,
    move_to_spam,
    LABEL_PROCESSED,
    LABEL_ANNOUNCEMENT,
    LABEL_NO_REPLY,
    LABEL_DRAFT_READY,
    LABEL_NEEDS_REVIEW,
    LABEL_ACTION_NEEDED,
)
from app.graph import build_graph
from app.config import POLL_INTERVAL_SECONDS

graph = build_graph()

# What the last poll did, per participant, for GET /admin/poller-status.
# In memory only: it describes this process, and resets on restart.
STATUS = {"started_at": None, "last_poll_at": None, "last_loop_error": None, "participants": {}}

# The background loop and POST /admin/poll-now must never poll at the same
# time, or both could pick up the same unread email and draft it twice.
_poll_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _short_error(e: Exception) -> str:
    return f"{type(e).__name__}: {e}\n" + "".join(traceback.format_tb(e.__traceback__)[-3:])


# participant_id -> {label name: Gmail label id}. Label ids are stable, so
# they are looked up (and created if missing) once per participant.
_label_cache: dict = {}


def _labels_for(participant_id: str, service) -> dict:
    if participant_id not in _label_cache:
        _label_cache[participant_id] = ensure_labels(service)
    return _label_cache[participant_id]


def process_email(service, labels: dict, email: dict, participant_id: str):
    result = graph.invoke({
        "email_id": str(uuid.uuid4()),
        "sender": email["sender"],
        "subject": email["subject"],
        "body": email["body"],
        "quoted_text": email["quoted_text"],
        "bulk_reason": email["bulk_reason"],
        "auth_verdict": email.get("auth_verdict"),
        "category": None,
        "handler_used": None,
        "response": None,
        "tokens_used": None,
        "latency_ms": None,
        "participant_id": participant_id,
        "gmail_id": email["gmail_id"],
    })

    gmail_id = email["gmail_id"]

    print(f"[{participant_id}] [{result['category']}] {email['subject'][:40]} -> {result['handler_used']}")

    spam, draft, names = gmail_actions(result)
    if spam:
        move_to_spam(service, gmail_id)
    if draft:
        # A meeting-classified email lands here too: the calendar node
        # never books anything itself, it only queued a pending proposal
        # (see app/handlers/calendar.py) that a human approves separately.
        # The draft reply is still created immediately — a Gmail draft is
        # already a human-in-the-loop step, since nothing sends until the
        # participant (or a study reviewer) opens and sends it themselves.
        create_draft_reply(service, email, result["response"])
    add_labels(service, gmail_id, [labels[n] for n in names])


# Label for each no-reply category; any other no-reply email gets
# AI/No reply needed.
NO_REPLY_LABELS = {
    "admin_action": LABEL_ACTION_NEEDED,
    "announcement_promo": LABEL_ANNOUNCEMENT,
}


def gmail_actions(result: dict) -> tuple[bool, bool, list]:
    """What to do in Gmail for a graph result: (move to Spam?, create a
    draft?, label names to add).

    Emails are deliberately left UNREAD: the participant still needs to
    see an announcement or check a draft. AI/Processed is always added; it
    is what keeps the poller from handling the same email again.
    """
    names = [LABEL_PROCESSED]
    if result["handler_used"] == "blocked":
        return True, False, names
    if result.get("suspicious"):
        return False, False, names + [LABEL_NEEDS_REVIEW]
    if not result.get("reply_needed"):
        return False, False, names + [NO_REPLY_LABELS.get(result["category"], LABEL_NO_REPLY)]
    names.append(LABEL_DRAFT_READY)
    if result.get("needs_review"):
        names.append(LABEL_NEEDS_REVIEW)
    return False, True, names


def poll_once() -> dict:
    """One pass over every connected, active participant. Each
    participant's failure (revoked token, API hiccup) is isolated so it
    doesn't take down the rest of the study. Returns STATUS."""
    with _poll_lock:
        for participant_id in db.list_active_participant_ids():
            st = STATUS["participants"].setdefault(
                participant_id, {"processed_total": 0}
            )
            st["last_poll_at"] = _now()
            st["last_error"] = None
            st["found_last_poll"] = 0

            try:
                service = get_gmail_service_for(participant_id)
            except NotConnected:
                st["last_error"] = "token invalid/revoked — reconnect via /auth/start"
                print(f"[{participant_id}] token invalid/revoked — skipping until they reconnect")
                continue
            except Exception as e:
                # Anything else (network, Google outage) must not stop the
                # remaining participants from being polled.
                st["last_error"] = _short_error(e)
                print(f"[{participant_id}] error connecting: {st['last_error']}")
                continue

            try:
                labels = _labels_for(participant_id, service)
                emails = fetch_unread_emails(
                    service, max_results=10,
                    processed_label_id=labels[LABEL_PROCESSED],
                )
            except Exception as e:
                st["last_error"] = _short_error(e)
                print(f"[{participant_id}] error: {st['last_error']}")
                continue

            st["found_last_poll"] = len(emails)
            for email in emails:
                try:
                    process_email(service, labels, email, participant_id)
                    st["processed_total"] += 1
                except Exception as e:
                    # One bad email must not block the rest of the batch.
                    st["last_error"] = f"on '{email['subject'][:40]}': " + _short_error(e)
                    print(f"[{participant_id}] error {st['last_error']}")

        STATUS["last_poll_at"] = _now()
    return STATUS


def run_poller(interval_seconds: int = POLL_INTERVAL_SECONDS):
    print(f"Starting multi-participant poller — checking every {interval_seconds}s...")
    STATUS["started_at"] = _now()
    while True:
        # Anything escaping poll_once (e.g. a database error listing
        # participants) used to end this thread for good, silently, while
        # the web app kept serving. Log it and try again next interval.
        try:
            db.init_db()
            poll_once()
            STATUS["last_loop_error"] = None
        except Exception as e:
            STATUS["last_loop_error"] = _short_error(e)
            print(f"poller loop error: {STATUS['last_loop_error']}")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    run_poller()
