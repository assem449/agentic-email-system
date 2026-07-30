import time
import hashlib
from app.state import EmailState
import app.handlers.llm as llm_handler

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
        state = llm_handler(state)  
        _CACHE[key] = state["response"] 
        state["handler_used"] = "cache_miss_llm"

    state["latency_ms"] = (time.perf_counter() - start) * 1000
    return state