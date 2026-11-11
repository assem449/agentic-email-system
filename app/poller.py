import time
import uuid
from app.gmail_client import (
    get_gmail_service,
    fetch_unread_emails,
    mark_as_read,
    create_draft_reply,
    move_to_spam,
)
from app.graph import build_graph

graph = build_graph()

def process_email(service, email: dict):
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
    })

    category = result["category"]
    response = result["response"]
    gmail_id = email["gmail_id"]

    print(f"[{category}] {email['subject'][:40]} -> {result['handler_used']}")

    if result.get("confirmation_token"):
        # Shown to the operator only. Nothing is on the calendar until this
        # token is confirmed: POST /pending/<token>/confirm (or GET /pending
        # to list everything awaiting a decision).
        print(f"  -> meeting proposal staged, awaiting confirmation: "
              f"token {result['confirmation_token']}")

    if category == "spam":
        move_to_spam(service, gmail_id)
        print(f"  -> moved to spam")
    else:
        draft = create_draft_reply(
            service, gmail_id, email["sender"], email["subject"], response
        )
        print(f"  -> draft created: {draft['id']}")

    mark_as_read(service, gmail_id)

def run_poller(interval_seconds=30):
    print(f"Starting poller — checking every {interval_seconds}s...")
    service = get_gmail_service()

    while True:
        try:
            emails = fetch_unread_emails(service, max_results=10)
            if emails:
                print(f"Found {len(emails)} unread email(s)")
                for email in emails:
                    process_email(service, email)
            else:
                print("No new emails.")
        except Exception as e:
            print(f"Error: {e}")

        time.sleep(interval_seconds)