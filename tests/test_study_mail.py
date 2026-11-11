"""Daily study emails: right role and day, once, from 8:00, resumable; and
the schedule file itself."""

import json
from collections import Counter
from datetime import datetime, timedelta

import pytest

import app.study_mail as sm
from app import db

SCHEDULE = json.loads(sm.SCHEDULE_PATH.read_text())
CATEGORIES = {"announcement_promo", "informational", "admin_action", "course_logistics",
              "academic_question", "meeting_request", "request_exception",
              "collaboration_opportunity", "wellbeing", "ambiguous", "spam"}


# --- the schedule file -------------------------------------------------------

@pytest.mark.parametrize("role", ["student", "instructor"])
def test_schedule_has_14_days_of_5_to_10_emails(role):
    days = SCHEDULE["days"][role]
    assert sorted(days, key=int) == [str(d) for d in range(1, 15)]
    assert all(5 <= len(days[d]) <= 10 for d in days)


@pytest.mark.parametrize("role", ["student", "instructor"])
def test_schedule_emails_are_complete_and_unique(role):
    emails = [e for d in SCHEDULE["days"][role].values() for e in d]
    assert all(e["category"] in CATEGORIES and e["sender"] and e["subject"] and e["body"] for e in emails)
    assert len({e["id"] for e in emails}) == len(emails)
    assert set(Counter(e["category"] for e in emails)) == CATEGORIES


def test_announcements_are_the_largest_share():
    for role in ("student", "instructor"):
        counts = Counter(e["category"] for d in SCHEDULE["days"][role].values() for e in d)
        assert counts.most_common(1)[0][0] == "announcement_promo"
    s = Counter(e["category"] for d in SCHEDULE["days"]["student"].values() for e in d)
    i = Counter(e["category"] for d in SCHEDULE["days"]["instructor"].values() for e in d)
    assert s["announcement_promo"] > i["announcement_promo"]


def test_schedule_is_not_copied_from_training_data():
    import re
    tok = lambda t: set(re.findall(r"[a-z0-9']+", t.lower()))
    train = [tok(e["subject"] + " " + e["body"]) for e in
             json.loads((sm.SCHEDULE_PATH.parent / "dataset_v2.json").read_text())]
    for role in ("student", "instructor"):
        for d in SCHEDULE["days"][role].values():
            for e in d:
                a = tok(e["subject"] + " " + e["body"])
                assert max(len(a & b) / len(a | b) for b in train) < 0.5, e["id"]


# --- the scheduler -----------------------------------------------------------

class Outbox:
    def __init__(self, fail_after=None):
        self.sent, self.fail_after = [], fail_after

    def __call__(self, pid, address, sender, subject, body, headers):
        if self.fail_after is not None and len(self.sent) >= self.fail_after:
            raise RuntimeError("Gmail API error")
        self.sent.append((pid, subject, headers))


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("STUDY_AUTOSEED", "on")


def connect(pid, role, days_ago=0):
    db.upsert_participant(pid, f"{pid}@example.com", "{}")
    if role:
        db.set_participant_role(pid, role)
    if days_ago:
        start = (datetime.utcnow() - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with db._conn() as conn:
            conn.execute("UPDATE participants SET connected_at = ? WHERE id = ?", (start, pid))


def at(hour):
    return datetime.now(sm.TZ).replace(hour=hour, minute=5)


def mine(outbox, pid):
    return [s for s in outbox.sent if s[0] == pid]


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("STUDY_AUTOSEED", raising=False)
    connect("sm0", "student")
    out = Outbox()
    assert sm.run_once(at(9), send=out) == [] and out.sent == []


def test_day_1_is_sent_right_after_the_role_and_only_once(on):
    connect("sm1", "student")
    out = Outbox()
    sm.run_once(at(6), send=out)               # before 8:00 is fine on day 1
    sm.run_once(at(9), send=out)               # second run: nothing new
    sent = mine(out, "sm1")
    assert len(sent) == len(SCHEDULE["days"]["student"]["1"])
    expected = {e["id"] for e in SCHEDULE["days"]["student"]["1"]}
    assert {h["X-Study-Seed-Id"] for _, _, h in sent} == expected
    assert all(h["X-Study-Expected"] in CATEGORIES for _, _, h in sent)


def test_no_role_no_emails(on):
    connect("sm2", None)
    out = Outbox()
    sm.run_once(at(9), send=out)
    assert mine(out, "sm2") == []


def test_later_days_wait_for_8am_and_use_the_role(on):
    connect("sm3", "instructor", days_ago=2)   # study day 3
    out = Outbox()
    sm.run_once(at(7), send=out)
    assert mine(out, "sm3") == []
    sm.run_once(at(8), send=out)
    ids = {h["X-Study-Seed-Id"] for _, _, h in mine(out, "sm3")}
    assert ids == {e["id"] for e in SCHEDULE["days"]["instructor"]["3"]}


def test_nothing_after_day_14(on):
    connect("sm4", "student", days_ago=14)     # study day 15
    out = Outbox()
    sm.run_once(at(9), send=out)
    assert mine(out, "sm4") == []


def test_interrupted_day_resumes_without_duplicates(on):
    connect("sm5", "student")
    first = Outbox(fail_after=3)
    sm.run_once(at(9), send=first)
    log = db.get_seed_log("sm5", 1)
    assert log["sent"] == 3 and log["finished_at"] is None and "Gmail API error" in log["last_error"]
    second = Outbox()
    sm.run_once(at(9), send=second)
    all_ids = [h["X-Study-Seed-Id"] for _, _, h in mine(first, "sm5") + mine(second, "sm5")]
    assert len(all_ids) == len(set(all_ids)) == len(SCHEDULE["days"]["student"]["1"])


def test_order_is_shuffled_per_participant_but_stable():
    a1 = [e["id"] for e in sm.emails_for("student", 6, "pA")]
    assert a1 == [e["id"] for e in sm.emails_for("student", 6, "pA")]
    assert sorted(a1) == sorted(e["id"] for e in SCHEDULE["days"]["student"]["6"])
