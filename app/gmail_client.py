import base64
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
]

GMAIL_CREDENTIALS_PATH = "credentials.json"  # same Cloud project as Calendar
GMAIL_TOKEN_PATH = "gmail_token.json"        # separate token for temp account

def get_gmail_service():
    creds = None
    token_path = Path(GMAIL_TOKEN_PATH)

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(GMAIL_TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(GMAIL_CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def fetch_unread_emails(service, max_results=10):
    """Returns list of dicts: {id, sender, subject, body}"""
    results = service.users().messages().list(
        userId="me", q="is:unread", maxResults=max_results
    ).execute()

    messages = results.get("messages", [])
    emails = []

    for msg_ref in messages:
        msg = service.users().messages().get(
            userId="me", id=msg_ref["id"], format="full"
        ).execute()

        headers = msg["payload"]["headers"]
        sender = next((h["value"] for h in headers if h["name"] == "From"), "")
        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")

        body = _extract_body(msg["payload"])

        emails.append({
            "gmail_id": msg["id"],
            "sender": sender,
            "subject": subject,
            "body": body,
        })

    return emails


def _extract_body(payload) -> str:
    """Pulls plain text body out of Gmail's nested payload structure."""
    if "parts" in payload:
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain":
                data = part["body"].get("data", "")
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
            if "parts" in part:  # nested multipart
                nested = _extract_body(part)
                if nested:
                    return nested
    else:
        data = payload["body"].get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    return ""


def mark_as_read(service, gmail_id: str):
    service.users().messages().modify(
        userId="me", id=gmail_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()


def create_draft_reply(service, gmail_id: str, sender: str, subject: str, reply_text: str):
    message_text = f"To: {sender}\nSubject: Re: {subject}\n\n{reply_text}"
    raw = base64.urlsafe_b64encode(message_text.encode()).decode()

    draft = service.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw}},
    ).execute()
    return draft


def move_to_spam(service, gmail_id: str):
    service.users().messages().modify(
        userId="me", id=gmail_id,
        body={"addLabelIds": ["SPAM"], "removeLabelIds": ["INBOX"]},
    ).execute()