import time
from anthropic import Anthropic
from app.state import EmailState
from app.config import ANTHROPIC_API_KEY, LLM_MODEL

_client = Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = (
    "You are a helpful customer support assistant replying to an email. "
    "Be empathetic, concise, and professional. Do not make promises about "
    "refunds, deadlines, or commitments you cannot verify. Keep the reply "
    "under 100 words."
)


def llm_handler(state: EmailState) -> EmailState:
    start = time.perf_counter()

    message = _client.messages.create(
        model=LLM_MODEL,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Subject: {state['subject']}\n\n{state['body']}",
        }],
    )

    response_text = message.content[0].text

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