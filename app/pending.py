"""Pending meeting records: the staging area between the calendar handler and
the Google Calendar API.

The calendar handler never writes to the calendar. It stages a record here,
keyed by a random confirmation token, and the only code path that inserts a
calendar event is confirm(), called from the operator's confirmation endpoint
(POST /pending/{token}/confirm in app/main.py).

Idempotency, so a repeated or concurrent confirmation cannot double-book:
  * confirm() takes SQLite's write lock (BEGIN IMMEDIATE) before reading the
    record, so two confirmations of the same token are serialised; the
    second sees status 'confirmed' and returns the stored event unchanged.
  * The calendar event id is derived from the token (event_id_for), so if
    the process dies after the API insert but before the record is updated,
    a retry inserts with the same id and the API rejects the duplicate.
    The caller's insert function treats that conflict as success
    (see app/handlers/calendar.py:insert_event).

The token is a secret held by the operator. It is never placed in the email
draft: that draft is a reply to the sender, and in the threat model the
sender may be the adversary.

SQLite is used so the poller and the FastAPI process, which run separately,
share one store. The file is gitignored (*.sqlite3).
"""
import hashlib
import secrets
import sqlite3
import time
from contextlib import closing
from typing import Callable, Optional

from app.config import PENDING_DB_PATH

STATUSES = ("pending", "confirmed", "cancelled")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_meetings (
    token        TEXT PRIMARY KEY,
    email_id     TEXT,
    sender       TEXT,
    subject      TEXT,
    body         TEXT,
    start_iso    TEXT NOT NULL,
    end_iso      TEXT NOT NULL,
    timezone     TEXT NOT NULL,
    time_source  TEXT NOT NULL,          -- 'parsed' or 'fallback'
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'confirmed', 'cancelled')),
    event_id     TEXT,
    event_link   TEXT,
    created_at   REAL NOT NULL,
    resolved_at  REAL
)
"""


class NotFound(KeyError):
    pass


class Conflict(RuntimeError):
    """The record is in a state that does not allow the requested action."""


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    # isolation_level=None: transactions are explicit (BEGIN IMMEDIATE below).
    conn = sqlite3.connect(db_path or PENDING_DB_PATH, isolation_level=None,
                           timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def event_id_for(token: str) -> str:
    """Deterministic Google Calendar event id for a token. Calendar ids must
    use base32hex characters (0-9, a-v); lowercase hex is a subset."""
    return hashlib.sha256(token.encode()).hexdigest()


def stage(*, email_id, sender, subject, body, start_iso, end_iso, timezone,
          time_source, db_path=None) -> str:
    """Create a pending record and return its confirmation token."""
    token = secrets.token_urlsafe(24)
    with closing(_connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO pending_meetings (token, email_id, sender, subject, body,"
            " start_iso, end_iso, timezone, time_source, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (token, email_id, sender, subject, body, start_iso, end_iso,
             timezone, time_source, time.time()))
    return token


def get(token: str, db_path=None) -> dict:
    with closing(_connect(db_path)) as conn:
        row = conn.execute("SELECT * FROM pending_meetings WHERE token = ?",
                           (token,)).fetchone()
    if row is None:
        raise NotFound(token)
    return dict(row)


def list_records(status: Optional[str] = "pending", db_path=None) -> list:
    with closing(_connect(db_path)) as conn:
        if status is None:
            rows = conn.execute(
                "SELECT * FROM pending_meetings ORDER BY created_at").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM pending_meetings WHERE status = ? ORDER BY created_at",
                (status,)).fetchall()
    return [dict(r) for r in rows]


def confirm(token: str, insert_fn: Callable[[dict, str], dict], db_path=None):
    """Commit a pending meeting to the calendar, at most once.

    insert_fn(record, event_id) performs the calendar write and returns the
    created (or already existing) event as a dict with 'id' and 'htmlLink'.

    Returns (record, already_confirmed). Raises NotFound, or Conflict if the
    record was cancelled.
    """
    with closing(_connect(db_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT * FROM pending_meetings WHERE token = ?",
                               (token,)).fetchone()
            if row is None:
                raise NotFound(token)
            record = dict(row)
            if record["status"] == "confirmed":
                conn.execute("COMMIT")
                return record, True
            if record["status"] == "cancelled":
                raise Conflict("meeting was cancelled; it cannot be confirmed")

            # Calendar write happens while holding the lock, so a concurrent
            # confirmation waits here rather than inserting a second event.
            event = insert_fn(record, event_id_for(token))
            now = time.time()
            conn.execute(
                "UPDATE pending_meetings SET status = 'confirmed', event_id = ?,"
                " event_link = ?, resolved_at = ? WHERE token = ?",
                (event.get("id"), event.get("htmlLink"), now, token))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    record.update(status="confirmed", event_id=event.get("id"),
                  event_link=event.get("htmlLink"), resolved_at=now)
    return record, False


def cancel(token: str, db_path=None):
    """Discard a pending meeting. Idempotent. Returns (record, already_cancelled).
    Raises NotFound, or Conflict if the meeting was already confirmed."""
    with closing(_connect(db_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute("SELECT * FROM pending_meetings WHERE token = ?",
                               (token,)).fetchone()
            if row is None:
                raise NotFound(token)
            record = dict(row)
            if record["status"] == "cancelled":
                conn.execute("COMMIT")
                return record, True
            if record["status"] == "confirmed":
                raise Conflict("meeting is already on the calendar; delete it there")
            now = time.time()
            conn.execute("UPDATE pending_meetings SET status = 'cancelled',"
                         " resolved_at = ? WHERE token = ?", (now, token))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    record.update(status="cancelled", resolved_at=now)
    return record, False
