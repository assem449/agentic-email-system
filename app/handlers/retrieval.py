import time
import json
import chromadb
from pathlib import Path
from app.state import EmailState

_client = chromadb.Client()  # in-memory, ephemeral — fine for prototype
_collection = _client.get_or_create_collection("faq")

def _load_faq():
    path = Path(__file__).parent.parent.parent / "data" / "faq.json"
    with open(path) as f:
        faqs = json.load(f)

    _collection.add(
        ids=[str(i) for i in range(len(faqs))],
        documents=[faq["question"] for faq in faqs],
        metadatas=[{"answer": faq["answer"]} for faq in faqs],
    )

_load_faq()  # runs once on import

CONFIDENCE_THRESHOLD = 1.0  # Chroma default distance metric; lower = closer match

def retrieval_handler(state: EmailState) -> EmailState:
    start = time.perf_counter()

    results = _collection.query(query_texts=[state["body"]], n_results=1)

    distance = results["distances"][0][0]
    answer = results["metadatas"][0][0]["answer"]
    matched_question = results["documents"][0][0]

    if distance <= CONFIDENCE_THRESHOLD:
        state["handler_used"] = "retrieval_hit"
        state["response"] = answer
    else:
        # No confident match — would normally fall back to LLM here
        state["handler_used"] = "retrieval_miss"
        state["response"] = f"[no confident FAQ match for]: {state['body'][:50]}"

    state["tokens_used"] = 0
    state["latency_ms"] = (time.perf_counter() - start) * 1000
    return state