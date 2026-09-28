import time
import uuid

from app import db
from app.google_auth import NotConnected, get_gmail_service_for
from app.gmail_client import fetch_unread_emails, mark_as_read, create_draft_reply, move_to_spam
from app.graph import build_graph
from app.config import POLL_INTERVAL_SECONDS

graph = build_graph()


def process_email(service, email: dict, participant_id: str):
    result = graph.invoke({
        "email_id": str(uuid.uuid4()),
        "sender": email["sender"],
        "subject": email["subject"],
        "body": email["body"],
        "category": None,
        "handler_used": None,
        "response": None,
        "tokens_used": None,
        "latency_ms": None,
        "participant_id": participant_id,
        "gmail_id": email["gmail_id"],
    })

    category = result["category"]
    response = result["response"]
    gmail_id = email["gmail_id"]

    print(f"[{participant_id}] [{category}] {email['subject'][:40]} -> {result['handler_used']}")

    if category == "spam":
        move_to_spam(service, gmail_id)
    else:
        # A meeting-classified email lands here too: the calendar node
        # never books anything itself, it only queued a pending proposal
        # (see app/handlers/calendar.py) that a human approves separately.
        # The draft reply is still created immediately — a Gmail draft is
        # already a human-in-the-loop step, since nothing sends until the
        # participant (or a study reviewer) opens and sends it themselves.
        create_draft_reply(
            service, gmail_id, email["sender"], email["subject"], response
        )

    mark_as_read(service, gmail_id)


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
            emails = fetch_unread_emails(service, max_results=10)
            for email in emails:
                process_email(service, email, participant_id)
        except Exception as e:
            print(f"[{participant_id}] error: {e}")


def run_poller(interval_seconds: int = POLL_INTERVAL_SECONDS):
    print(f"Starting multi-participant poller — checking every {interval_seconds}s...")
    db.init_db()
    while True:
        poll_once()
        time.sleep(interval_seconds)


if __name__ == "__main__":
    run_poller()
