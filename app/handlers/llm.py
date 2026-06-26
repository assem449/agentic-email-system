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
    total_tokens = message.usage.input_tokens + message.usage.output_tokens

    state["handler_used"] = "llm"
    state["response"] = response_text
    state["tokens_used"] = total_tokens
    state["latency_ms"] = (time.perf_counter() - start) * 1000

    return state