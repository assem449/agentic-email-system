"""Seed a fixed set of scenario emails directly into a participant's
mailbox — see app/seeding.py for why this is spam-filter-proof (no
delivery happens at all, so there's nothing for a spam filter to act
on), unlike actually sending test emails.

Usage:
    python scripts/seed_participant.py <participant_id> <scenarios.json>

scenarios.json: a list of objects, each
    {"sender": "Alex Chen <alex@example.com>", "subject": "...", "body": "..."}
"sender" is optional (defaults to a generic placeholder) — it's just
the From header shown in the mailbox, nothing is actually delivered to
or from it.

data/eval_set.json is close to this shape already (subject/body) but
has no "sender" field and isn't meant to be seeded wholesale (it's the
labeled accuracy-eval set, not a curated study scenario set) — write a
smaller, purpose-built scenarios.json for the actual study instead.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db
from app.seeding import seed_scenarios


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <participant_id> <scenarios.json>")
        sys.exit(1)

    participant_id, scenarios_path = sys.argv[1], sys.argv[2]

    db.init_db()
    participant = db.get_participant(participant_id)
    if participant is None:
        print(f"No active participant with id {participant_id!r} — has it connected via /auth/start?")
        sys.exit(1)

    with open(scenarios_path) as f:
        scenarios = json.load(f)

    print(f"Seeding {len(scenarios)} email(s) into {participant['email']}'s inbox...")
    try:
        ids = seed_scenarios(participant_id, participant["email"], scenarios)
    except Exception as e:
        if "insufficient" in str(e).lower() or "403" in str(e):
            print(
                "Insert failed — likely a scope problem. This participant probably "
                "connected before gmail.insert was added to app/google_auth.py's "
                "SCOPES. Have them reconnect via /auth/start, then retry."
            )
        raise
    print(f"Done. {len(ids)} message(s) inserted as unread.")


if __name__ == "__main__":
    main()
