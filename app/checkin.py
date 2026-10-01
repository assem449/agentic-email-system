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
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app import db
from app.google_auth import account_chooser_url
from app.handlers.calendar import create_approved_event

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

# Backs the "What do these mean?" side drawer — one entry per category
# the classifier actually uses (app/classifier.py / app/graph.py),
# described in plain terms with a representative example.
CATEGORY_INFO = [
    ("ack", "A short acknowledgment with nothing left to answer, like a thank-you. "
            "Answered instantly from a template, no AI involved.",
     "“Thanks so much!”"),
    ("faq", "A common question that matches one already in the knowledge base, "
            "answered instantly, or passed to the AI if nothing matches closely.",
     "“What are your support hours?”"),
    ("meeting", "A request to schedule a call or meeting. Your real calendar is checked "
                "for a free slot, but nothing is ever booked until you approve it yourself.",
     "“Can we grab 30 minutes tomorrow afternoon?”"),
    ("support", "An account or product issue that needs a specific, helpful reply, "
                "drafted by the AI (and reused if the same question comes up again).",
     "“My export keeps failing, can you help?”"),
    ("emotional", "A frustrated or upset message. The AI drafts an empathetic reply "
                  "rather than a purely procedural one.",
     "“This is so frustrating, nothing is working!”"),
    ("ambiguous", "Doesn't fit cleanly into another category, so the AI drafts a reply "
                  "case by case.",
     "“Following up on my email from last week.”"),
    ("spam", "Looks like spam or phishing. Blocked automatically — no draft, no reply.",
     "“You've won a prize, claim it now!”"),
]

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
    """A Gmail link targeted at a specific account. See
    account_chooser_url (app.google_auth) for why this wrapping exists
    at all — used for Gmail URLs specifically here."""
    return account_chooser_url(email, f"https://mail.google.com/mail/u/0/{continue_fragment}")


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
  font-family:'Open Sans',-apple-system,system-ui,sans-serif;
  background:#F1F3F4; color:#1A1A18; padding:56px 20px 40px;
}
/* Two columns side by side on a wide viewport (main content + the
   always-visible category sidebar), wrapping to a stacked single
   column on a narrow one — no media query needed, flex-wrap handles it. */
.wrap{width:100%; max-width:900px; display:flex; gap:26px; align-items:flex-start; flex-wrap:wrap;}
.main-col{flex:1 1 480px; min-width:320px; max-width:520px;}

/* --- simulated inbox backdrop: a Gmail-inspired look, real data, not a
   real Gmail embed (Google blocks iframing gmail.com anyway) --- */
.gmail-panel{
  background:#fff; border-radius:16px; overflow:hidden;
  box-shadow:0 2px 10px rgba(0,0,0,0.07);
  animation:fadeIn .4s ease-out;
}
.gmail-topbar{
  display:flex; align-items:center; gap:10px; padding:16px 22px;
  border-bottom:1px solid #EDEDED; font-size:15px; font-weight:600; color:#3c4043;
}
.gmail-dot{width:11px; height:11px; border-radius:50%; background:#EA4335; flex-shrink:0;}
.view-gmail-btn{
  margin-left:auto; display:inline-flex; align-items:center; gap:6px; background:#fff; border:1px solid #DADCE0;
  color:#3c4043; font-size:12.5px; font-weight:600; padding:7px 14px; border-radius:999px; transition:all .2s ease;
}
.view-gmail-btn:hover{background:#F8F9FA; border-color:#C4C7C9;}
.gmail-row{
  display:flex; align-items:center; gap:12px; padding:13px 22px;
  border-bottom:1px solid #F1F1F1; text-decoration:none; color:inherit; transition:background .18s ease;
}
.gmail-row:last-child{border-bottom:none;}
.gmail-row:hover{background:#F8F9FA;}
.gmail-chip{font-size:11.5px; font-weight:700; padding:3px 10px; border-radius:999px; width:78px; text-align:center; flex-shrink:0;}
.gmail-subject{flex-grow:1; font-size:14px; color:#202124; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
.gmail-status{font-size:12.5px; color:#80868b; flex-shrink:0;}
.gmail-empty{padding:26px 22px; font-size:14px; color:#80868b; text-align:center;}

/* --- the popup card, stacked below the inbox panel, not overlapping it --- */
.card{
  background:#fff; border-radius:22px; position:relative;
  margin:20px 0 0; padding:34px 30px 32px;
  box-shadow:0 24px 60px rgba(20,20,19,0.18), 0 2px 8px rgba(20,20,19,0.08);
  animation:popIn .45s cubic-bezier(.16,1,.3,1) .12s both;
}
@keyframes fadeIn{from{opacity:0; transform:translateY(4px);} to{opacity:1; transform:translateY(0);}}
@keyframes popIn{from{opacity:0; transform:scale(.94) translateY(14px);} to{opacity:1; transform:scale(1) translateY(0);}}
.close{
  position:absolute; top:18px; right:18px; width:30px; height:30px; border-radius:50%;
  background:#F4F2EC; border:none; display:flex; align-items:center; justify-content:center;
  cursor:pointer; color:#8a887f; text-decoration:none; font-size:16px; transition:background .2s ease;
}
.close:hover{background:#EAE7DD;}
.eyebrow{font-size:12px; letter-spacing:.06em; text-transform:uppercase; color:#a6a39a; font-weight:600; margin-bottom:7px;}
h1{margin:0 0 5px; font-size:25px; font-weight:700; line-height:1.25;}
.sub{font-size:14px; color:#8a887f; margin-bottom:16px;}
.lead{font-size:15px; color:#57544C; line-height:1.6; margin-bottom:6px;}
.row{display:flex; align-items:center; gap:10px; padding:12px 0; border-bottom:1px solid #F0EEE7;}
.row:last-child{border-bottom:none;}
.pill{cursor:pointer; border:1px solid #E5E2D9; background:#fff; font-size:12.5px; font-weight:600;
      padding:6px 14px; border-radius:999px; transition:all .2s ease;}
.pill:hover{border-color:#D6D2C4;}
.pill.on-yes{background:#E9F5EC; border-color:#2E7D46; color:#2E7D46;}
.pill.on-no{background:#F5E4E4; border-color:#A6432E; color:#A6432E;}
.num{cursor:pointer; width:32px; height:32px; border-radius:9px; border:1px solid #E5E2D9; background:#fff;
     font-size:13.5px; font-weight:600; color:#57544C; display:inline-flex; align-items:center; justify-content:center;
     transition:all .2s ease;}
.num:hover{border-color:#D6D2C4;}
.num.on{background:#1A1A18; border-color:#1A1A18; color:#fff;}
.section-label{font-size:14px; font-weight:600; color:#3d3c39; margin-bottom:9px;}
.meeting-card{background:#FAF9F6; border:1px solid #EDEAE1; border-radius:14px; padding:16px 18px; margin-bottom:12px;}
.approve-btn{cursor:pointer; border:none; background:#2F6FED; color:#fff; font-size:13px; font-weight:600;
             padding:9px 18px; border-radius:9px; transition:background .2s ease;}
.approve-btn:hover{background:#2558BE;}
.approve-btn:disabled, .reject-btn:disabled{opacity:.5; cursor:default;}
.reject-btn{cursor:pointer; border:1px solid #E5E2D9; background:#fff; color:#57544C; font-size:13px; font-weight:600;
            padding:9px 18px; border-radius:9px; transition:all .2s ease;}
.reject-btn:hover{border-color:#D6D2C4;}
textarea{width:100%; border:1px solid #E5E2D9; border-radius:11px; padding:11px 14px;
         font-size:14px; font-family:inherit; resize:vertical; min-height:68px; transition:border-color .2s ease;}
textarea:focus{outline:none; border-color:#2F6FED;}
button.submit{background:#2F6FED; color:#fff; border:none; border-radius:11px; padding:13px 26px;
              font-size:15px; font-weight:600; cursor:pointer; transition:background .2s ease; width:100%;}
button.submit:hover{background:#2558BE;}
a{color:#2F6FED; text-decoration:none;}
.done{background:#FAF9F6; border-radius:16px; padding:22px; margin-top:16px; text-align:center;}
.done .big{font-size:24px; margin-bottom:7px;}
.result{font-size:14px; margin-top:10px; text-align:center; min-height:16px;}

.header-links{display:flex; gap:16px; margin-bottom:14px;}
.link-btn{background:none; border:none; color:#2F6FED; font-size:13px; font-weight:600; cursor:pointer; padding:0;}
.link-btn:hover{text-decoration:underline;}

/* --- always-visible category sidebar, next to the main column --- */
.sidebar{
  flex:1 1 300px; min-width:280px; max-width:340px; background:#fff; border-radius:18px;
  box-shadow:0 2px 10px rgba(0,0,0,0.07); padding:28px 24px; align-self:flex-start;
  animation:fadeIn .4s ease-out;
}
.sidebar h2{font-size:17px; margin:0 0 20px; font-weight:700;}
.cat-item{margin-bottom:22px;}
.cat-item:last-child{margin-bottom:0;}
.cat-badge{font-size:11.5px; font-weight:700; padding:3px 11px; border-radius:999px; display:inline-block; margin-bottom:8px;}
.cat-desc{font-size:13.5px; color:#57544C; line-height:1.6; margin-bottom:8px;}
.cat-example{font-size:13px; color:#8a887f; font-style:italic; background:#FAF9F6; border-radius:9px; padding:9px 12px;}

/* --- welcome modal: auto-opened on Day 1 only, reopenable from the header link --- */
.welcome-overlay{
  position:fixed; inset:0; background:rgba(26,26,24,.45); display:flex; align-items:center; justify-content:center;
  padding:20px; opacity:0; pointer-events:none; transition:opacity .25s ease; z-index:60;
}
.welcome-overlay.open{opacity:1; pointer-events:auto;}
.welcome-modal{
  background:#fff; border-radius:20px; max-width:440px; width:100%; padding:34px 30px; max-height:85vh; overflow-y:auto;
  box-shadow:0 30px 80px rgba(0,0,0,.25); transform:scale(.95); transition:transform .25s cubic-bezier(.16,1,.3,1);
}
.welcome-overlay.open .welcome-modal{transform:scale(1);}
.welcome-modal h2{font-size:21px; margin:0 0 14px; font-weight:700;}
.welcome-modal p{font-size:14px; color:#57544C; line-height:1.6; margin:0 0 14px;}
.welcome-modal ul{margin:0 0 18px; padding-left:20px;}
.welcome-modal li{font-size:14px; color:#57544C; line-height:1.6; margin-bottom:7px;}
"""


@router.get("/checkin/{token}", response_class=HTMLResponse)
def checkin_page(token: str):
    participant = db.get_participant_by_checkin_token(token)
    if participant is None:
        raise HTTPException(404, "This check-in link isn't recognized. It may have been disconnected.")

    day = db.day_number_for(participant["id"])
    events = db.list_events_for_today(participant["id"])
    already = db.get_checkin_submission(participant["id"], day)
    show_welcome = day == 1 and not participant["welcomed_at"]

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
<link href="https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{PAGE_STYLE}</style>
</head>
<body>
  <div class="wrap">
    <div class="main-col">
      {_gmail_panel_html(events, participant['email'])}
      <div class="card">
        <a class="close" href="{_google_link(participant['email'], '#inbox')}" title="Back to inbox">&times;</a>
        <div class="eyebrow">Email assistant study</div>
        <h1>Day {day}</h1>
        <div class="sub">{participant['email']}</div>
        <div class="header-links">
          <button type="button" class="link-btn" onclick="openWelcome()">About this study</button>
        </div>
        <div class="lead">You received <strong>{n}</strong> email{'s' if n != 1 else ''} today. Here's a peek above, check your real Drafts and Calendar too, then let us know how it went.</div>
        {_pending_events_html(token, participant["id"])}
        {body_html}
      </div>
    </div>
    {_category_sidebar_html()}
  </div>
  {_welcome_modal_html(token, show_welcome)}
<script>
  function openWelcome() {{
    document.getElementById('welcome-overlay').classList.add('open');
  }}
  async function dismissWelcome(token) {{
    document.getElementById('welcome-overlay').classList.remove('open');
    fetch(`/checkin/${{token}}/welcome-seen`, {{method: 'POST'}}).catch(() => {{}});
  }}
</script>
</body></html>
""")


def _pending_events_html(token: str, participant_id: str) -> str:
    """Meeting proposals awaiting this participant's own approval —
    scoped so they only ever see and act on their own. Approving calls
    create_approved_event() immediately: the real Calendar event is
    created right away, no researcher involved. A researcher can still
    act on the same proposal from /admin — whichever happens first wins,
    the other 404s on an already-decided row."""
    pending = db.list_pending_events_for_participant(participant_id)
    if not pending:
        return ""

    cards = ""
    for p in pending:
        try:
            when = datetime.fromisoformat(p["proposed_start"]).strftime("%A, %b %d at %I:%M %p")
        except ValueError:
            when = p["proposed_start"]
        subject = p["subject"] or "(no subject)"
        moved_note = (
            '<div style="font-size:12px; color:#a6a39a; margin-top:4px;">'
            "Your requested time was busy, so this is the next open slot.</div>"
            if p["time_adjusted"] else ""
        )
        cards += f"""
        <div class="meeting-card" data-event-id="{p['id']}">
          <div style="font-size:13.5px; font-weight:600;">{subject}</div>
          <div style="font-size:12.5px; color:#8a887f; margin-top:2px;">From {p['sender']}</div>
          <div style="font-size:13.5px; margin-top:8px;">📅 {when}</div>
          {moved_note}
          <div style="display:flex; gap:8px; margin-top:12px;">
            <button type="button" class="approve-btn" onclick="decideEvent('{token}','{p['id']}','approve',this)">Approve</button>
            <button type="button" class="reject-btn" onclick="decideEvent('{token}','{p['id']}','reject',this)">Reject</button>
          </div>
          <div class="meeting-result"></div>
        </div>
        """

    return f"""
    <div style="margin-top:18px;">
      <div class="section-label">Meeting requests awaiting your approval</div>
      {cards}
    </div>
<script>
  async function decideEvent(token, eventId, action, btn) {{
    const card = btn.closest('.meeting-card');
    card.querySelectorAll('button').forEach(b => b.disabled = true);
    const res = await fetch(`/checkin/${{token}}/pending/${{eventId}}/${{action}}`, {{method: 'POST'}});
    const data = await res.json().catch(() => ({{}}));
    const resultEl = card.querySelector('.meeting-result');
    if (res.ok && action === 'approve') {{
      resultEl.innerHTML = `Added to your calendar. <a href="${{data.calendar_event_link}}" target="_blank">View it</a>`;
      resultEl.style.color = '#2E7D46';
    }} else if (res.ok) {{
      resultEl.textContent = 'Declined, no event created.';
      resultEl.style.color = '#8a887f';
    }} else {{
      resultEl.textContent = 'Something went wrong, please try again.';
      resultEl.style.color = '#A6432E';
      card.querySelectorAll('button').forEach(b => b.disabled = false);
    }}
    resultEl.style.marginTop = '8px';
    resultEl.style.fontSize = '13px';
  }}
</script>
"""


def _category_sidebar_html() -> str:
    """Always-visible reference panel next to the main column, explaining
    what each classification category means and how it's handled, with
    an example. Static content, same for every participant and every
    day — no toggle needed, it's just always there."""
    items = ""
    for category, description, example in CATEGORY_INFO:
        color, bg = CATEGORY_STYLE.get(category, DEFAULT_STYLE)
        items += f"""
        <div class="cat-item">
          <div class="cat-badge" style="color:{color}; background:{bg};">{category}</div>
          <div class="cat-desc">{description}</div>
          <div class="cat-example">{example}</div>
        </div>
        """
    return f"""
    <div class="sidebar">
      <h2>What do these categories mean?</h2>
      {items}
    </div>
    """


def _welcome_modal_html(token: str, auto_open: bool) -> str:
    """First-day welcome screen, explaining what the study is and what
    to expect. Auto-shown only once (day 1, before welcomed_at is set —
    see app.db.mark_welcomed); reopenable anytime afterward from the
    'About this study' link, which just toggles the same modal without
    re-marking anything."""
    open_class = " open" if auto_open else ""
    return f"""
    <div class="welcome-overlay{open_class}" id="welcome-overlay">
      <div class="welcome-modal">
        <h2>Welcome to the study 👋</h2>
        <p>
          You're helping test an assistant that reads unread emails in this inbox, figures out
          what kind of message each one is, and drafts a reply, all without sending anything on
          its own.
        </p>
        <p>Here's exactly what it does, and doesn't do:</p>
        <ul>
          <li>Drafts a reply to most emails and saves it to your Drafts folder. Nothing is ever sent automatically, you decide if and when to send each one.</li>
          <li>For meeting requests, it checks your real calendar for a free time and proposes it, but never books anything until you approve it yourself, right here on this page.</li>
          <li>Obvious spam gets blocked automatically.</li>
        </ul>
        <p>
          Each day, come back to this page to see what happened with today's emails, approve or
          reject any meeting proposals, and give quick feedback, it only takes a minute or two.
        </p>
        <p style="font-size:12.5px; color:#a6a39a;">
          This is a research study, not your personal inbox. Nothing you do here is shared outside
          the study team.
        </p>
        <button class="submit" onclick="dismissWelcome('{token}')">Let's get started</button>
      </div>
    </div>
    """


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
      <div class="gmail-topbar">
        <span class="gmail-dot"></span> Inbox
        <a class="view-gmail-btn" href="{_google_link(email, '#inbox')}" target="_blank">View in Gmail ↗</a>
      </div>
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


@router.post("/checkin/{token}/pending/{event_id}/approve")
def approve_pending_self(token: str, event_id: str):
    """Participant-initiated approval, from their own check-in page.
    Creates the real calendar event immediately — see
    app.handlers.calendar.create_approved_event. Scoped to the
    participant behind `token`: a pending row that exists but belongs
    to someone else, or isn't pending anymore (already decided here or
    on /admin), 404s the same as a row that doesn't exist at all."""
    participant = db.get_participant_by_checkin_token(token)
    if participant is None:
        raise HTTPException(404, "Check-in link not recognized")

    row = db.get_pending_event(event_id)
    if row is None or row["participant_id"] != participant["id"] or row["status"] != "pending":
        raise HTTPException(404, "No such pending meeting request")

    link = create_approved_event(participant["id"], row)
    db.decide_pending_event(event_id, "approved", link)
    # Google's htmlLink doesn't target any account on its own — wrap it
    # the same way as the Gmail links above, or it opens whatever
    # account is session index 0 in the browser instead of this one.
    return {"status": "approved", "calendar_event_link": account_chooser_url(participant["email"], link)}


@router.post("/checkin/{token}/pending/{event_id}/reject")
def reject_pending_self(token: str, event_id: str):
    participant = db.get_participant_by_checkin_token(token)
    if participant is None:
        raise HTTPException(404, "Check-in link not recognized")

    row = db.get_pending_event(event_id)
    if row is None or row["participant_id"] != participant["id"] or row["status"] != "pending":
        raise HTTPException(404, "No such pending meeting request")

    db.decide_pending_event(event_id, "rejected")
    return {"status": "rejected"}


@router.post("/checkin/{token}/welcome-seen")
def mark_welcome_seen(token: str):
    """Called once the first time the Day 1 welcome modal is dismissed,
    so it stops auto-showing on later visits. Reopening it later via
    the 'About this study' link doesn't call this again — it's already
    marked, and calling it again is harmless either way (just a no-op
    timestamp update), so no special-casing needed there."""
    participant = db.get_participant_by_checkin_token(token)
    if participant is None:
        raise HTTPException(404, "Check-in link not recognized")
    db.mark_welcomed(participant["id"])
    return {"status": "ok"}


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
