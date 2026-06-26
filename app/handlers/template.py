import time
from app.state import EmailState

TEMPLATES = {
    "default": "You're welcome! Let me know if there's anything else I can help with.",
    "thanks": "Glad I could help! Reach out anytime.",
    "ok": "Got it, thanks for confirming!",
}

def select_template(body: str) -> str:
    text = body.lower().strip()
    if "thank" in text:
        return TEMPLATES["thanks"]
    if text in ("ok", "ok!", "okay"):
        return TEMPLATES["ok"]
    return TEMPLATES["default"]

def template_handler(state: EmailState) -> EmailState:
    start = time.perf_counter()

    response = select_template(state["body"])

    state["handler_used"] = "template"
    state["response"] = response
    state["tokens_used"] = 0  # no LLM call
    state["latency_ms"] = (time.perf_counter() - start) * 1000

    return state