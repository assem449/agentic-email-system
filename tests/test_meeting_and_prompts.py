"""meeting_request slot choice and handler, and the drafting prompts.

The two LLM calls and the Calendar API are stubbed. These tests check the
decisions (which time, accept or propose, review when the calendar can't be
read), not how well the real LLM reads times or words the reply.
"""

from datetime import datetime, timedelta

import pytest

import app.handlers.calendar as cal
from app import db
from app.handlers.llm import system_prompt

TZ = cal.TZ
NOW = datetime(2026, 10, 26, 9, 0, tzinfo=TZ)  # a Monday, 9:00
HALF = timedelta(minutes=30)


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


# --- choose_slot -------------------------------------------------------------

def test_free_specific_time_is_accepted():
    assert cal.choose_slot([], [(at(27, 14), None)], HALF, NOW) == ("accepted", at(27, 14))


def test_first_free_option_in_senders_order():
    busy = [(at(27, 14), at(27, 15))]
    options = [(at(27, 14), None), (at(28, 10), None)]
    assert cal.choose_slot(busy, options, HALF, NOW) == ("accepted", at(28, 10))


def test_range_is_searched_for_a_free_slot():  # "Wednesday after 2 pm"
    busy = [(at(28, 14), at(28, 15, 30))]
    assert cal.choose_slot(busy, [(at(28, 14), at(28, 18))], HALF, NOW) == ("accepted", at(28, 15, 30))


def test_busy_options_get_the_next_free_slot():
    busy = [(at(26, 11), at(26, 18)), (at(27, 14), at(27, 15))]
    assert cal.choose_slot(busy, [(at(27, 14), None)], HALF, NOW) == ("busy", at(27, 9))


def test_no_time_proposed_gets_next_free_slot_after_lead_time():
    assert cal.choose_slot([], [], HALF, NOW) == ("none", at(26, 11))


@pytest.mark.parametrize("option", [
    (at(27, 19), None),                     # evening: outside default hours
    (datetime(2026, 10, 31, 10, 0, tzinfo=TZ), None),  # Saturday
    (at(26, 9, 30), None),                  # sooner than the 2-hour lead
])
def test_times_outside_preferences_are_not_accepted(option):
    decision, _ = cal.choose_slot([], [option], HALF, NOW)
    assert decision == "busy"


def test_nothing_free_in_window():
    busy = [(NOW, NOW + timedelta(days=30))]
    assert cal.choose_slot(busy, [], HALF, NOW) == ("no_slot", None)


# --- parse_options -------------------------------------------------------------

def test_parse_options_reads_times_ranges_and_length():
    raw = 'Sure: {"options": [{"date": "2026-10-28", "start": "14:00", "end": "18:00"}, ' \
          '{"date": "2026-10-29", "start": "10:00", "end": null}], "duration_minutes": 15}'
    options, minutes = cal.parse_options(raw)
    assert options == [(at(28, 14), at(28, 18)), (at(29, 10), None)]
    assert minutes == 15


@pytest.mark.parametrize("raw", ["no json here", "{broken", '{"options": [{"date": "soon"}]}'])
def test_unreadable_extraction_counts_as_no_time(raw):
    assert cal.parse_options(raw) == ([], None)


# --- handler -------------------------------------------------------------------

class FakeCalendar:
    def __init__(self, busy=None, fail=False):
        self.busy, self.fail = busy or [], fail

    def freebusy(self):
        return self

    def query(self, body):
        if self.fail:
            raise RuntimeError("Calendar API down")
        self._busy = [{"start": s.isoformat(), "end": e.isoformat()} for s, e in self.busy]
        return self

    def execute(self):
        return {"calendars": {"primary": {"busy": self._busy}}}


@pytest.fixture
def meeting(monkeypatch):
    prompts = []

    def fake_llm(system, user, max_tokens):
        prompts.append(system)
        if "JSON only" in system:
            return '{"options": [{"date": "2026-10-27", "start": "14:00", "end": null}], ' \
                   '"duration_minutes": 15}', 100, 30
        return "Hi Owen, ...", 150, 60

    monkeypatch.setattr(cal, "_llm", fake_llm)
    monkeypatch.setattr(cal, "_now", lambda: NOW)
    db.upsert_participant("m1", "m1@example.com", "{}")

    def run(calendar):
        monkeypatch.setattr(cal, "get_calendar_service_for", lambda pid: calendar)
        state = {"participant_id": "m1", "sender": "Owen Brady <o@x.edu>",
                 "subject": "Meet Tuesday?", "body": "Could we meet Tuesday at 2 for 15 minutes?",
                 "gmail_id": "g1"}
        return cal.calendar_handler(state), prompts
    return run


def test_handler_accepts_free_time_and_queues_pending_event(meeting):
    out, prompts = meeting(FakeCalendar())
    assert out["meeting_decision"] == "accepted"
    assert out["handler_used"] == "calendar_pending_review"
    assert out["tokens_used"] == 100 + 30 + 150 + 60
    assert "Tuesday, October 27 at 2:00 PM works" in prompts[-1]
    pending = db.list_pending_events_for_participant("m1")
    # 15 minutes, as the email asked, not the 30-minute default.
    assert any(p["proposed_start"].startswith("2026-10-27T14:00")
               and p["proposed_end"].startswith("2026-10-27T14:15") for p in pending)


def test_handler_proposes_when_requested_time_is_busy(meeting):
    out, prompts = meeting(FakeCalendar(busy=[(at(27, 14), at(27, 15))]))
    assert out["meeting_decision"] == "busy"
    assert "propose" in prompts[-1].lower()


def test_handler_calendar_failure_gets_no_time_and_review(meeting):
    out, prompts = meeting(FakeCalendar(fail=True))
    assert out["meeting_decision"] == "unavailable"
    assert out["handler_used"] == "calendar_unavailable"
    assert out["needs_review"] is True
    assert "[CONFIRM: meeting time]" in prompts[-1]


# --- drafting prompts ------------------------------------------------------------

def test_ambiguous_prompt_asks_clarifying_questions():
    assert "clarif" not in system_prompt({"category": "academic_question"}).lower()
    assert "Do not guess" in system_prompt({"category": "ambiguous"})


def test_role_context_in_prompt():
    assert "is an instructor or TA" in system_prompt({"category": "wellbeing", "role": "instructor"})
    assert "who will send this reply" not in system_prompt({"category": "wellbeing", "role": None})
