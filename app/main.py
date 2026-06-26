import uuid
from fastapi import FastAPI
from pydantic import BaseModel
from app.graph import build_graph
from typing import Optional

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
    })
    return result

@app.get("/health")
def health():
    return {"status": "ok"}