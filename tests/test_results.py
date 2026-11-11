"""Results page data, saved cost, correct-category feedback and the Excel
export."""

import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

import app.results as results
from app import db
from app.checkin import router as checkin_router
from app.config import ADMIN_TOKEN

app = FastAPI()
app.include_router(checkin_router)
app.include_router(results.router)
client = TestClient(app)
ADMIN = {"X-Admin-Token": ADMIN_TOKEN}


def event(pid, category, handler, tin, tout, chars, subject="s"):
    db.record_email_event(participant_id=pid, gmail_id="g", sender="x@y.edu", subject=subject,
                          category=category, handler_used=handler, response_preview="",
                          input_tokens=tin, output_tokens=tout, latency_ms=10.0,
                          body_chars=chars, reply_needed=tout > 0, needs_review=False)


def test_cost_usd():
    assert results.cost_usd(1_000_000, 0) == 3.0
    assert results.cost_usd(0, 1_000_000) == 15.0


def test_baseline_needs_enough_llm_emails():
    rows = [{"handler_used": "llm", "input_tokens": 500, "output_tokens": 100, "body_chars": 400}] * 4
    assert results.baseline_model(rows) is None
    model = results.baseline_model(rows + rows[:1])
    assert model == {"emails": 5, "prompt_tokens": 400.0, "output_tokens": 100.0}  # 500 - 400/4


@pytest.fixture(scope="module")
def study():
    token = db.upsert_participant("res1", "res1@example.com", "{}")
    db.set_participant_role("res1", "student")
    for i in range(5):  # general-LLM drafts: 600 in (200 prompt + 1600/4), 150 out
        event("res1", "academic_question", "llm", 600, 150, 1600, subject=f"q{i}")
    event("res1", "announcement_promo", "no_reply_bulk", 0, 0, 2000, subject="newsletter")
    event("res1", "meeting_request", "calendar_pending_review", 400, 90, 400, subject="meet")
    # Recorded before cost tracking: no token data.
    db.record_email_event(participant_id="res1", gmail_id="g", sender="x", subject="old",
                          category="spam", handler_used="blocked", response_preview="")
    ids = {e["subject"]: e["id"] for e in db.list_email_events() if e["participant_id"] == "res1"}
    r = client.post(f"/checkin/{token}/submit", json={"overall_rating": 8, "notes": "ok", "per_email": [
        {"email_event_id": ids["q0"], "correct": True},
        {"email_event_id": ids["newsletter"], "correct": False, "correct_category": "admin_action"},
        {"email_event_id": ids["meet"], "correct": False, "correct_category": "not_a_category"},
        {"email_event_id": ids["q1"], "correct": True, "correct_category": "spam"},
    ]})
    assert r.status_code == 200
    return results.build_results(participant="res1")


def test_correct_category_saved_only_for_wrong_and_valid(study):
    by_subject = {r["subject"]: r for r in study["rows"]}
    assert by_subject["newsletter"]["verdict"] == "wrong"
    assert by_subject["newsletter"]["should_be"] == "admin_action"
    assert by_subject["meet"]["should_be"] is None      # invalid name dropped
    assert by_subject["q1"]["should_be"] is None        # ignored when Correct
    assert by_subject["q2"]["verdict"] == "not rated"


def test_summary_and_saved_cost(study):
    s = study["summary"]
    assert s["emails"] == 8 and s["rated"] == 4 and s["correct"] == 2 and s["correct_pct"] == 50.0
    assert s["with_cost_data"] == 7                     # the old row is left out
    assert s["llm_calls_avoided"] == 1
    # baseline per email: (200 + chars/4) in, 150 out
    expected_baseline = (5 * results.cost_usd(600, 150) + results.cost_usd(700, 150)
                         + results.cost_usd(300, 150))
    expected_actual = 5 * results.cost_usd(600, 150) + results.cost_usd(400, 90)
    assert s["baseline_usd"] == round(expected_baseline, 4)
    assert s["actual_usd"] == round(expected_actual, 4)
    assert s["saved_usd"] == round(expected_baseline - expected_actual, 4)


def test_confusion_and_by_category(study):
    conf = {(c["predicted"], c["participant_says"]): c["count"] for c in study["confusion"]}
    assert conf[("announcement_promo", "admin_action")] == 1
    assert conf[("meeting_request", "unknown")] == 1
    assert conf[("academic_question", "academic_question")] == 2
    cat = {c["category"]: c for c in study["by_category"]}
    assert cat["academic_question"]["rated"] == 2 and cat["academic_question"]["correct_pct"] == 100.0


def test_endpoints_need_the_admin_token(study):
    assert client.get("/admin/results.json").status_code == 401
    assert client.get("/admin/export.xlsx", headers={"X-Admin-Token": "nope"}).status_code == 401
    assert client.get("/admin/results.json?participant=res1", headers=ADMIN).json()["summary"]["emails"] == 8
    assert "Study results" in client.get("/admin/results").text


def test_excel_export_has_all_sheets_and_no_tokens(study):
    r = client.get("/admin/export.xlsx", headers=ADMIN)
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Summary", "Emails", "By category", "True labels", "Confusion", "Feedback", "Participants"]
    participants = [row for row in wb["Participants"].iter_rows(values_only=True)]
    assert participants[0] == ("Participant", "Email", "Role", "Connected (UTC)", "Active", "Days checked in")
    assert all("token" not in str(c).lower() for row in participants for c in row)
    assert any(row[0] == "res1" and row[5] == 1 for row in participants[1:])


def test_true_label_accuracy():
    db.upsert_participant("res2", "res2@example.com", "{}")
    for cat, true in [("spam", "spam"), ("spam", "announcement_promo"),
                      ("admin_action", "admin_action"), ("informational", None)]:
        db.record_email_event(participant_id="res2", gmail_id="g", sender="x", subject=f"{cat}-{true}",
                              category=cat, handler_used="no_reply", response_preview="",
                              input_tokens=0, output_tokens=0, body_chars=10,
                              expected_category=true, seed_id="s-x" if true else None)
    data = results.build_results(participant="res2")
    s = data["summary"]
    assert s["with_true_label"] == 3 and s["model_correct"] == 2 and s["model_correct_pct"] == 66.7
    truth = {c["category"]: c for c in data["by_true_category"]}
    assert truth["announcement_promo"]["model_correct"] == 0
    assert truth["announcement_promo"]["predicted_instead"] == {"spam": 1}
