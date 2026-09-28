"""Web OAuth flow for enrolling a study participant's sandbox account.

Replaces the desktop `InstalledAppFlow.run_local_server()` pattern (which
only works when the app runs on the same machine as the browser) with the
standard redirect flow a deployed server needs: /auth/start sends the
participant to Google, /auth/callback receives the code back and stores
their token.
"""

import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow

from app import db
from app.config import GOOGLE_OAUTH_CLIENT_SECRETS_PATH, OAUTH_REDIRECT_URI
from app.google_auth import SCOPES

router = APIRouter()


def _flow() -> Flow:
    return Flow.from_client_secrets_file(
        GOOGLE_OAUTH_CLIENT_SECRETS_PATH,
        scopes=SCOPES,
        redirect_uri=OAUTH_REDIRECT_URI,
    )


@router.get("/auth/start")
def auth_start(participant_id: str | None = None):
    """Landing link participants click. A fresh participant_id is minted
    if none is supplied, so `/auth/start` alone is a usable enrollment
    link for the study."""
    participant_id = participant_id or str(uuid.uuid4())

    flow = _flow()
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # force a refresh_token every time, for a study
        state=participant_id,
    )
    return RedirectResponse(authorization_url)


@router.get("/auth/callback")
def auth_callback(code: str, state: str):
    participant_id = state

    flow = _flow()
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise HTTPException(400, f"Google sign-in failed: {e}")

    creds = flow.credentials

    # Confirm the token works and learn the account's address, purely so
    # the admin review page can show something more useful than a uuid.
    email = "(unknown)"
    try:
        gmail = build_gmail_from_creds(creds)
        email = gmail.users().getProfile(userId="me").execute().get("emailAddress", email)
    except Exception:
        pass

    db.upsert_participant(participant_id, email, creds.to_json())

    return HTMLResponse(
        f"""
        <html><body style="font-family: sans-serif; padding: 48px; max-width: 480px;">
        <h2>Connected</h2>
        <p>{email} is now enrolled in the study.</p>
        <p>You can close this tab.</p>
        </body></html>
        """
    )


def build_gmail_from_creds(creds):
    from googleapiclient.discovery import build
    return build("gmail", "v1", credentials=creds)


@router.post("/auth/disconnect")
def disconnect(participant_id: str):
    """Revoke local access and delete this participant's stored data —
    the consent screen promises this is available on request."""
    db.delete_participant_data(participant_id)
    return {"status": "disconnected", "participant_id": participant_id}
