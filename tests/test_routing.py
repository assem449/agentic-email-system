"""Routing skeleton: bulk labels, no-reply categories and the header
safety check before Spam.

    python -m pytest tests/

No Gmail, calendar or LLM calls: route_decision and gmail_actions are pure,
and the graph tests only take paths that end without a drafting handler.
"""

import pytest

import app.graph as graph_module
from app.email_text import auth_verdict
from app.gmail_client import (
    LABEL_ACTION_NEEDED, LABEL_ANNOUNCEMENT, LABEL_DRAFT_READY,
    LABEL_NEEDS_REVIEW, LABEL_NO_REPLY, LABEL_PROCESSED,
)
from app.graph import route_decision
from app.poller import gmail_actions


def state(category, body="Some text.", bulk=None, verdict=None):
    return {
        "email_id": "t", "sender": "x@example.com", "subject": "s",
        "body": body, "category": category, "bulk_reason": bulk,
        "auth_verdict": verdict, "participant_id": None,
    }


# --- Decision 1: bulk mail keeps the classifier's category, no draft ---

@pytest.mark.parametrize("category", ["admin_action", "announcement_promo", "informational"])
def test_bulk_never_drafts(category):  # cases A, B, C
    assert route_decision(state(category, bulk="header:list-id", verdict="pass")) == "no_reply"


def test_bulk_in_a_drafting_category_gets_no_draft():
    assert route_decision(state("academic_question", bulk="header:list-id")) == "no_reply"


# --- Decision 2: Spam only when the classifier and the headers agree ---

def test_spam_that_fails_dmarc_is_moved():  # case D
    assert route_decision(state("spam", verdict="fail")) == "spam"


@pytest.mark.parametrize("verdict", ["pass", "none", None])
def test_spam_without_a_failed_check_is_held_for_review(verdict):  # case E, and unknown
    assert route_decision(state("spam", verdict=verdict)) == "suspicious"


def test_spam_beats_bulk():
    assert route_decision(state("spam", bulk="header:list-id", verdict="fail")) == "spam"


def test_failed_dmarc_is_not_answered():  # case F
    assert route_decision(state("ambiguous", verdict="fail")) == "suspicious"


def test_missing_dmarc_alone_does_not_block_a_draft():
    assert route_decision(state("academic_question", verdict="none")) == "llm"


# --- No-reply categories and drafting routes ---

@pytest.mark.parametrize("category", ["admin_action", "announcement_promo", "informational"])
def test_no_reply_categories(category):
    assert route_decision(state(category)) == "no_reply"


def test_informational_that_asks_something_gets_a_draft():
    assert route_decision(state("informational", body="Thanks! Could you check my grade?")) == "llm"


@pytest.mark.parametrize("category,node", [
    ("meeting_request", "calendar"), ("course_logistics", "course_logistics"),
    ("request_exception", "request_exception"), ("wellbeing", "llm"), ("something_new", "llm"),
])
def test_drafting_routes(category, node):
    assert route_decision(state(category)) == node


def test_rules_classifier_names_are_mapped():
    assert route_decision(state("meeting")) == "calendar"
    assert route_decision(state("ack")) == "no_reply"


# --- Gmail actions: (move to Spam?, draft?, labels) ---

def run(category, **kw):
    """Run the real graph with a fixed classifier. Only for paths that end
    without calling the LLM or calendar."""
    original = graph_module.classify_node
    graph_module.classify_node = lambda s: {**s, "category": category}
    try:
        return graph_module.build_graph().invoke(state(category, **kw))
    finally:
        graph_module.classify_node = original


def test_actions_moved_to_spam():
    assert gmail_actions(run("spam", verdict="fail")) == (True, None, [LABEL_PROCESSED])


def test_actions_spam_held():
    result = run("spam", verdict="pass")
    assert result["handler_used"] == "spam_held"
    assert gmail_actions(result) == (False, None, [LABEL_PROCESSED, LABEL_NEEDS_REVIEW])


def test_actions_auth_failed():
    result = run("course_logistics", verdict="fail")
    assert result["handler_used"] == "auth_failed"
    assert gmail_actions(result) == (False, None, [LABEL_PROCESSED, LABEL_NEEDS_REVIEW])


@pytest.mark.parametrize("category,label", [
    ("admin_action", LABEL_ACTION_NEEDED),
    ("announcement_promo", LABEL_ANNOUNCEMENT),
    ("informational", LABEL_NO_REPLY),
    ("course_logistics", LABEL_NO_REPLY),  # bulk mail in a drafting category
])
def test_actions_bulk_labels(category, label):
    result = run(category, bulk="header:list-id")
    assert result["category"] == category  # no relabel to announcement_promo
    assert gmail_actions(result) == (False, None, [LABEL_PROCESSED, label])


def test_actions_draft_with_review():
    result = {"handler_used": "llm", "category": "wellbeing",
              "reply_needed": True, "needs_review": True}
    assert gmail_actions(result) == (
        False, "reply", [LABEL_PROCESSED, LABEL_DRAFT_READY, LABEL_NEEDS_REVIEW])


# --- Header parsing ---

def payload(*headers):
    return {"headers": [{"name": n, "value": v} for n, v in headers]}


GMAIL = "mx.google.com; dkim=pass header.i=@northfield.edu; spf=pass; dmarc={} header.from=northfield.edu"


@pytest.mark.parametrize("value,expected", [
    ("pass (p=REJECT)", "pass"), ("fail (p=QUARANTINE)", "fail"),
    ("none", "none"), ("temperror", "none"),
])
def test_auth_verdict(value, expected):
    assert auth_verdict(payload(("Authentication-Results", GMAIL.format(value)))) == expected


def test_auth_verdict_missing_header():
    assert auth_verdict(payload(("From", "a@b.com"))) == "none"


def test_auth_verdict_ignores_a_forged_header():
    # A sender can add their own "dmarc=pass" header; only Gmail's counts.
    forged = ("Authentication-Results", "evil.example; dmarc=pass")
    real = ("Authentication-Results", GMAIL.format("fail"))
    assert auth_verdict(payload(real, forged)) == "fail"
    assert auth_verdict(payload(forged)) == "none"
