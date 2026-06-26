import json
import time
from pathlib import Path
from app.state import EmailState

LOG_PATH = Path(__file__).parent.parent / "logs" / "routing_log.jsonl"
LOG_PATH.parent.mkdir(exist_ok=True)

def log_routing_decision(state: EmailState) -> EmailState:
    record = {
        "timestamp": time.time(),
        "email_id": state.get("email_id"),
        "category": state.get("category"),
        "handler_used": state.get("handler_used"),
        "tokens_used": state.get("tokens_used"),
        "latency_ms": state.get("latency_ms"),
        "response_preview": (state.get("response") or "")[:200],
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")
    return state