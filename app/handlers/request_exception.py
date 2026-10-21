"""request_exception: a short note for the inbox owner, never a reply.

Extensions, regrades, deferrals and other exceptions are decisions only the
person can make, so nothing is written to the sender. One small LLM call
summarises what is being asked; the poller saves it as a Gmail draft
addressed to the participant themselves (in the same thread) and labels
the email AI/Needs review. The same note is shown on the check-in page.
Same behaviour in student and instructor inboxes.
"""

import time
from email.utils import parseaddr

from app.config import LLM_MODEL
from app.handlers.llm import _client
from app.state import EmailState

SYSTEM_PROMPT = """\
You help the owner of a university inbox keep track of requests that only \
they can decide. Summarise the email below for the owner in one or two \
plain sentences: who is asking, for what exactly (which assignment, exam or \
grade; how much time or what new date), the reason they give, any evidence \
they offer, and any deadline they mention. Leave out what the email does \
not say. Do not recommend a decision, do not judge the reason, and do not \
address the sender. Output only the summary.\
"""


def _sender_label(sender: str) -> str:
    name, addr = parseaddr(sender or "")
    return name or addr or "the sender"


def request_exception_handler(state: EmailState) -> EmailState:
    start = time.perf_counter()

    message = _client.messages.create(
        model=LLM_MODEL,
        max_tokens=200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content":
                   f"From: {_sender_label(state.get('sender', ''))}\n"
                   f"Subject: {state['subject']}\n\n{state['body']}"}],
    )
    summary = next((b.text for b in message.content if b.type == "text"), "").strip()

    state["handler_used"] = "exception_note"
    state["note_to_self"] = True
    state["note_summary"] = summary
    state["needs_review"] = True
    state["response"] = (
        f"Note for you, not sent to {_sender_label(state.get('sender', ''))}:\n\n"
        f"{summary}\n\n"
        "This is a request only you can decide. No reply has been drafted. "
        "This draft is addressed to you, so sending it would only email yourself."
    )
    state["input_tokens"] = message.usage.input_tokens
    state["output_tokens"] = message.usage.output_tokens
    state["tokens_used"] = state["input_tokens"] + state["output_tokens"]
    state["latency_ms"] = (time.perf_counter() - start) * 1000
    return state
