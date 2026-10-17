import base64
import re
from email.message import EmailMessage
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.email_text import (
    body_bulk_reason, bulk_reason, clean_body, headers_dict, html_to_text,
)

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


# Labels the agent applies. Emails are left UNREAD so the person still sees
# them; "AI/Processed" is what stops the poller from handling one twice.
LABEL_PROCESSED = "AI/Processed"
LABEL_ANNOUNCEMENT = "AI/Announcement"
LABEL_NO_REPLY = "AI/No reply needed"
LABEL_DRAFT_READY = "AI/Draft ready"
LABEL_NEEDS_REVIEW = "AI/Needs review"
AGENT_LABELS = [
    LABEL_PROCESSED, LABEL_ANNOUNCEMENT, LABEL_NO_REPLY,
    LABEL_DRAFT_READY, LABEL_NEEDS_REVIEW,
]

# Unread emails are left unread now, so the UNREAD list also returns ones
# already handled. They are skipped by label. Gmail lists newest first, so
# new mail is at the top; the page is larger than one poll's worth so a
# burst of new mail is not pushed off it by handled-but-unread emails.
LIST_PAGE_SIZE = 50


def ensure_labels(service) -> dict:
    """Create any missing agent labels; return {label name: label id}."""
    existing = service.users().labels().list(userId="me").execute().get("labels", [])
    ids = {lab["name"]: lab["id"] for lab in existing}
    for name in AGENT_LABELS:
        if name not in ids:
            created = service.users().labels().create(
                userId="me",
                body={
                    "name": name,
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            ).execute()
            ids[name] = created["id"]
    return ids


def add_labels(service, gmail_id: str, label_ids: list):
    service.users().messages().modify(
        userId="me", id=gmail_id, body={"addLabelIds": label_ids}
    ).execute()


def fetch_unread_emails(service, max_results=10, processed_label_id=None):
    """Returns up to max_results unread emails not yet labelled processed.

    Keys: gmail_id, thread_id, message_id, references, sender, reply_to,
    subject, body (cleaned), quoted_text, raw_body, bulk_reason.

    Filters by the UNREAD label directly rather than q="is:unread" --
    the q= search query runs against Gmail's search index, which lags
    behind for messages written via messages.insert (seeding) by
    anywhere from seconds to several minutes, even though the UNREAD
    label is applied and visible in the mailbox immediately. labelIds
    filters on label metadata directly, with no such delay. That is also
    why the processed label is checked here rather than excluded in a
    search query.
    """
    results = service.users().messages().list(
        userId="me", labelIds=["UNREAD"], maxResults=LIST_PAGE_SIZE
    ).execute()

    emails = []

    for msg_ref in results.get("messages", []):
        if len(emails) >= max_results:
            break

        # "minimal" returns labelIds without the body: cheap way to skip
        # emails handled on an earlier poll.
        if processed_label_id:
            meta = service.users().messages().get(
                userId="me", id=msg_ref["id"], format="minimal"
            ).execute()
            if processed_label_id in meta.get("labelIds", []):
                continue

        msg = service.users().messages().get(
            userId="me", id=msg_ref["id"], format="full"
        ).execute()

        label_ids = msg.get("labelIds", [])

        headers = headers_dict(msg["payload"])
        raw_body = _extract_body(msg["payload"])
        body, quoted = clean_body(raw_body)

        emails.append({
            "gmail_id": msg["id"],
            "thread_id": msg.get("threadId"),
            "message_id": headers.get("message-id", ""),
            "references": headers.get("references", ""),
            "sender": headers.get("from", ""),
            "reply_to": headers.get("reply-to", ""),
            "subject": headers.get("subject", ""),
            "body": body,
            "quoted_text": quoted,
            "raw_body": raw_body,
            "bulk_reason": bulk_reason(label_ids, headers) or body_bulk_reason(raw_body),
        })

    return emails


def _decode(part) -> str:
    data = part.get("body", {}).get("data", "")
    if not data:
        return ""
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")


def _find_part(payload, mime_type: str) -> str:
    if payload.get("mimeType") == mime_type:
        text = _decode(payload)
        if text:
            return text
    for part in payload.get("parts", []):
        if part.get("filename"):  # attachment, not the body
            continue
        text = _find_part(part, mime_type)
        if text:
            return text
    return ""


def _extract_body(payload) -> str:
    """Plain-text body; falls back to converting the HTML part.

    Many newsletters and some mail clients send HTML only. The previous
    version returned "" for those, so the classifier saw a subject line
    and nothing else.
    """
    text = _find_part(payload, "text/plain")
    if text.strip():
        return text
    raw_html = _find_part(payload, "text/html")
    if raw_html:
        return html_to_text(raw_html)
    if "parts" not in payload:  # single-part message with no mimeType match
        return _decode(payload)
    return ""


def create_draft_reply(service, email: dict, reply_text: str):
    """Create a draft in the original thread, addressed like a real reply."""
    subject = email["subject"] or ""
    if not re.match(r"(?i)^re:", subject.strip()):
        subject = f"Re: {subject}"

    msg = EmailMessage()
    msg["To"] = email.get("reply_to") or email["sender"]
    msg["Subject"] = subject
    if email.get("message_id"):
        msg["In-Reply-To"] = email["message_id"]
        msg["References"] = " ".join(
            x for x in (email.get("references"), email["message_id"]) if x
        )
    msg.set_content(reply_text)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    message = {"raw": raw}
    if email.get("thread_id"):
        message["threadId"] = email["thread_id"]

    return service.users().drafts().create(
        userId="me", body={"message": message}
    ).execute()


def move_to_spam(service, gmail_id: str):
    service.users().messages().modify(
        userId="me", id=gmail_id,
        body={"addLabelIds": ["SPAM"], "removeLabelIds": ["INBOX"]},
    ).execute()
