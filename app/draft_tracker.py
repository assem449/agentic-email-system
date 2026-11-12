"""What participants did with each reply draft, for measuring review effort
without asking them anything.

About once an hour, for every reply draft created in the last TRACK_DAYS
days that is still unchanged or edited, it looks the draft up in Gmail:
  - still there, same text      -> unchanged
  - still there, text changed   -> edited  (with % of words changed)
  - gone, a sent reply in the thread after it -> sent (% changed vs. the draft)
  - gone, nothing sent          -> deleted
After TRACK_DAYS the last status is kept as final. Exception notes (drafts
addressed to the participant) are not tracked: they aren't replies.

Comparisons use the text without quoted history and sign-off
(email_text.clean_body), so Gmail adding "On ... wrote:" doesn't count as
an edit.
"""

import difflib
import re
import time
import traceback
from datetime import datetime, timedelta, timezone

from app import db
from app.email_text import clean_body
from app.gmail_client import _extract_body
from app.google_auth import NotConnected, get_gmail_service_for

TRACK_DAYS = 3
CHECK_INTERVAL_SECONDS = 3600
STATUS = {"last_run_at": None, "last_error": None}


def change_pct(original: str, current: str) -> float:
    """Share of words changed, 0 (identical) to 100 (fully rewritten)."""
    a = re.findall(r"\S+", clean_body(original or "")[0].lower())
    b = re.findall(r"\S+", clean_body(current or "")[0].lower())
    if not a and not b:
        return 0.0
    return round(100 * (1 - difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()), 1)


def _is_missing(error: Exception) -> bool:
    status = getattr(getattr(error, "resp", None), "status", None)
    return status in (404, 400) or "not found" in str(error).lower()


def _sent_after(service, thread_id: str, after_ms: int):
    """Body of the last message the participant sent in the thread after
    after_ms, or None."""
    if not thread_id:
        return None
    thread = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
    sent = [m for m in thread.get("messages", [])
            if "SENT" in m.get("labelIds", []) and "DRAFT" not in m.get("labelIds", [])
            and int(m.get("internalDate", 0)) >= after_ms]
    return _extract_body(sent[-1]["payload"]) if sent else None


def check_draft(service, event) -> tuple[str, float]:
    """(status, % changed) for one tracked draft."""
    try:
        draft = service.users().drafts().get(userId="me", id=event["draft_id"], format="full").execute()
    except Exception as e:
        if not _is_missing(e):
            raise
        created_ms = int(datetime.strptime(event["created_at"], "%Y-%m-%dT%H:%M:%SZ")
                         .replace(tzinfo=timezone.utc).timestamp() * 1000)
        sent_body = _sent_after(service, event["thread_id"], created_ms)
        if sent_body is None:
            return "deleted", None
        return "sent", change_pct(event["draft_text"], sent_body)
    pct = change_pct(event["draft_text"], _extract_body(draft["message"]["payload"]))
    return ("unchanged" if pct == 0 else "edited"), pct


def run_once() -> int:
    """Check every tracked draft once; returns how many were checked."""
    since = (datetime.now(timezone.utc) - timedelta(days=TRACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    checked = 0
    for participant_id in db.list_active_participant_ids():
        events = db.list_drafts_to_track(participant_id, since)
        if not events:
            continue
        try:
            service = get_gmail_service_for(participant_id)
        except NotConnected:
            continue
        for event in events:
            try:
                status, pct = check_draft(service, event)
                db.update_draft_status(event["id"], status, pct)
                checked += 1
            except Exception as e:
                print(f"[{participant_id}] draft check failed for {event['id']}: {e}")
    return checked


def run_draft_tracker(interval_seconds: int = CHECK_INTERVAL_SECONDS):
    while True:
        try:
            db.init_db()
            run_once()
            STATUS["last_error"] = None
        except Exception as e:
            STATUS["last_error"] = f"{type(e).__name__}: {e}\n" + "".join(
                traceback.format_tb(e.__traceback__)[-3:])
            print(f"draft tracker error: {STATUS['last_error']}")
        STATUS["last_run_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        time.sleep(interval_seconds)
