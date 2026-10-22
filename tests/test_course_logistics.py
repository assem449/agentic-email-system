"""course_logistics handler: role check, wrong course, FAQ match, cache.

The FAQ search (ChromaDB embeddings) and the LLM are replaced by stubs, so
these tests check the handler's decisions, not match quality or wording.
"""

import pytest

import app.handlers.course_logistics as cl
from app import db

FAQ = cl._load_faq()
LATE = next(e for e in FAQ["entries"] if e["id"] == "late-penalty")


@pytest.fixture
def stubs(monkeypatch):
    calls = {"llm": 0}

    def fake_write(entry, faq):
        calls["llm"] += 1
        return f"Answer from {entry['id']}.", 120, 40

    monkeypatch.setattr(cl, "_match", lambda text: (LATE, 0.2))
    monkeypatch.setattr(cl, "_write_reply", fake_write)
    return calls


def email(pid="p1", role="instructor", sender="Fatima Noor <f.noor@my.northfield.edu>",
          body="Is the late penalty 10% per day?", subject="Late penalty"):
    return {"participant_id": pid, "role": role, "sender": sender,
            "subject": subject, "body": body,
            "input_tokens": 0, "output_tokens": 0}


def connect(pid):
    db.upsert_participant(pid, f"{pid}@example.com", "{}")


@pytest.mark.parametrize("role", ["student", None])
def test_not_an_instructor_gets_review_no_draft(stubs, role):
    out = cl.course_logistics_handler(email(role=role))
    assert out["handler_used"] == "logistics_review_role"
    assert out["response"] is None and out["needs_review"]
    assert stubs["llm"] == 0


def test_other_course_is_not_covered(stubs):
    out = cl.course_logistics_handler(email(body="What is the late penalty in CHEM 1000?"))
    assert out["handler_used"] == "logistics_other_course"
    assert out["response"] is None and stubs["llm"] == 0


def test_own_course_code_and_room_numbers_are_fine(stubs):
    connect("p0")
    out = cl.course_logistics_handler(email(pid="p0", body=f"{FAQ['course']}: late penalty? Is Room 3021 right?"))
    assert out["handler_used"] == "faq_llm"


def test_no_close_entry_is_not_covered(stubs, monkeypatch):
    monkeypatch.setattr(cl, "_match", lambda text: (LATE, 0.8))
    out = cl.course_logistics_handler(email(body="Which room are office hours in this week?"))
    assert out["handler_used"] == "logistics_not_covered"
    assert out["response"] is None and out["needs_review"]


def test_second_matching_email_reuses_reply_with_new_greeting(stubs):
    connect("p2")
    first = cl.course_logistics_handler(email(pid="p2"))
    second = cl.course_logistics_handler(email(
        pid="p2", sender="Owen Brady <o.brady@my.northfield.edu>",
        body="How much do we lose per late day?"))
    assert first["handler_used"] == "faq_llm" and first["tokens_used"] == 160
    assert second["handler_used"] == "faq_cache_hit" and second["tokens_used"] == 0
    assert stubs["llm"] == 1
    assert first["response"].startswith("Hi Fatima,")
    assert second["response"].startswith("Hi Owen,")
    assert "Fatima" not in second["response"]
    assert "Answer from late-penalty." in second["response"]


def test_cache_is_per_participant(stubs):
    connect("p3"); connect("p4")
    cl.course_logistics_handler(email(pid="p3"))
    out = cl.course_logistics_handler(email(pid="p4"))
    assert out["handler_used"] == "faq_llm" and stubs["llm"] == 2


def test_editing_the_faq_stops_reuse(stubs, monkeypatch):
    connect("p5")
    cl.course_logistics_handler(email(pid="p5"))
    monkeypatch.setattr(cl, "_faq", {**FAQ, "version": "edited"})
    out = cl.course_logistics_handler(email(pid="p5"))
    assert out["handler_used"] == "faq_llm" and stubs["llm"] == 2


@pytest.mark.parametrize("sender,greeting", [
    ("Prof. Victor Lang <v.lang@northfield.edu>", "Hi Victor,"),
    ("o.brady@my.northfield.edu", "Hi,"),
    ("", "Hi,"),
])
def test_greeting(sender, greeting):
    assert cl._greeting(sender) == greeting


def test_role_is_stored_and_validated():
    connect("p6")
    assert db.get_participant_role("p6") is None
    db.set_participant_role("p6", "instructor")
    assert db.get_participant_role("p6") == "instructor"
    with pytest.raises(ValueError):
        db.set_participant_role("p6", "admin")
