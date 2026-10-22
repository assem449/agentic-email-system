import time
from email.utils import parseaddr
from anthropic import Anthropic
from app.state import EmailState
from app.config import ANTHROPIC_API_KEY, LLM_MODEL

_client = Anthropic(api_key=ANTHROPIC_API_KEY)

# The previous prompt ("customer support assistant... under 100 words")
# produced short generic replies, which is what made multi-question emails
# come back as a polite thank-you. The reply length now follows the email.
SYSTEM_PROMPT = """\
You draft email replies for someone in a university community (a student, \
teaching assistant or instructor). A human reads every draft before it is \
sent.

How to write the reply:
1. Before writing, identify every question and request in the newest \
message. The reply must address each one, in the order asked. Do not \
merge them into one general answer, and never reply with only a thank-you \
when something was asked.
2. Greet the sender by name when it is known. Match their register: formal \
("Dear Professor ...") when writing to faculty or staff, friendly but \
clear with classmates.
3. Refer to the specific course, assignment, deadline or meeting the sender \
mentioned, so the reply could not be pasted under a different email.
4. If answering needs information you do not have (a date, a grade, a \
policy detail, the owner's availability), write a bracketed placeholder \
such as [CONFIRM: new deadline] instead of guessing.
5. Never promise grades, extensions, exceptions, refunds or anything else \
only the inbox owner can decide. Say it will be checked, with a placeholder.
6. If the sender sounds stressed or upset, acknowledge it briefly and \
sincerely before answering.
7. Be as long as the email needs: two sentences for a simple question, \
short paragraphs or a list when several things are asked.
8. End with a sign-off and "[Your name]". Output only the email body: no \
subject line and no notes about the draft.\
"""


# Added to SYSTEM_PROMPT for one category. Categories not listed use the
# general prompt as is.
CATEGORY_GUIDANCE = {
    "ambiguous": (
        "It is unclear what the sender is asking. Do not guess an answer. "
        "Acknowledge the email briefly and ask one or two specific questions "
        "that would make the request clear (which course, assignment, date or "
        "earlier conversation they mean)."
    ),
}

ROLE_CONTEXT = {
    "student": "The inbox owner, who will send this reply, is a student.",
    "instructor": "The inbox owner, who will send this reply, is an instructor or TA.",
}


def system_prompt(state: EmailState) -> str:
    parts = [SYSTEM_PROMPT]
    if state.get("role") in ROLE_CONTEXT:
        parts.append(ROLE_CONTEXT[state["role"]])
    if state.get("category") in CATEGORY_GUIDANCE:
        parts.append(CATEGORY_GUIDANCE[state["category"]])
    return "\n\n".join(parts)


def _sender_name(sender: str) -> str:
    name, addr = parseaddr(sender or "")
    return name or addr or "unknown"


def _user_content(state: EmailState) -> str:
    parts = [
        f"From: {_sender_name(state.get('sender', ''))}",
        f"Subject: {state['subject']}",
        "",
        "Newest message:",
        state["body"],
    ]
    quoted = state.get("quoted_text")
    if quoted:
        parts += ["", "Earlier messages in this thread (for context only):", quoted]
    return "\n".join(parts)


def llm_handler(state: EmailState) -> EmailState:
    start = time.perf_counter()

    message = _client.messages.create(
        model=LLM_MODEL,
        max_tokens=800,
        system=system_prompt(state),
        messages=[{"role": "user", "content": _user_content(state)}],
    )

    response_text = next(
        (b.text for b in message.content if b.type == "text"), ""
    )

    # Input and output tokens are priced differently ($3/M vs $15/M for
    # Sonnet 4.6), so the split has to be recorded separately. A combined
    # token count cannot be converted into a dollar cost after the fact.
    input_tokens = message.usage.input_tokens
    output_tokens = message.usage.output_tokens

    state["handler_used"] = "llm"
    state["response"] = response_text
    state["input_tokens"] = input_tokens
    state["output_tokens"] = output_tokens
    state["tokens_used"] = input_tokens + output_tokens
    state["latency_ms"] = (time.perf_counter() - start) * 1000

    return state
