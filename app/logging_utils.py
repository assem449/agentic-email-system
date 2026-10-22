import json
import time
from pathlib import Path
from app.state import EmailState
from app import db

LOG_PATH = Path(__file__).parent.parent / "logs" / "routing_log.jsonl"
LOG_PATH.parent.mkdir(exist_ok=True)

def log_routing_decision(state: EmailState) -> EmailState:
    record = {
        "timestamp": time.time(),
        "participant_id": state.get("participant_id"),
        "email_id": state.get("email_id"),
        "category": state.get("category"),
        "handler_used": state.get("handler_used"),
        "tokens_used": state.get("tokens_used"),
        "latency_ms": state.get("latency_ms"),
        "reply_needed": state.get("reply_needed"),
        "needs_review": state.get("needs_review"),
        "bulk_reason": state.get("bulk_reason"),
        "classifier_category": state.get("classifier_category"),
        "response_preview": (state.get("response") or "")[:200],
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")

    # Also record to the study datastore, keyed by participant — this is
    # what backs the daily check-in page (app/checkin.py). Skipped for the
    # account-free /route-email demo path, where participant_id is None.
    participant_id = state.get("participant_id")
    if participant_id:
        db.record_email_event(
            participant_id=participant_id,
            gmail_id=state.get("gmail_id") or "",
            sender=state.get("sender") or "",
            subject=state.get("subject") or "",
            category=state.get("category") or "",
            handler_used=state.get("handler_used") or "",
            # For a note, its summary: that is what the check-in page shows.
            response_preview=(state.get("note_summary") or state.get("response") or "")[:200],
        )

    return state
