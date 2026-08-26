import time
import hashlib
from app.state import EmailState
from app.handlers.llm import llm_handler

# In-memory cache: {normalized_question_hash: response}
#
# NOTE: this is process-global state. Two evaluation passes in the same
# process will share it, so the second pass gets free hits on every email
# the first pass sent to the LLM. Always call clear_cache() at the start
# of each evaluation run.
_CACHE: dict[str, str] = {}


def clear_cache() -> None:
    """Reset cache state between evaluation runs."""
    _CACHE.clear()


def cache_size() -> int:
    return len(_CACHE)


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
        state["input_tokens"] = 0
        state["output_tokens"] = 0
    else:
        # llm_handler sets response, tokens_used, input_tokens,
        # output_tokens and handler_used; we only override the label and
        # the latency so the reported time covers the whole cache path.
        state = llm_handler(state)
        _CACHE[key] = state["response"]
        state["handler_used"] = "cache_miss_llm"

    state["latency_ms"] = (time.perf_counter() - start) * 1000
    return state