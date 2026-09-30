"""Daily participant check-in page.

Each participant gets one private, unguessable link (their `checkin_token`,
shown once on the post-OAuth "Connected" page, see app/oauth_web.py).
Visiting it shows what the pipeline did with today's emails and collects
their feedback: per-email correctness, an overall draft-quality rating,
and free-text notes.

Styled as a centered popup-style card (not a full document page) so it
feels closer to something that appears when a participant opens their
study inbox, rather than a separate site they navigate to. Still a
single self-contained HTML response, no framework, no build step, easy
to swap out once a real study UI is decided.
"""

import json
from typing import List, Optional
from urllib.parse import quote

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
    "blocked": "Blocked as spam",
}


def _google_link(email: str, continue_fragment: str) -> str:
    """A link to a specific Google account's Gmail, not just whatever
    account happens to be session index 0 in the browser (a participant
    signed into their real account too will otherwise get bounced there
    instead of their study account). AccountChooser switches to `email`
    first if it's signed in, or prompts sign-in if it isn't, then
    continues to the given Gmail URL."""
    continue_url = f"https://mail.google.com/mail/u/0/{continue_fragment}"
    return (
        "https://accounts.google.com/AccountChooser"
        f"?Email={quote(email)}&continue={quote(continue_url, safe='')}"
    )


def _gmail_link(email: str, gmail_id: str) -> str:
    if not gmail_id:
        return "#"
    return _google_link(email, f"#all/{gmail_id}")


class PerEmailFeedback(BaseModel):
    email_event_id: str
    correct: bool


class CheckinSubmission(BaseModel):
    overall_rating: Optional[int] = None
    notes: str = ""
    per_email: List[PerEmailFeedback] = []


PAGE_STYLE = """
*{box-sizing:border-box;}
body{
  margin:0; min-height:100vh; display:flex; align-items:flex-start; justify-content:center;
  font-family:'Inter',-apple-system,system-ui,sans-serif;
  background:#F1F3F4; color:#1A1A18; padding:56px 20px 40px;
}
.wrap{width:100%; max-width:480px;}

/* --- simulated inbox backdrop: a Gmail-inspired look, real data, not a
   real Gmail embed (Google blocks iframing gmail.com anyway) --- */
.gmail-panel{
  background:#fff; border-radius:12px 12px 0 0; overflow:hidden;
  box-shadow:0 1px 2px rgba(0,0,0,0.08);
}
.gmail-topbar{
  display:flex; align-items:center; gap:10px; padding:14px 20px;
  border-bottom:1px solid #EDEDED; font-size:14px; font-weight:600; color:#3c4043;
}
.gmail-dot{width:10px; height:10px; border-radius:50%; background:#EA4335; flex-shrink:0;}
.gmail-row{
  display:flex; align-items:center; gap:10px; padding:11px 20px;
  border-bottom:1px solid #F1F1F1; text-decoration:none; color:inherit; transition:background .12s;
}
.gmail-row:last-child{border-bottom:none;}
.gmail-row:hover{background:#F8F9FA;}
.gmail-chip{font-size:10.5px; font-weight:700; padding:2px 8px; border-radius:999px; width:70px; text-align:center; flex-shrink:0;}
.gmail-subject{flex-grow:1; font-size:13px; color:#202124; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
.gmail-status{font-size:11.5px; color:#80868b; flex-shrink:0;}
.gmail-empty{padding:24px 20px; font-size:13px; color:#80868b; text-align:center;}

/* --- the popup card, layered over the inbox panel --- */
.card{
  background:#fff; border-radius:20px; position:relative; z-index:2;
  margin:-22px 14px 0; padding:30px 26px 28px;
  box-shadow:0 24px 60px rgba(20,20,19,0.18), 0 2px 8px rgba(20,20,19,0.08);
  animation:popIn .28s cubic-bezier(.2,.8,.2,1);
}
@keyframes popIn{from{opacity:0; transform:scale(.96) translateY(8px);} to{opacity:1; transform:scale(1) translateY(0);}}
.close{
  position:absolute; top:16px; right:16px; width:28px; height:28px; border-radius:50%;
  background:#F4F2EC; border:none; display:flex; align-items:center; justify-content:center;
  cursor:pointer; color:#8a887f; text-decoration:none; font-size:15px; transition:background .15s;
}
.close:hover{background:#EAE7DD;}
.eyebrow{font-size:11.5px; letter-spacing:.06em; text-transform:uppercase; color:#a6a39a; font-weight:600; margin-bottom:6px;}
h1{margin:0 0 4px; font-size:22px; font-weight:700; line-height:1.25;}
.sub{font-size:13px; color:#8a887f; margin-bottom:14px;}
.lead{font-size:14px; color:#57544C; line-height:1.55; margin-bottom:6px;}
.row{display:flex; align-items:center; gap:10px; padding:11px 0; border-bottom:1px solid #F0EEE7;}
.row:last-child{border-bottom:none;}
.pill{cursor:pointer; border:1px solid #E5E2D9; background:#fff; font-size:12px; font-weight:600;
      padding:5px 12px; border-radius:999px; transition:all .15s;}
.pill:hover{border-color:#D6D2C4;}
.pill.on-yes{background:#E9F5EC; border-color:#2E7D46; color:#2E7D46;}
.pill.on-no{background:#F5E4E4; border-color:#A6432E; color:#A6432E;}
.num{cursor:pointer; width:28px; height:28px; border-radius:8px; border:1px solid #E5E2D9; background:#fff;
     font-size:12.5px; font-weight:600; color:#57544C; display:inline-flex; align-items:center; justify-content:center;
     transition:all .15s;}
.num:hover{border-color:#D6D2C4;}
.num.on{background:#1A1A18; border-color:#1A1A18; color:#fff;}
.section-label{font-size:13px; font-weight:600; color:#3d3c39; margin-bottom:8px;}
textarea{width:100%; border:1px solid #E5E2D9; border-radius:10px; padding:10px 12px;
         font-size:13.5px; font-family:inherit; resize:vertical; min-height:60px; transition:border-color .15s;}
textarea:focus{outline:none; border-color:#D97757;}
button.submit{background:#D97757; color:#fff; border:none; border-radius:10px; padding:12px 24px;
              font-size:14px; font-weight:600; cursor:pointer; transition:background .15s; width:100%;}
button.submit:hover{background:#C6653F;}
a{color:#D97757; text-decoration:none;}
.done{background:#FAF9F6; border-radius:14px; padding:20px; margin-top:16px; text-align:center;}
.done .big{font-size:22px; margin-bottom:6px;}
.result{font-size:13px; margin-top:10px; text-align:center; min-height:16px;}
"""


@router.get("/checkin/{token}", response_class=HTMLResponse)
def checkin_page(token: str):
    participant = db.get_participant_by_checkin_token(token)
    if participant is None:
        raise HTTPException(404, "This check-in link isn't recognized. It may have been disconnected.")

    day = db.day_number_for(participant["id"])
    events = db.list_events_for_today(participant["id"])
    already = db.get_checkin_submission(participant["id"], day)

    if already:
        body_html = f"""
        <div class="done">
          <div class="big">🎉</div>
          <div style="font-size:14.5px;">Thanks, you already checked in for Day {day}.</div>
          <div style="font-size:12.5px; color:#a6a39a; margin-top:4px;">Come back tomorrow for Day {day + 1}.</div>
        </div>
        """
    else:
        body_html = _form_html(token, events)

    n = len(events)
    return HTMLResponse(f"""
<!doctype html>
<html><head><meta charset="utf-8"><title>Day {day} check-in</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{PAGE_STYLE}</style>
</head>
<body>
  <div class="wrap">
    {_gmail_panel_html(events, participant['email'])}
    <div class="card">
      <a class="close" href="{_google_link(participant['email'], '#inbox')}" title="Back to inbox">&times;</a>
      <div class="eyebrow">Email assistant study</div>
      <h1>Day {day}</h1>
      <div class="sub">{participant['email']}</div>
      <div class="lead">You received <strong>{n}</strong> email{'s' if n != 1 else ''} today. Here's a peek above, check your real Drafts and Calendar too, then let us know how it went.</div>
      {body_html}
    </div>
  </div>
</body></html>
""")


def _gmail_panel_html(events, email: str) -> str:
    """Backdrop behind the popup card: a Gmail-inspired inbox list built
    from the participant's real processed emails (app.db.email_events).
    Not a live embed of Gmail itself — Google blocks third-party sites
    from iframing mail.google.com — just a look-alike using real data,
    with each row still deep-linking to the actual message."""
    if not events:
        rows = '<div class="gmail-empty">No emails yet today. Check back later.</div>'
    else:
        rows = "".join(_gmail_row_html(e, email) for e in events)

    return f"""
    <div class="gmail-panel">
      <div class="gmail-topbar"><span class="gmail-dot"></span> Inbox</div>
      {rows}
    </div>
    """


def _gmail_row_html(e, email: str) -> str:
    color, bg = CATEGORY_STYLE.get(e["category"], DEFAULT_STYLE)
    status = STATUS_LABEL.get(e["handler_used"], e["handler_used"] or "Processed")
    subject = e["subject"] or "(no subject)"
    return f"""
    <a class="gmail-row" href="{_gmail_link(email, e['gmail_id'])}" target="_blank">
      <div class="gmail-chip" style="color:{color}; background:{bg};">{e['category'] or '...'}</div>
      <div class="gmail-subject">{subject}</div>
      <div class="gmail-status">{status}</div>
    </a>
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
          <div style="flex-grow:1; font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
            {subject} <span style="color:#a6a39a;">· {e['category'] or '...'}</span>
          </div>
          <button type="button" class="pill" onclick="markCorrect('{eid}', true, this)">Correct</button>
          <button type="button" class="pill" onclick="markCorrect('{eid}', false, this)">Wrong</button>
        </div>
        """

    num_buttons = "".join(
        f'<div class="num" onclick="setRating({n}, this)">{n}</div>' for n in range(1, 11)
    )

    return f"""
  <div style="margin-top:20px; display:flex; flex-direction:column; gap:18px;">
    <div>
      <div class="section-label">Was each email classified correctly?</div>
      {per_email_rows}
    </div>
    <div>
      <div class="section-label">How good were today's drafted replies overall?</div>
      <div style="display:flex; gap:5px; align-items:center; flex-wrap:wrap;">
        <span style="font-size:11.5px; color:#a6a39a; margin-right:2px;">Poor</span>
        {num_buttons}
        <span style="font-size:11.5px; color:#a6a39a; margin-left:2px;">Excellent</span>
      </div>
    </div>
    <div>
      <label for="notes" class="section-label" style="display:block;">Anything else you noticed? (optional)</label>
      <textarea id="notes" placeholder="e.g. the meeting time it proposed was off by an hour"></textarea>
    </div>
    <button class="submit" onclick="submitFeedback('{token}')">Submit today's feedback</button>
    <div id="result" class="result"></div>
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
    el.textContent = res.ok ? 'Thanks! See you tomorrow.' : 'Something went wrong, please try again.';
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
        # v2 (deprecated-but-functional shim on v2), avoids assuming
        # which major version ended up installed.
        per_email=[pe.dict() for pe in submission.per_email],
    )
    return {"status": "saved", "day": day}
