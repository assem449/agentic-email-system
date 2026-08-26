import time
import json
import chromadb
from pathlib import Path
from app.state import EmailState
from app.handlers.llm import llm_handler

# Distance metric is set explicitly rather than left to ChromaDB's default
# (squared L2). With the default embedding function the vectors are
# normalized, so squared L2 and cosine distance are monotonically related
# -- but the numeric scale differs, and a threshold is meaningless unless
# the metric is stated.
_client = chromadb.Client()  # in-memory, ephemeral — fine for prototype
_collection = _client.get_or_create_collection(
    "faq",
    metadata={"hnsw:space": "cosine"},
)

# Cosine DISTANCE, range [0, 2]. 0.5 == cosine similarity of 0.5.
#
# This is equivalent to the previous squared-L2 threshold of 1.0: for unit
# vectors, L2^2 = 2 - 2*cos, so L2^2 <= 1.0  <=>  cos >= 0.5  <=>  cosine
# distance <= 0.5. Switching the metric without changing this number would
# have accepted essentially every query.
#
# The value is not empirically validated. Sweep it against a held-out
# labelled slice before reporting it as tuned.
CONFIDENCE_THRESHOLD = 0.5


def _load_faq():
    if _collection.count() > 0:
        return

    path = Path(__file__).parent.parent.parent / "data" / "faq.json"
    with open(path) as f:
        faqs = json.load(f)

    _collection.add(
        ids=[str(i) for i in range(len(faqs))],
        documents=[faq["question"] for faq in faqs],
        metadatas=[{"answer": faq["answer"]} for faq in faqs],
    )


_load_faq()  # runs once on import


def retrieval_handler(state: EmailState) -> EmailState:
    start = time.perf_counter()

    results = _collection.query(query_texts=[state["body"]], n_results=1)

    distance = results["distances"][0][0]
    answer = results["metadatas"][0][0]["answer"]

    state["retrieval_distance"] = distance

    if distance <= CONFIDENCE_THRESHOLD:
        # The stored answer is returned verbatim. No generation happens
        # on this path.
        state["handler_used"] = "retrieval_hit"
        state["response"] = answer
        state["tokens_used"] = 0
        state["input_tokens"] = 0
        state["output_tokens"] = 0
    else:
        # No confident match — fall through to the LLM. Previously this
        # branch emitted a placeholder string and recorded zero tokens,
        # which silently counted unanswered emails as free successful
        # routing and inflated the reported token and latency savings.
        state = llm_handler(state)
        state["handler_used"] = "retrieval_miss_llm"

    state["latency_ms"] = (time.perf_counter() - start) * 1000
    return state