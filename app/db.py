"""Study datastore: encrypted OAuth tokens + pending calendar proposals.

This is the one persistent store this deployment has, and it's
deliberately narrow: credentials (encrypted) and small metadata about
proposed meetings, never the emails themselves. See docs/NOTES.md.
"""

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from app.config import DB_PATH
from app.crypto import decrypt, encrypt

_SCHEMA = """
CREATE TABLE IF NOT EXISTS participants (
    id TEXT PRIMARY KEY,
    email TEXT,
    token_enc BLOB NOT NULL,
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
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    decided_at TEXT,
    calendar_event_link TEXT,
    FOREIGN KEY (participant_id) REFERENCES participants(id)
);
"""


@contextmanager
def _conn():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _conn():
        pass


# --- participants ---------------------------------------------------------

def upsert_participant(participant_id: str, email: str, token_json: str) -> None:
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO participants (id, email, token_enc, connected_at, active)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(id) DO UPDATE SET
                email = excluded.email,
                token_enc = excluded.token_enc,
                active = 1
            """,
            (participant_id, email, encrypt(token_json), _now()),
        )


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
        conn.execute("DELETE FROM participants WHERE id = ?", (participant_id,))


# --- pending calendar proposals -------------------------------------------

def create_pending_event(
    participant_id: str,
    gmail_id: str,
    sender: str,
    subject: str,
    reply_preview: str,
    proposed_start: str,
    proposed_end: str,
) -> str:
    event_id = str(uuid.uuid4())
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO pending_events
                (id, participant_id, gmail_id, sender, subject, reply_preview,
                 proposed_start, proposed_end, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                event_id, participant_id, gmail_id, sender, subject,
                reply_preview, proposed_start, proposed_end, _now(),
            ),
        )
    return event_id


def list_pending_events(status: str = "pending") -> list[sqlite3.Row]:
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM pending_events WHERE status = ? ORDER BY created_at ASC",
            (status,),
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


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
