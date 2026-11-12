"""Draft tracking (unchanged / edited / sent / deleted, % words changed),
the optional review-minutes field, and how both show up in results."""

import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.draft_tracker as dt
import app.results as results
from app import db
from app.checkin import router as checkin_router

DRAFT = "Hi Owen,\n\nThe late penalty is 10% per day, up to three days.\n\nBest regards,\n[Your name]"


def payload(text):
    return {"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()}}


class Missing(Exception):
    class resp:
        status = 404


class FakeGmail:
    """drafts().get / threads().get with canned answers."""
    def __init__(self, draft_text=None, sent_text=None, sent_ms=10**13):
        self.draft_text, self.sent_text, self.sent_ms = draft_text, sent_text, sent_ms
        self._call = None

    def users(self): return self
    def drafts(self): self._call = "draft"; return self
    def threads(self): self._call = "thread"; return self
    def get(self, **kw): return self

    def execute(self):
        if self._call == "draft":
            if self.draft_text is None:
                raise Missing("Requested entity was not found.")
            return {"message": {"payload": payload(self.draft_text)}}
        msgs = []
        if self.sent_text is not None:
            msgs.append({"labelIds": ["SENT"], "internalDate": str(self.sent_ms), "payload": payload(self.sent_text)})
        return {"messages": msgs}


EVENT = {"id": "e1", "draft_id": "d1", "thread_id": "t1", "draft_text": DRAFT,
         "created_at": "2026-11-12T08:00:00Z"}


def test_change_pct():
    assert dt.change_pct(DRAFT, DRAFT) == 0.0
    assert 0 < dt.change_pct(DRAFT, DRAFT.replace("three", "two")) < 20
    assert dt.change_pct(DRAFT, "Hi Owen,\n\nSee the outline.\n\nThanks") > 50
    # Gmail's quoted history and a different sign-off don't count as edits.
    assert dt.change_pct(DRAFT, DRAFT.replace("[Your name]", "Sam") + "\n\nOn Tue, Owen wrote:\n> question") == 0.0


@pytest.mark.parametrize("gmail,status", [
    (FakeGmail(draft_text=DRAFT), "unchanged"),
    (FakeGmail(draft_text=DRAFT.replace("10% per day", "5% per day")), "edited"),
    (FakeGmail(draft_text=None, sent_text=DRAFT), "sent"),
    (FakeGmail(draft_text=None, sent_text=None), "deleted"),
])
def test_check_draft(gmail, status):
    got, pct = dt.check_draft(gmail, EVENT)
    assert got == status
    assert (pct is None) == (status == "deleted")


def test_sent_before_the_draft_does_not_count():
    gmail = FakeGmail(draft_text=None, sent_text=DRAFT, sent_ms=1000)  # 1970
    assert dt.check_draft(gmail, EVENT) == ("deleted", None)


def test_run_once_updates_rows(monkeypatch):
    db.upsert_participant("dt1", "dt1@example.com", "{}")
    db.record_email_event(participant_id="dt1", gmail_id="g-dt1", sender="x", subject="late?",
                          category="course_logistics", handler_used="faq_llm", response_preview="",
                          input_tokens=10, output_tokens=5, body_chars=20, reply_needed=True)
    db.set_event_draft("dt1", "g-dt1", "d1", "t1", DRAFT)
    monkeypatch.setattr(dt, "get_gmail_service_for",
                        lambda pid: FakeGmail(draft_text=DRAFT.replace("three days.", "three days. Good luck!")))
    assert dt.run_once() >= 1
    row = next(e for e in db.list_email_events() if e["gmail_id"] == "g-dt1")
    assert row["draft_status"] == "edited" and row["draft_change_pct"] > 0
    # sent/deleted drafts are no longer tracked
    db.update_draft_status(row["id"], "sent", 5.0)
    assert all(e["gmail_id"] != "g-dt1" for e in db.list_drafts_to_track("dt1", "2000-01-01T00:00:00Z"))


def test_review_minutes_saved_and_summarised():
    app = FastAPI(); app.include_router(checkin_router)
    client = TestClient(app)
    token = db.upsert_participant("dt2", "dt2@example.com", "{}")
    assert client.post(f"/checkin/{token}/submit", json={"review_minutes": 7}).status_code == 200
    sub = db.get_checkin_submission("dt2", db.day_number_for("dt2"))
    assert sub["review_minutes"] == 7
    token3 = db.upsert_participant("dt3", "dt3@example.com", "{}")
    client.post(f"/checkin/{token3}/submit", json={"review_minutes": 5000})   # out of range
    assert db.get_checkin_submission("dt3", db.day_number_for("dt3"))["review_minutes"] is None
    s = results.build_results(participant="dt2")["summary"]
    assert s["avg_review_minutes"] == 7.0 and s["review_minutes_days"] == 1


def test_review_summary_counts():
    rows = [{"draft_status": s, "draft_change_pct": p} for s, p in
            [("unchanged", 0), ("unchanged", 0), ("edited", 10), ("sent", 30), ("deleted", None), (None, None)]]
    s = results.review_summary(rows, [4, 6])
    assert s["drafts"] == 5
    assert s["drafts_by_status"] == {"unchanged": 2, "edited": 1, "sent": 1, "deleted": 1}
    assert s["drafts_used_unchanged_pct"] == 40.0
    assert s["median_change_pct"] == 20.0
    assert s["avg_review_minutes"] == 5.0
