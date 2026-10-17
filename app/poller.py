import time
import uuid

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
)
from app.graph import build_graph
from app.config import POLL_INTERVAL_SECONDS

graph = build_graph()

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
        "category": None,
        "handler_used": None,
        "response": None,
        "tokens_used": None,
        "latency_ms": None,
        "participant_id": participant_id,
        "gmail_id": email["gmail_id"],
    })

    category = result["category"]
    gmail_id = email["gmail_id"]

    print(f"[{participant_id}] [{category}] {email['subject'][:40]} -> {result['handler_used']}")

    # Emails are deliberately left UNREAD: the participant still needs to
    # see an announcement or check a draft. The AI/Processed label is what
    # keeps the poller from handling the same email again.
    to_add = [labels[LABEL_PROCESSED]]

    if category == "spam":
        move_to_spam(service, gmail_id)
    elif not result.get("reply_needed"):
        if category == "announcement_promo":
            to_add.append(labels[LABEL_ANNOUNCEMENT])
        else:
            to_add.append(labels[LABEL_NO_REPLY])
    else:
        # A meeting-classified email lands here too: the calendar node
        # never books anything itself, it only queued a pending proposal
        # (see app/handlers/calendar.py) that a human approves separately.
        # The draft reply is still created immediately — a Gmail draft is
        # already a human-in-the-loop step, since nothing sends until the
        # participant (or a study reviewer) opens and sends it themselves.
        create_draft_reply(service, email, result["response"])
        to_add.append(labels[LABEL_DRAFT_READY])
        if result.get("needs_review"):
            to_add.append(labels[LABEL_NEEDS_REVIEW])

    add_labels(service, gmail_id, to_add)


def poll_once() -> None:
    """One pass over every connected, active participant. Each
    participant's failure (revoked token, API hiccup) is isolated so it
    doesn't take down the rest of the study."""
    for participant_id in db.list_active_participant_ids():
        try:
            service = get_gmail_service_for(participant_id)
        except NotConnected:
            print(f"[{participant_id}] token invalid/revoked — skipping until they reconnect")
            continue

        try:
            labels = _labels_for(participant_id, service)
            emails = fetch_unread_emails(
                service, max_results=10,
                processed_label_id=labels[LABEL_PROCESSED],
            )
        except Exception as e:
            print(f"[{participant_id}] error: {e}")
            continue

        for email in emails:
            try:
                process_email(service, labels, email, participant_id)
            except Exception as e:
                # One bad email must not block the rest of the batch.
                print(f"[{participant_id}] error on '{email['subject'][:40]}': {e}")


def run_poller(interval_seconds: int = POLL_INTERVAL_SECONDS):
    print(f"Starting multi-participant poller — checking every {interval_seconds}s...")
    db.init_db()
    while True:
        poll_once()
        time.sleep(interval_seconds)


if __name__ == "__main__":
    run_poller()
