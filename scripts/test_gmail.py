"""Manual smoke test for the legacy single-account desktop OAuth flow
(credentials.json + token.json — see app/gmail_client.py). Not used by
the multi-participant study deployment (that's app/google_auth.py +
app/oauth_web.py instead).

Run from the repo root: python scripts/test_gmail.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.gmail_client import get_gmail_service, fetch_unread_emails

service = get_gmail_service()  # opens browser first time — log in with temp Gmail account
emails = fetch_unread_emails(service)

for e in emails:
    print(f"From: {e['sender']}")
    print(f"Subject: {e['subject']}")
    print(f"Body preview: {e['body'][:100]}")
    print("---")
