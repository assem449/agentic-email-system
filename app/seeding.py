"""Seed scripted scenario emails directly into a participant's mailbox.

This is for the study's fixed, researcher-authored scenario set (see
research/eval_run.py's data/eval_set.json for the kind of content, or a
custom scenarios file) — not for organic mail. It uses the Gmail API's
`messages.insert`, which writes a message straight into the mailbox
(like IMAP APPEND) instead of sending it. Nothing is transported: no
SMTP hop, no delivery pipeline, and per Google's own docs it "bypasses
most scanning and classification" — there's no sender reputation, rate
limit, or spam-filter risk the way an actually-sent test email has,
because nothing is actually being sent. This is the fix for scenario
emails repeatedly landing in Spam when they were sent as real mail
between fresh accounts (see docs/NOTES.md and the conversation this
came out of).

Requires the gmail.insert scope (app/google_auth.py) — a participant
connected before that scope was added needs to reconnect once.
"""

import base64
from email.message import EmailMessage
from email.utils import formatdate
from typing import Dict, List, Optional

from app.google_auth import get_gmail_service_for


def _build_raw_message(sender: str, to: str, subject: str, body: str,
                       headers: Optional[Dict[str, str]] = None) -> str:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    # Extra headers let a scenario look like real bulk mail, e.g.
    # {"List-Unsubscribe": "<mailto:unsub@example.com>"}. messages.insert
    # skips Gmail's tab classification, so without these a seeded
    # newsletter carries none of the signals a real one would.
    for name, value in (headers or {}).items():
        msg[name] = value
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def seed_email(participant_id: str, participant_email: str, sender: str, subject: str, body: str,
               headers: Optional[Dict[str, str]] = None) -> str:
    """Inserts one scenario email, unread, straight into the inbox.
    Returns the new message's Gmail id (what app.gmail_client's poller
    will pick up next cycle, same as any other unread message)."""
    service = get_gmail_service_for(participant_id)
    raw = _build_raw_message(sender, participant_email, subject, body, headers)
    result = service.users().messages().insert(
        userId="me",
        body={"raw": raw, "labelIds": ["INBOX", "UNREAD"]},
    ).execute()
    return result["id"]


def seed_scenarios(participant_id: str, participant_email: str, scenarios: List[dict]) -> List[str]:
    """scenarios: [{"sender": "...", "subject": "...", "body": "...",
    "headers": {...} (optional)}, ...].
    Returns the inserted Gmail message ids, in order."""
    return [
        seed_email(
            participant_id,
            participant_email,
            # /admin/seed sends "sender": None when omitted, which
            # .get(key, default) would pass straight through.
            s.get("sender") or "study@example.com",
            s["subject"],
            s["body"],
            s.get("headers"),
        )
        for s in scenarios
    ]
