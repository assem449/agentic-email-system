"""Daily participant check-in page.

Each participant gets one private, unguessable link (their `checkin_token`,
shown once on the post-OAuth "Connected" page — see app/oauth_web.py).
Visiting it shows what the pipeline did with today's emails and collects
their feedback: per-email correctness, an overall draft-quality rating,
and free-text notes.

Deliberately a single self-contained HTML response (same approach as
/admin in app/main.py) — no build step, no framework, easy to swap out
once a real study UI is decided.
"""

import json
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app import db

router = APIRouter()

CATEGORY_STYLE = {
    "ack": ("#6B6A66", "#EFEDE6"),
    "faq": ("#2E6A7D", "#E4F0F5"),
    "meeting": ("#A6432E", "#FBE9E4"),
    "support": ("#7A5A2E", "#F5EEE0"),
    "spam": ("#7A2E2E", "#F5E4E4"),
    "emotional": ("#4A3D7A", "#ECE7F5"),
    "ambiguous": ("#6B6A66", "#EFEDE6"),
}
DEFAULT_STYLE = ("#6B6A66", "#EFEDE6")

STATUS_LABEL = {
    "template": "Draft created",
    "cache_hit": "Draft created",
    "cache_miss_llm": "Draft created",
    "retrieval_hit": "Draft created",
    "retrieval_miss_llm": "Draft created",
    "llm": "Draft created",
    "calendar_pending_review": "Awaiting approval",
    "calendar_pending_review_demo": "Awaiting approval (demo)",
    "blocked": "Blocked — spam",
}


def _gmail_link(gmail_id: str) -> str:
    if not gmail_id:
        return "#"
    return f"https://mail.google.com/mail/u/0/#all/{gmail_id}"


class PerEmailFeedback(BaseModel):
    email_event_id: str
    correct: bool


class CheckinSubmission(BaseModel):
    overall_rating: Optional[int] = None
    notes: str = ""
    per_email: List[PerEmailFeedback] = []


@router.get("/checkin/{token}", response_class=HTMLResponse)
def checkin_page(token: str):
    participant = db.get_participant_by_checkin_token(token)
    if participant is None:
        raise HTTPException(404, "Check-in link not recognized — it may have been disconnected.")

    day = db.day_number_for(participant["id"])
    events = db.list_events_for_today(participant["id"])
    already = db.get_checkin_submission(participant["id"], day)

    rows_html = "".join(_email_row_html(e) for e in events) or (
        '<p style="color:#8a887f; font-size:14px;">No emails yet today — check back later.</p>'
    )

    if already:
        body_html = f"""
        <div style="background:#fff; border:1px solid #E8E6DD; border-radius:12px; padding:24px; margin-top:20px;">
          <div style="font-size:15px;">Thanks — you already submitted feedback for Day {day}.</div>
          <div style="font-size:13px; color:#8a887f; margin-top:6px;">Come back tomorrow for Day {day + 1}.</div>
        </div>
        """
    else:
        body_html = _form_html(token, events)

    return HTMLResponse(f"""
<!doctype html>
<html><head><meta charset="utf-8"><title>Day {day} check-in</title>
<style>
  body{{font-family:-apple-system,system-ui,sans-serif; background:#FAF9F5; color:#141413;
       max-width:640px; margin:0 auto; padding:48px 20px 80px;}}
  h1{{font-family:Georgia,serif; font-weight:400; font-size:28px; margin:0 0 6px;}}
  .eyebrow{{font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:#8a887f; font-weight:600;}}
  .row{{display:flex; align-items:center; gap:10px; padding:12px 0; border-bottom:1px solid #ECE9E1;}}
  .row:last-child{{border-bottom:none;}}
  .badge{{font-size:11.5px; font-weight:700; padding:3px 10px; border-radius:999px; width:76px; text-align:center; flex-shrink:0;}}
  .pill{{cursor:pointer; border:1px solid #d8d5cb; background:#fff; font-size:12.5px; font-weight:600; padding:5px 12px; border-radius:999px;}}
  .pill.on-yes{{background:#E9F5EC; border-color:#2E7D46; color:#2E7D46;}}
  .pill.on-no{{background:#F5E4E4; border-color:#A6432E; color:#A6432E;}}
  .num{{cursor:pointer; width:30px; height:30px; border-radius:7px; border:1px solid #d8d5cb; background:#fff;
       font-size:13px; font-weight:600; color:#3d3c39; display:inline-flex; align-items:center; justify-content:center;}}
  .num.on{{background:#141413; border-color:#141413; color:#FAF9F5;}}
  textarea{{width:100%; box-sizing:border-box; border:1px solid #d8d5cb; border-radius:8px; padding:10px 12px;
           font-size:13.5px; font-family:inherit; resize:vertical; min-height:64px;}}
  button.submit{{background:#D97757; color:#FAF9F5; border:none; border-radius:8px; padding:12px 26px;
                font-size:14.5px; font-weight:600; cursor:pointer;}}
  a{{color:#D97757; text-decoration:none;}}
</style>
</head>
<body>
  <div class="eyebrow">Email assistant study</div>
  <h1>Day {day} — {participant['email']}</h1>
  <p style="font-size:15px; color:#3d3c39; line-height:1.55;">
    You received <strong>{len(events)}</strong> email{'s' if len(events) != 1 else ''} today.
    Check your Drafts folder and Calendar, then let us know how it went.
  </p>
  {rows_html}
  {body_html}
<script>
function selectPill(btn, group) {{
  group.forEach(b => b.classList.remove('on-yes', 'on-no'));
}}
</script>
</body></html>
""")


def _email_row_html(e) -> str:
    color, bg = CATEGORY_STYLE.get(e["category"], DEFAULT_STYLE)
    status = STATUS_LABEL.get(e["handler_used"], e["handler_used"] or "—")
    subject = e["subject"] or "(no subject)"
    return f"""
    <div class="row">
      <div class="badge" style="color:{color}; background:{bg};">{e['category'] or '—'}</div>
      <div style="flex-grow:1; font-size:14px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">{subject}</div>
      <div style="font-size:12.5px; color:#6B6A66; flex-shrink:0;">{status}</div>
      <a href="{_gmail_link(e['gmail_id'])}" target="_blank" style="font-size:12.5px; font-weight:600; flex-shrink:0;">Open in Gmail ↗</a>
    </div>
    """


def _form_html(token: str, events) -> str:
    if not events:
        return ""

    per_email_rows = ""
    for e in events:
        eid = e["id"]
        subject = e["subject"] or "(no subject)"
        per_email_rows += f"""
        <div class="row" data-email-id="{eid}">
          <div style="flex-grow:1; font-size:13.5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
            {subject} <span style="color:#8a887f;">— {e['category'] or '—'}</span>
          </div>
          <button type="button" class="pill" onclick="markCorrect('{eid}', true, this)">Correct</button>
          <button type="button" class="pill" onclick="markCorrect('{eid}', false, this)">Wrong</button>
        </div>
        """

    num_buttons = "".join(
        f'<div class="num" onclick="setRating({n}, this)">{n}</div>' for n in range(1, 11)
    )

    return f"""
  <div style="margin-top:24px; display:flex; flex-direction:column; gap:18px;">
    <div>
      <div style="font-size:13.5px; font-weight:600; color:#3d3c39; margin-bottom:6px;">Was each email classified correctly?</div>
      {per_email_rows}
    </div>
    <div>
      <div style="font-size:13.5px; font-weight:600; color:#3d3c39; margin-bottom:8px;">Overall, how good were today's drafted replies?</div>
      <div style="display:flex; gap:6px; align-items:center;">
        <span style="font-size:12px; color:#8a887f;">Poor</span>
        {num_buttons}
        <span style="font-size:12px; color:#8a887f;">Excellent</span>
      </div>
    </div>
    <div>
      <label for="notes" style="font-size:13.5px; font-weight:600; color:#3d3c39; display:block; margin-bottom:6px;">Anything else you noticed? (optional)</label>
      <textarea id="notes" placeholder="e.g. the meeting time it proposed was off by an hour..."></textarea>
    </div>
    <button class="submit" onclick="submitFeedback('{token}')">Submit today's feedback</button>
    <div id="result" style="font-size:13.5px;"></div>
  </div>
<script>
  const perEmail = {{}};
  let rating = null;

  function markCorrect(id, correct, btn) {{
    perEmail[id] = correct;
    const row = btn.closest('.row');
    row.querySelectorAll('.pill').forEach(b => b.classList.remove('on-yes', 'on-no'));
    btn.classList.add(correct ? 'on-yes' : 'on-no');
  }}

  function setRating(n, el) {{
    rating = n;
    document.querySelectorAll('.num').forEach(b => b.classList.remove('on'));
    el.classList.add('on');
  }}

  async function submitFeedback(token) {{
    const per_email = Object.entries(perEmail).map(([email_event_id, correct]) => ({{email_event_id, correct}}));
    const res = await fetch(`/checkin/${{token}}/submit`, {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{overall_rating: rating, notes: document.getElementById('notes').value, per_email}})
    }});
    const el = document.getElementById('result');
    el.textContent = res.ok ? 'Thanks! See you tomorrow.' : 'Something went wrong — please try again.';
    el.style.color = res.ok ? '#2E7D46' : '#A6432E';
  }}
</script>
"""


@router.post("/checkin/{token}/submit")
def submit_checkin(token: str, submission: CheckinSubmission):
    participant = db.get_participant_by_checkin_token(token)
    if participant is None:
        raise HTTPException(404, "Check-in link not recognized")

    day = db.day_number_for(participant["id"])
    db.save_checkin_submission(
        participant_id=participant["id"],
        day_number=day,
        overall_rating=submission.overall_rating,
        notes=submission.notes,
        # .dict() rather than .model_dump(): works on both pydantic v1 and
        # v2 (deprecated-but-functional shim on v2) — avoids assuming
        # which major version ended up installed.
        per_email=[pe.dict() for pe in submission.per_email],
    )
    return {"status": "saved", "day": day}
