"""Study datastore: encrypted OAuth tokens + pending calendar proposals.

This is the one persistent store this deployment has, and it's
deliberately narrow: credentials (encrypted) and small metadata about
proposed meetings, never the emails themselves. See docs/NOTES.md.
"""

import json
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from app.config import DB_PATH
from app.crypto import decrypt, encrypt

_SCHEMA = """
CREATE TABLE IF NOT EXISTS participants (
    id TEXT PRIMARY KEY,
    email TEXT,
    token_enc BLOB NOT NULL,
    checkin_token TEXT,
    welcomed_at TEXT,
    connected_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS pending_events (
    id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL,
    gmail_id TEXT,
    sender TEXT,
    subject TEXT,
    reply_preview TEXT,
    proposed_start TEXT NOT NULL,
    proposed_end TEXT NOT NULL,
    time_adjusted INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    decided_at TEXT,
    calendar_event_link TEXT,
    FOREIGN KEY (participant_id) REFERENCES participants(id)
);

-- One row per email the pipeline actually processed for a participant.
-- Backs the daily check-in page (app/checkin.py): "what did I get today
-- and how was it handled." Short preview only, same policy as
-- pending_events and logging_utils.py — never the full email body.
CREATE TABLE IF NOT EXISTS email_events (
    id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL,
    gmail_id TEXT,
    sender TEXT,
    subject TEXT,
    category TEXT,
    handler_used TEXT,
    response_preview TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (participant_id) REFERENCES participants(id)
);

-- One row per participant per study-day they submitted feedback for.
-- per_email_json: [{"email_event_id": "...", "correct": true|false}, ...]
CREATE TABLE IF NOT EXISTS checkin_submissions (
    participant_id TEXT NOT NULL,
    day_number INTEGER NOT NULL,
    overall_rating INTEGER,
    notes TEXT,
    per_email_json TEXT,
    submitted_at TEXT NOT NULL,
    PRIMARY KEY (participant_id, day_number),
    FOREIGN KEY (participant_id) REFERENCES participants(id)
);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive, idempotent fixes for a study.db created before a given
    column/table existed. CREATE TABLE IF NOT EXISTS (in _SCHEMA) handles
    brand-new tables fine; it does nothing for a column added to a table
    that already exists, which is what this covers. Runs after _SCHEMA's
    CREATE TABLEs and before the unique index below, since the index
    needs the column to actually exist first — on a fresh db _SCHEMA
    already created it, on an old db this ALTER just added it."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(participants)")}
    if "checkin_token" not in cols:
        conn.execute("ALTER TABLE participants ADD COLUMN checkin_token TEXT")
    if "welcomed_at" not in cols:
        conn.execute("ALTER TABLE participants ADD COLUMN welcomed_at TEXT")

    pending_cols = {row["name"] for row in conn.execute("PRAGMA table_info(pending_events)")}
    if "time_adjusted" not in pending_cols:
        conn.execute(
            "ALTER TABLE pending_events ADD COLUMN time_adjusted INTEGER NOT NULL DEFAULT 0"
        )

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_participants_checkin_token "
        "ON participants(checkin_token)"
    )


@contextmanager
def _conn():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _conn():
        pass


# --- participants ---------------------------------------------------------

def upsert_participant(participant_id: str, email: str, token_json: str) -> str:
    """Returns the participant's check-in token (unchanged across
    reconnects — minted once on first connect)."""
    token = secrets.token_urlsafe(24)
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO participants (id, email, token_enc, checkin_token, connected_at, active)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(id) DO UPDATE SET
                email = excluded.email,
                token_enc = excluded.token_enc,
                checkin_token = COALESCE(participants.checkin_token, excluded.checkin_token),
                active = 1
            """,
            (participant_id, email, encrypt(token_json), token, _now()),
        )
        row = conn.execute(
            "SELECT checkin_token FROM participants WHERE id = ?", (participant_id,)
        ).fetchone()
    return row["checkin_token"]


def get_participant_token(participant_id: str) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT token_enc FROM participants WHERE id = ? AND active = 1",
            (participant_id,),
        ).fetchone()
    if row is None:
        return None
    return json.loads(decrypt(row["token_enc"]))


def save_refreshed_token(participant_id: str, token_json: str) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE participants SET token_enc = ? WHERE id = ?",
            (encrypt(token_json), participant_id),
        )


def list_active_participant_ids() -> list[str]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id FROM participants WHERE active = 1"
        ).fetchall()
    return [r["id"] for r in rows]


def deactivate_participant(participant_id: str) -> None:
    """Disconnect + stop polling. Does not delete history rows — call
    delete_participant_data for a full erase-on-request."""
    with _conn() as conn:
        conn.execute(
            "UPDATE participants SET active = 0 WHERE id = ?", (participant_id,)
        )


def delete_participant_data(participant_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM pending_events WHERE participant_id = ?", (participant_id,))
        conn.execute("DELETE FROM email_events WHERE participant_id = ?", (participant_id,))
        conn.execute("DELETE FROM checkin_submissions WHERE participant_id = ?", (participant_id,))
        conn.execute("DELETE FROM participants WHERE id = ?", (participant_id,))


def get_participant(participant_id: str) -> Optional[sqlite3.Row]:
    with _conn() as conn:
        return conn.execute(
            "SELECT id, email, checkin_token, welcomed_at, connected_at FROM participants WHERE id = ? AND active = 1",
            (participant_id,),
        ).fetchone()


def get_participant_by_checkin_token(token: str) -> Optional[sqlite3.Row]:
    with _conn() as conn:
        return conn.execute(
            "SELECT id, email, checkin_token, welcomed_at, connected_at FROM participants WHERE checkin_token = ? AND active = 1",
            (token,),
        ).fetchone()


def mark_welcomed(participant_id: str) -> None:
    """Records that this participant has seen the first-day welcome
    screen, so GET /checkin/{token} stops auto-showing it (they can
    still reopen it on demand from the small 'About this study' link)."""
    with _conn() as conn:
        conn.execute(
            "UPDATE participants SET welcomed_at = ? WHERE id = ?", (_now(), participant_id)
        )


# --- pending calendar proposals -------------------------------------------

def create_pending_event(
    participant_id: str,
    gmail_id: str,
    sender: str,
    subject: str,
    reply_preview: str,
    proposed_start: str,
    proposed_end: str,
    time_adjusted: bool = False,
) -> str:
    event_id = str(uuid.uuid4())
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO pending_events
                (id, participant_id, gmail_id, sender, subject, reply_preview,
                 proposed_start, proposed_end, time_adjusted, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                event_id, participant_id, gmail_id, sender, subject,
                reply_preview, proposed_start, proposed_end, int(time_adjusted), _now(),
            ),
        )
    return event_id


def list_pending_events(status: str = "pending") -> list[sqlite3.Row]:
    """All participants' proposals — backs the researcher /admin page."""
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM pending_events WHERE status = ? ORDER BY created_at ASC",
            (status,),
        ).fetchall()


def list_pending_events_for_participant(participant_id: str, status: str = "pending") -> list[sqlite3.Row]:
    """One participant's own proposals — backs the check-in page's
    self-approve section. Scoped so a participant can only ever see and
    act on their own meeting proposals."""
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM pending_events WHERE participant_id = ? AND status = ? ORDER BY created_at ASC",
            (participant_id, status),
        ).fetchall()


def get_pending_event(event_id: str) -> Optional[sqlite3.Row]:
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM pending_events WHERE id = ?", (event_id,)
        ).fetchone()


def decide_pending_event(event_id: str, status: str, calendar_event_link: Optional[str] = None) -> None:
    with _conn() as conn:
        conn.execute(
            """
            UPDATE pending_events
            SET status = ?, decided_at = ?, calendar_event_link = ?
            WHERE id = ?
            """,
            (status, _now(), calendar_event_link, event_id),
        )


# --- daily check-in --------------------------------------------------------

def record_email_event(
    participant_id: str,
    gmail_id: str,
    sender: str,
    subject: str,
    category: str,
    handler_used: str,
    response_preview: str,
) -> None:
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO email_events
                (id, participant_id, gmail_id, sender, subject, category,
                 handler_used, response_preview, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()), participant_id, gmail_id, sender, subject,
                category, handler_used, response_preview, _now(),
            ),
        )


def _today_utc() -> date:
    # connected_at / created_at are stored in UTC (_now(), below), so
    # "today" has to be computed in UTC too — date.today() uses the
    # server's local time, which can disagree with UTC by a day near
    # midnight and silently shift the reported study day by one.
    return datetime.now(timezone.utc).date()


def day_number_for(participant_id: str) -> Optional[int]:
    """1-indexed study day, based on calendar days since this
    participant connected. None if they're not an active participant."""
    p = get_participant(participant_id)
    if p is None:
        return None
    connected_date = date.fromisoformat(p["connected_at"][:10])
    return (_today_utc() - connected_date).days + 1


def list_events_for_today(participant_id: str) -> list[sqlite3.Row]:
    today = _today_utc().isoformat()
    with _conn() as conn:
        return conn.execute(
            """
            SELECT * FROM email_events
            WHERE participant_id = ? AND date(created_at) = ?
            ORDER BY created_at ASC
            """,
            (participant_id, today),
        ).fetchall()


def save_checkin_submission(
    participant_id: str,
    day_number: int,
    overall_rating: Optional[int],
    notes: str,
    per_email: list,
) -> None:
    """per_email: [{"email_event_id": ..., "correct": bool}, ...].
    Re-submitting the same day overwrites the earlier submission."""
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO checkin_submissions
                (participant_id, day_number, overall_rating, notes, per_email_json, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(participant_id, day_number) DO UPDATE SET
                overall_rating = excluded.overall_rating,
                notes = excluded.notes,
                per_email_json = excluded.per_email_json,
                submitted_at = excluded.submitted_at
            """,
            (participant_id, day_number, overall_rating, notes, json.dumps(per_email), _now()),
        )


def get_checkin_submission(participant_id: str, day_number: int) -> Optional[sqlite3.Row]:
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM checkin_submissions WHERE participant_id = ? AND day_number = ?",
            (participant_id, day_number),
        ).fetchone()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
