"""HTTP interface: email routing plus the operator's meeting confirmation.

The /pending endpoints are the only route by which anything is written to
the calendar. They are for the mailbox owner, not for email senders: run
the server bound to localhost (uvicorn's default, 127.0.0.1) and do not
expose it publicly. Confirmation tokens are never included in email drafts.
"""
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app import pending
from app.graph import build_graph
from app.handlers.calendar import insert_event

app = FastAPI(title="Adaptive Email Router")
graph = build_graph()


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
    classify_latency_ms: Optional[float] = None
    confirmation_token: Optional[str] = None


class PendingMeeting(BaseModel):
    token: str
    email_id: Optional[str]
    sender: Optional[str]
    subject: Optional[str]
    start_iso: str
    end_iso: str
    timezone: str
    time_source: str
    status: str
    event_id: Optional[str]
    event_link: Optional[str]
    created_at: float
    resolved_at: Optional[float]


class Decision(BaseModel):
    meeting: PendingMeeting
    already_done: bool   # true when this call repeated an earlier decision


@app.post("/route-email", response_model=EmailResponse)
def route_email(email: EmailRequest):
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
        "confirmation_token": None,
    })
    return result


@app.get("/pending", response_model=list[PendingMeeting])
def list_pending(status: Optional[str] = "pending"):
    """Meetings awaiting a decision. ?status=confirmed|cancelled, or ?status=all."""
    if status == "all":
        status = None
    elif status not in pending.STATUSES:
        raise HTTPException(400, f"status must be one of {pending.STATUSES} or 'all'")
    return pending.list_records(status)


@app.get("/pending/{token}", response_model=PendingMeeting)
def get_pending(token: str):
    try:
        return pending.get(token)
    except pending.NotFound:
        raise HTTPException(404, "no such meeting proposal")


@app.post("/pending/{token}/confirm", response_model=Decision)
def confirm_pending(token: str):
    """The only calendar write. Idempotent: confirming twice returns the
    same event and does not create a second one."""
    try:
        record, already = pending.confirm(token, insert_event)
    except pending.NotFound:
        raise HTTPException(404, "no such meeting proposal")
    except pending.Conflict as e:
        raise HTTPException(409, str(e))
    return {"meeting": record, "already_done": already}


@app.post("/pending/{token}/cancel", response_model=Decision)
def cancel_pending(token: str):
    try:
        record, already = pending.cancel(token)
    except pending.NotFound:
        raise HTTPException(404, "no such meeting proposal")
    except pending.Conflict as e:
        raise HTTPException(409, str(e))
    return {"meeting": record, "already_done": already}


@app.get("/health")
def health():
    return {"status": "ok"}
