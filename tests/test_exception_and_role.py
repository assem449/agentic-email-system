"""request_exception note and the one-time role choice.

The LLM is replaced by a stub returning a fixed summary; the real wording
is not tested here.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.graph as graph_module
import app.handlers.request_exception as rx
from app import db
from app.checkin import _gmail_row_html, _welcome_modal_html
from app.gmail_client import LABEL_NEEDS_REVIEW, LABEL_PROCESSED
from app.poller import gmail_actions

SUMMARY = "Fatima Noor asks for a 3-day extension on Assignment 3 because of the flu; offers a medical note."


@pytest.fixture
def fake_llm(monkeypatch):
    def create(**kwargs):
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=SUMMARY)],
            usage=SimpleNamespace(input_tokens=90, output_tokens=30),
        )
    monkeypatch.setattr(rx._client.messages, "create", create)


def run_exception():
    original = graph_module.classify_node
    graph_module.classify_node = lambda s: {**s, "category": "request_exception"}
    try:
        return graph_module.build_graph().invoke({
            "email_id": "t", "sender": "Fatima Noor <f.noor@my.northfield.edu>",
            "subject": "Extension request", "body": "I had the flu, could I get 3 more days?",
            "category": None, "participant_id": None, "auth_verdict": "pass",
            "bulk_reason": None,
        })
    finally:
        graph_module.classify_node = original


def test_exception_becomes_a_note_to_self(fake_llm):
    result = run_exception()
    assert result["handler_used"] == "exception_note"
    assert result["response"].startswith("Note for you, not sent to Fatima Noor:")
    assert SUMMARY in result["response"]
    assert result["note_summary"] == SUMMARY
    assert result["tokens_used"] == 120
    assert gmail_actions(result) == (False, "self_note", [LABEL_PROCESSED, LABEL_NEEDS_REVIEW])


def test_note_and_subject_are_escaped_on_checkin():
    row = _gmail_row_html({
        "category": "request_exception", "handler_used": "exception_note",
        "subject": "<script>alert(1)</script>", "gmail_id": "g1",
        "response_preview": "asks <b>now</b>",
    }, "me@example.com")
    assert "<script>" not in row and "&lt;script&gt;" in row
    assert "asks &lt;b&gt;now&lt;/b&gt;" in row


def test_role_can_be_set_only_once():
    db.upsert_participant("r1", "r1@example.com", "{}")
    assert db.set_participant_role("r1", "student") is True
    assert db.set_participant_role("r1", "instructor") is False
    assert db.get_participant_role("r1") == "student"


def test_role_endpoint():
    from app.checkin import router
    from fastapi import FastAPI
    app = FastAPI(); app.include_router(router)
    client = TestClient(app)
    token = db.upsert_participant("r2", "r2@example.com", "{}")
    assert client.post(f"/checkin/{token}/role", json={"role": "admin"}).status_code == 400
    assert client.post(f"/checkin/{token}/role", json={"role": "instructor"}).status_code == 200
    assert client.post(f"/checkin/{token}/role", json={"role": "student"}).status_code == 409
    assert db.get_participant_role("r2") == "instructor"
    assert client.post("/checkin/nope/role", json={"role": "student"}).status_code == 404


def test_welcome_modal_requires_a_choice_until_role_set():
    unset = _welcome_modal_html("tok", True, None)
    assert "I'm a student" in unset and "disabled" in unset and "saveRoleAndStart" in unset
    chosen = _welcome_modal_html("tok", False, "instructor")
    assert "I'm a student" not in chosen and "Instructor" in chosen and "dismissWelcome" in chosen
