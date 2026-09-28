import threading
import uuid

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional

from app import db
from app.config import ADMIN_TOKEN, POLL_INTERVAL_SECONDS
from app.graph import build_graph
from app.handlers.calendar import create_approved_event
from app.oauth_web import router as oauth_router
from app.poller import run_poller

app = FastAPI(title="Adaptive Email Router")
app.include_router(oauth_router)
graph = build_graph()


@app.on_event("startup")
def _startup():
    db.init_db()
    # Blocking Google API calls, so a plain background thread rather than
    # an asyncio task — this is a study-scale deployment (dozens of
    # participants polled every ~30s), not something that needs to scale
    # past a single worker.
    threading.Thread(
        target=run_poller, args=(POLL_INTERVAL_SECONDS,), daemon=True
    ).start()


class EmailRequest(BaseModel):
    sender: str
    subject: str
    body: str


class EmailResponse(BaseModel):
    email_id: str
    category: str
    handler_used: str
    response: str
    tokens_used: Optional[int]
    latency_ms: Optional[float]


@app.post("/route-email", response_model=EmailResponse)
def route_email(email: EmailRequest):
    """Account-free path: classify/draft one email with no Gmail
    connection at all — this is the backing endpoint for the
    'simulated form' study UI option (paste or pick a sample email, see
    the classification + drafted reply)."""
    result = graph.invoke({
        "email_id": str(uuid.uuid4()),
        "sender": email.sender,
        "subject": email.subject,
        "body": email.body,
        "category": None,
        "handler_used": None,
        "response": None,
        "tokens_used": None,
        "latency_ms": None,
        "participant_id": None,
        "gmail_id": None,
    })
    return result


@app.get("/health")
def health():
    return {"status": "ok"}


# --- human-in-the-loop review (placeholder UI — swap out freely) ---------
#
# Meeting-classified emails never book a calendar event on their own; they
# land here as a pending proposal until a reviewer approves or rejects it.
# Auth is a single shared header token, deliberately minimal for a small
# study — replace with real per-reviewer auth before this goes wider.

def _require_admin(x_admin_token: Optional[str]):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "bad or missing X-Admin-Token header")


@app.get("/admin/pending")
def list_pending(x_admin_token: Optional[str] = Header(None)):
    _require_admin(x_admin_token)
    rows = db.list_pending_events("pending")
    return [dict(r) for r in rows]


@app.post("/admin/pending/{event_id}/approve")
def approve_pending(event_id: str, x_admin_token: Optional[str] = Header(None)):
    _require_admin(x_admin_token)
    row = db.get_pending_event(event_id)
    if row is None or row["status"] != "pending":
        raise HTTPException(404, "no such pending event")

    link = create_approved_event(row["participant_id"], row)
    db.decide_pending_event(event_id, "approved", link)
    return {"status": "approved", "calendar_event_link": link}


@app.post("/admin/pending/{event_id}/reject")
def reject_pending(event_id: str, x_admin_token: Optional[str] = Header(None)):
    _require_admin(x_admin_token)
    row = db.get_pending_event(event_id)
    if row is None or row["status"] != "pending":
        raise HTTPException(404, "no such pending event")

    db.decide_pending_event(event_id, "rejected")
    return {"status": "rejected"}


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    """Bare-bones review page — a placeholder until the real study UI is
    designed. Prompts for the admin token client-side and calls the
    /admin/pending* JSON endpoints above."""
    return """
<!doctype html><html><head><meta charset="utf-8"><title>Pending meeting proposals</title>
<style>
  body{font-family:-apple-system,system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 16px;color:#141413}
  .card{border:1px solid #ddd;border-radius:8px;padding:16px;margin-bottom:12px}
  button{margin-right:8px;padding:6px 14px;border-radius:6px;border:1px solid #ccc;cursor:pointer}
  .approve{background:#e9f5ec}
  .reject{background:#f5e4e4}
</style></head>
<body>
<h2>Pending meeting proposals</h2>
<p><small>Enter the admin token once; it's kept only in this tab.</small></p>
<input id="tok" type="password" placeholder="admin token" style="width:100%;padding:8px;margin-bottom:16px">
<div id="list">Loading…</div>
<script>
const tok = () => document.getElementById('tok').value;
async function load() {
  const res = await fetch('/admin/pending', {headers: {'X-Admin-Token': tok()}});
  const items = res.ok ? await res.json() : [];
  const el = document.getElementById('list');
  el.innerHTML = items.length ? '' : '<p>No pending proposals.</p>';
  for (const it of items) {
    const div = document.createElement('div');
    div.className = 'card';
    div.innerHTML = `<div><b>${it.subject || '(no subject)'}</b></div>
      <div><small>${it.sender}</small></div>
      <div style="margin:8px 0">${it.reply_preview}</div>
      <div><small>Proposed: ${it.proposed_start} – ${it.proposed_end}</small></div>
      <div style="margin-top:10px">
        <button class="approve" onclick="decide('${it.id}','approve')">Approve</button>
        <button class="reject" onclick="decide('${it.id}','reject')">Reject</button>
      </div>`;
    el.appendChild(div);
  }
}
async function decide(id, action) {
  await fetch(`/admin/pending/${id}/${action}`, {method: 'POST', headers: {'X-Admin-Token': tok()}});
  load();
}
document.getElementById('tok').addEventListener('change', load);
load();
</script>
</body></html>
"""
