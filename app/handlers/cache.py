import time
import hashlib
from app.state import EmailState

# In-memory cache: {normalized_question_hash: response}
_CACHE: dict[str, str] = {}

def _normalize(text: str) -> str:
    return " ".join(text.lower().strip().split())

def _cache_key(text: str) -> str:
    return hashlib.sha256(_normalize(text).encode()).hexdigest()

def cache_handler(state: EmailState) -> EmailState:
    start = time.perf_counter()
    key = _cache_key(state["body"])

    if key in _CACHE:
        state["handler_used"] = "cache_hit"
        state["response"] = _CACHE[key]
        state["tokens_used"] = 0
    else:
        # Cache miss — for now, store a placeholder.
        # Step 7 will wire this to actually call the LLM handler and cache its output.
        response = f"[cache miss — would call LLM for]: {state['body'][:50]}"
        _CACHE[key] = response

        state["handler_used"] = "cache_miss"
        state["response"] = response
        state["tokens_used"] = None  # will be set once wired to real LLM

    state["latency_ms"] = (time.perf_counter() - start) * 1000
    return state