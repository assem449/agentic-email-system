"""Per-participant Google auth for the multi-tenant study deployment.

This is separate from the single-account `get_gmail_service()` in
gmail_client.py (which still does the old local desktop-app flow for
quick ad-hoc testing / test_gmail.py). Everything that touches a real
study participant's account goes through here instead: it loads that
participant's encrypted token from app.db, builds live Gmail/Calendar
services from it, and writes back a refreshed token when Google issues
one.
"""

from urllib.parse import quote

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app import db

# One combined scope set — a single OAuth consent covers both Gmail and
# Calendar, so each participant has exactly one stored token, not two.
#
# gmail.insert is for app/seeding.py: writing scenario emails straight
# into a mailbox (messages.insert) rather than actually sending them,
# so they never pass through delivery/spam filtering at all. A
# participant who connected before this scope was added needs to
# reconnect once (re-run /auth/start) before seeding will work for them
# — their stored token predates the grant.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.insert",
    "https://www.googleapis.com/auth/calendar",
]


class NotConnected(Exception):
    """Raised when a participant has no stored (active) token, or their
    refresh token has been revoked and they need to reconnect."""


def _load_credentials(participant_id: str) -> Credentials:
    token_info = db.get_participant_token(participant_id)
    if token_info is None:
        raise NotConnected(participant_id)

    creds = Credentials.from_authorized_user_info(token_info, SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            db.save_refreshed_token(participant_id, creds.to_json())
        else:
            raise NotConnected(participant_id)

    return creds


def get_gmail_service_for(participant_id: str):
    return build("gmail", "v1", credentials=_load_credentials(participant_id))


def get_calendar_service_for(participant_id: str):
    return build("calendar", "v3", credentials=_load_credentials(participant_id))


def account_chooser_url(email: str, continue_url: str) -> str:
    """Wraps any Google URL (a Gmail link, a Calendar event's htmlLink,
    anything) so it opens against a specific account rather than
    whatever Google treats as the browser's session-index-0 account.
    Without this, a participant also signed into their real account
    gets bounced there instead of the study account whenever a link
    like this is opened — same bug for Gmail deep links and Calendar
    event links, so this one helper covers both (and anything else
    Google-hosted later). Switches to `email` first if it's signed in
    in that browser, or prompts sign-in if it isn't, then continues to
    `continue_url`."""
    return (
        "https://accounts.google.com/AccountChooser"
        f"?Email={quote(email)}&continue={quote(continue_url, safe='')}"
    )
