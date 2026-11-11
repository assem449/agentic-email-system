"""Daily study emails: each participant's inbox gets that study day's emails
for their role, once, at SEND_HOUR in the study's time zone.

The emails come from data/academic/study_schedule.json, written for the
study and separate from the classifier's training data. Everyone with the
same role gets the same emails on the same study day (a fixed schedule),
in an order shuffled per participant. Each email carries hidden headers
with the category it was written as (X-Study-Expected) and its schedule id
(X-Study-Seed-Id), so results can compare the classifier with the true
label.

Runs only when STUDY_AUTOSEED=on, so test accounts don't receive study
mail. Day 1 is sent as soon as the participant has chosen a role; days
2-14 at SEND_HOUR. A day the server missed is skipped, not sent late.
"""

import json
import os
import random
import time
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app import db
from app.config import STUDY_TIMEZONE
from app.seeding import seed_email

SCHEDULE_PATH = Path(__file__).parent.parent / "data" / "academic" / "study_schedule.json"
SEND_HOUR = 8
STUDY_DAYS = 14
CHECK_INTERVAL_SECONDS = 300
TZ = ZoneInfo(STUDY_TIMEZONE)

STATUS = {"last_run_at": None, "last_error": None}

_schedule = None


def enabled() -> bool:
    return os.environ.get("STUDY_AUTOSEED", "off").lower() == "on"


def load_schedule() -> dict:
    global _schedule
    if _schedule is None:
        _schedule = json.loads(SCHEDULE_PATH.read_text())
    return _schedule


def emails_for(role: str, day: int, participant_id: str) -> list:
    """That day's emails for the role, shuffled the same way every time for
    this participant (so a resumed day continues in the same order)."""
    emails = list(load_schedule()["days"][role].get(str(day), []))
    random.Random(f"{participant_id}:{day}").shuffle(emails)
    return emails


def headers_for(email: dict) -> dict:
    return {**(email.get("headers") or {}),
            "X-Study-Expected": email["category"],
            "X-Study-Seed-Id": email["id"]}


def due(day: int, now: datetime) -> bool:
    return 1 <= day <= STUDY_DAYS and (day == 1 or now.hour >= SEND_HOUR)


def run_once(now: datetime = None, send=seed_email) -> list:
    """Send whatever is due now. Returns [(participant_id, day, sent)]."""
    if not enabled():
        return []
    now = now or datetime.now(TZ)
    done = []
    for participant_id in db.list_active_participant_ids():
        participant = db.get_participant(participant_id)
        role = participant["role"] if participant else None
        if not role:
            continue  # chosen in the check-in popup; nothing is sent before that
        day = db.day_number_for(participant_id)
        if day is None or not due(day, now):
            continue
        emails = emails_for(role, day, participant_id)
        log = db.get_seed_log(participant_id, day)
        if log is not None and log["finished_at"]:
            continue
        if log is None:
            db.start_seed_day(participant_id, day, len(emails))
        sent = log["sent"] if log is not None else 0
        try:
            for email in emails[sent:]:
                send(participant_id, participant["email"], email["sender"],
                     email["subject"], email["body"], headers_for(email))
                sent += 1
            db.update_seed_day(participant_id, day, sent, finished=True)
        except Exception as e:
            db.update_seed_day(participant_id, day, sent, finished=False,
                               error=f"{type(e).__name__}: {e}")
            print(f"[{participant_id}] study mail day {day} stopped after {sent}: {e}")
        done.append((participant_id, day, sent))
    return done


def run_study_mail(interval_seconds: int = CHECK_INTERVAL_SECONDS):
    print(f"Study mail scheduler {'on' if enabled() else 'off (STUDY_AUTOSEED is not on)'}.")
    while True:
        try:
            db.init_db()
            run_once()
            STATUS["last_error"] = None
        except Exception as e:
            STATUS["last_error"] = f"{type(e).__name__}: {e}\n" + "".join(
                traceback.format_tb(e.__traceback__)[-3:])
            print(f"study mail error: {STATUS['last_error']}")
        STATUS["last_run_at"] = datetime.now(TZ).isoformat(timespec="seconds")
        time.sleep(interval_seconds)
