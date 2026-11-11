"""Calendar staging and confirmation (paper §III-B, §III-C).

Checks the properties the paper relies on:
  * routing an email to the calendar handler never touches the Calendar API
  * the draft reply carries neither the confirmation token nor a booking claim
  * confirmation is the only write, and it is idempotent: sequential and
    concurrent repeats, and a retry after a crash between the insert and the
    database update, all yield exactly one event
  * cancelled proposals cannot be confirmed, confirmed ones cannot be cancelled
  * the HTTP endpoints expose the same behaviour

No Google credentials or network needed: the Calendar service is faked.

    python3 -m pytest tests/
"""
import os
import sys
import threading
import time
import types
from datetime import datetime

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from googleapiclient.errors import HttpError  # noqa: E402

from app import pending  # noqa: E402
from app.handlers import calendar as cal  # noqa: E402


class FakeCalendar:
    """Mimics service.events().insert/get(...).execute() with Google's 409
    on a duplicate event id."""

    def __init__(self, fail_after_insert=False, delay=0.0):
        self.delay = delay  # widens the race window in the concurrency test
        self.events_by_id = {}
        self.insert_calls = 0
        self.fail_after_insert = fail_after_insert
        self.lock = threading.Lock()

    def events(self):
        return self

    def insert(self, calendarId, body):
        def execute():
            with self.lock:
                self.insert_calls += 1
            time.sleep(self.delay)
            with self.lock:
                if body["id"] in self.events_by_id:
                    resp = types.SimpleNamespace(status=409, reason="duplicate")
                    raise HttpError(resp, b'{"error": {"code": 409}}')
                event = dict(body, htmlLink=f"https://calendar/{body['id']}")
                self.events_by_id[body["id"]] = event
            if self.fail_after_insert:
                self.fail_after_insert = False
                raise ConnectionError("process died after the insert")
            return event
        return types.SimpleNamespace(execute=execute)

    def get(self, calendarId, eventId):
        return types.SimpleNamespace(execute=lambda: self.events_by_id[eventId])


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / "pending.sqlite3")
    monkeypatch.setattr("app.pending.PENDING_DB_PATH", path)

    def no_api():
        raise AssertionError("Calendar API must not be called while staging")
    monkeypatch.setattr(cal, "_get_service", no_api)
    return path


def _state(body, sender="alice@example.com", subject="Sync"):
    return {"email_id": "e1", "sender": sender, "subject": subject, "body": body,
            "category": "meeting", "handler_used": None, "response": None,
            "tokens_used": None, "latency_ms": None}


def _inserter(service):
    return lambda record, event_id: cal.insert_event(record, event_id, service=service)


# ------------------------------------------------------------------ staging

def test_handler_stages_without_calendar_write(db):
    out = cal.calendar_handler(_state("Can we meet on March 3 at 3pm?"))
    token = out["confirmation_token"]

    record = pending.get(token)
    assert record["status"] == "pending"
    assert record["time_source"] == "parsed"
    assert datetime.fromisoformat(record["start_iso"]).hour == 15
    assert record["event_id"] is None
    assert out["handler_used"] == "calendar"
    assert out["tokens_used"] == out["input_tokens"] == out["output_tokens"] == 0


def test_draft_never_contains_token_or_claims_booking(db):
    for body in ("Can we meet on March 3 at 3pm?", "Let's find a time to chat soon"):
        out = cal.calendar_handler(_state(body))
        assert out["confirmation_token"] not in out["response"]
        assert "scheduled" not in out["response"].lower()
        assert "calendar link" not in out["response"].lower()


def test_unparseable_time_is_flagged_as_fallback(db):
    out = cal.calendar_handler(_state("Let's find a time to chat soon"))
    assert pending.get(out["confirmation_token"])["time_source"] == "fallback"
    assert "suggest a few times" in out["response"]


# ------------------------------------------------------------- confirmation

def test_confirm_writes_once_and_is_idempotent(db):
    token = cal.calendar_handler(_state("Meet on March 3 at 3pm?"))["confirmation_token"]
    svc = FakeCalendar()

    first, already1 = pending.confirm(token, _inserter(svc))
    second, already2 = pending.confirm(token, _inserter(svc))

    assert (already1, already2) == (False, True)
    assert svc.insert_calls == 1
    assert len(svc.events_by_id) == 1
    assert first["event_id"] == second["event_id"] == pending.event_id_for(token)
    assert pending.get(token)["status"] == "confirmed"


def test_concurrent_confirms_create_one_event(db):
    token = cal.calendar_handler(_state("Meet on March 3 at 3pm?"))["confirmation_token"]
    svc = FakeCalendar(delay=0.05)
    results, errors = [], []

    def worker():
        try:
            results.append(pending.confirm(token, _inserter(svc)))
        except Exception as e:  # pragma: no cover - surfaced by the assert
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert svc.insert_calls == 1
    assert sorted(already for _, already in results) == [False] + [True] * 7


def test_retry_after_crash_finds_existing_event(db):
    token = cal.calendar_handler(_state("Meet on March 3 at 3pm?"))["confirmation_token"]
    svc = FakeCalendar(fail_after_insert=True)

    with pytest.raises(ConnectionError):
        pending.confirm(token, _inserter(svc))
    assert pending.get(token)["status"] == "pending"   # rolled back
    assert len(svc.events_by_id) == 1                  # but the event exists

    record, already = pending.confirm(token, _inserter(svc))
    assert already is False
    assert len(svc.events_by_id) == 1                  # 409 -> reused, not duplicated
    assert record["event_id"] == pending.event_id_for(token)


def test_cancel_rules(db):
    t1 = cal.calendar_handler(_state("Meet on March 3 at 3pm?"))["confirmation_token"]
    pending.cancel(t1)
    assert pending.cancel(t1)[1] is True               # idempotent
    with pytest.raises(pending.Conflict):
        pending.confirm(t1, _inserter(FakeCalendar()))

    t2 = cal.calendar_handler(_state("Meet on March 4 at 3pm?"))["confirmation_token"]
    pending.confirm(t2, _inserter(FakeCalendar()))
    with pytest.raises(pending.Conflict):
        pending.cancel(t2)


def test_unknown_token(db):
    with pytest.raises(pending.NotFound):
        pending.confirm("nope", _inserter(FakeCalendar()))


# -------------------------------------------------------------------- HTTP

@pytest.fixture
def client(db, monkeypatch):
    # app.main builds the full graph; stub the heavyweight handlers so the
    # test needs neither torch, ChromaDB nor an API key.
    for name, attrs in {
        "app.distilbert_classifier": {"classify_email_distilbert": lambda s, b: "meeting"},
        "app.handlers.retrieval": {"retrieval_handler": lambda s: s},
        "app.handlers.llm": {"llm_handler": lambda s: s},
    }.items():
        mod = types.ModuleType(name)
        mod.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, mod)
    for name in ("app.main", "app.graph", "app.handlers.cache"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    from fastapi.testclient import TestClient
    import app.main as main

    svc = FakeCalendar()
    monkeypatch.setattr(main, "insert_event",
                        lambda record, event_id: cal.insert_event(record, event_id, service=svc))
    c = TestClient(main.app)
    c.fake_calendar = svc
    return c


def test_http_flow(client):
    r = client.post("/route-email", json={"sender": "bob@example.com", "subject": "Chat",
                                          "body": "Could we meet on March 3 at 3pm?"})
    assert r.status_code == 200
    body = r.json()
    token = body["confirmation_token"]
    assert body["handler_used"] == "calendar"
    assert token not in body["response"]
    assert client.fake_calendar.insert_calls == 0      # nothing booked yet

    assert [m["token"] for m in client.get("/pending").json()] == [token]

    r1 = client.post(f"/pending/{token}/confirm")
    r2 = client.post(f"/pending/{token}/confirm")
    assert r1.status_code == r2.status_code == 200
    assert (r1.json()["already_done"], r2.json()["already_done"]) == (False, True)
    assert client.fake_calendar.insert_calls == 1
    assert client.get("/pending").json() == []
    assert client.post(f"/pending/{token}/cancel").status_code == 409
    assert client.post("/pending/nope/confirm").status_code == 404
