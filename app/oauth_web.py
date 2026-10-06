"""Web OAuth flow for enrolling a study participant's sandbox account.

Replaces the desktop `InstalledAppFlow.run_local_server()` pattern (which
only works when the app runs on the same machine as the browser) with the
standard redirect flow a deployed server needs: /auth/start sends the
participant to Google, /auth/callback receives the code back and stores
their token.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow

from app import db
from app.config import GOOGLE_OAUTH_CLIENT_SECRETS_PATH, OAUTH_REDIRECT_URI
from app.google_auth import SCOPES, account_chooser_url


def _google_link(email: str, continue_fragment: str) -> str:
    """A Gmail link targeted at a specific account. See
    account_chooser_url (app.google_auth) for why this wrapping exists
    at all — used for Gmail URLs specifically here."""
    return account_chooser_url(email, f"https://mail.google.com/mail/u/0/{continue_fragment}")

router = APIRouter()


def _flow() -> Flow:
    # PKCE off: /auth/start and /auth/callback are separate HTTP requests,
    # each building its own Flow object, so a PKCE code_verifier generated
    # during /auth/start can't survive to /auth/callback's token exchange
    # ("Missing code verifier" from Google otherwise). Safe to skip here —
    # this is a confidential "Web application" client (has a client
    # secret), which is what actually authenticates the token exchange;
    # PKCE exists for public clients that can't hold a secret.
    return Flow.from_client_secrets_file(
        GOOGLE_OAUTH_CLIENT_SECRETS_PATH,
        scopes=SCOPES,
        redirect_uri=OAUTH_REDIRECT_URI,
        autogenerate_code_verifier=False,
    )


@router.get("/auth/start")
def auth_start(participant_id: Optional[str] = None):
    """Landing link participants click. The participant's real identity
    is always the connected Google account's email address (set in
    /auth/callback once we know it) -- not anything passed here.
    `participant_id`, if given, is just carried through as the OAuth
    `state` value; it has no effect on which participant row gets
    created or updated. Omit it entirely and this still works."""
    state = participant_id or str(uuid.uuid4())

    flow = _flow()
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # force a refresh_token every time, for a study
        state=state,
    )
    return RedirectResponse(authorization_url)


@router.get("/auth/callback")
def auth_callback(request: Request, code: str, state: str):
    flow = _flow()
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise HTTPException(400, f"Google sign-in failed: {e}")

    creds = flow.credentials

    # The participant's id is always the connected account's own email
    # (lowercased) -- not whatever was passed to /auth/start -- so the
    # same Google account always maps to the same participant row no
    # matter what, if anything, was in the enrollment link. Only falls
    # back to the /auth/start state value if Google's profile lookup
    # itself fails, so a participant row still gets created either way.
    email = None
    try:
        gmail = build_gmail_from_creds(creds)
        email = gmail.users().getProfile(userId="me").execute().get("emailAddress")
    except Exception:
        pass
    participant_id = email.lower() if email else state
    email = email or "(unknown)"

    checkin_token = db.upsert_participant(participant_id, email, creds.to_json())
    checkin_url = str(request.base_url).rstrip("/") + f"/checkin/{checkin_token}"

    return HTMLResponse(f"""
<!doctype html>
<html><head><meta charset="utf-8"><title>Connected</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  *{{box-sizing:border-box;}}
  body{{
    margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
    font-family:'Open Sans',-apple-system,system-ui,sans-serif;
    background:#EDEBE3; color:#1A1A18; padding:24px;
  }}
  .card{{
    background:#fff; width:100%; max-width:420px; border-radius:20px;
    box-shadow:0 24px 60px rgba(20,20,19,0.16), 0 2px 8px rgba(20,20,19,0.06);
    padding:36px 32px 32px; position:relative;
    animation:popIn .45s cubic-bezier(.16,1,.3,1) .1s both;
  }}
  @keyframes popIn{{from{{opacity:0; transform:scale(.94) translateY(12px);}} to{{opacity:1; transform:scale(1) translateY(0);}}}}
  .close{{
    position:absolute; top:16px; right:16px; width:28px; height:28px; border-radius:50%;
    background:#F4F2EC; border:none; display:flex; align-items:center; justify-content:center;
    cursor:pointer; color:#8a887f; text-decoration:none; font-size:15px; transition:background .2s ease;
  }}
  .close:hover{{background:#EAE7DD;}}
  .check{{width:44px; height:44px; border-radius:50%; background:#E9F5EC; display:flex; align-items:center; justify-content:center; margin-bottom:16px;}}
  h2{{margin:0 0 6px; font-size:21px; font-weight:600;}}
  p{{margin:0 0 4px; font-size:14px; color:#57544C; line-height:1.55;}}
  .go-btn{{
    display:inline-flex; align-items:center; gap:8px; background:#2F6FED; color:#fff;
    text-decoration:none; font-size:14px; font-weight:600; padding:12px 20px; border-radius:10px;
    margin-top:16px; transition:background .2s ease;
  }}
  .go-btn:hover{{background:#2558BE;}}
  .foot{{font-size:12.5px; color:#a6a39a; margin-top:14px; line-height:1.5;}}
</style>
</head>
<body>
  <div class="card">
    <a class="close" href="{_google_link(email, '#inbox')}" title="Back to inbox">&times;</a>
    <div class="check">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M4 12l5 5L20 6" stroke="#2E7D46" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </div>
    <h2>You're connected</h2>
    <p>{email} is now enrolled in the study.</p>
    <p>This is your personal daily check-in page for the rest of the study.</p>
    <a class="go-btn" href="{checkin_url}">Open your check-in page →</a>
    <div class="foot">Bookmark this page once it opens, you'll use it every day.</div>
  </div>
</body></html>
""")


def build_gmail_from_creds(creds):
    from googleapiclient.discovery import build
    return build("gmail", "v1", credentials=creds)


@router.post("/auth/disconnect")
def disconnect(participant_id: str):
    """Revoke local access and delete this participant's stored data —
    the consent screen promises this is available on request."""
    db.delete_participant_data(participant_id)
    return {"status": "disconnected", "participant_id": participant_id}
