import os

from langgraph.graph import StateGraph, END
import time
from app.state import EmailState
from app.classifier import classify_email
from app.handlers.template import template_handler
from app.handlers.cache import cache_handler
from app.handlers.retrieval import retrieval_handler
from app.handlers.calendar import calendar_handler
from app.handlers.llm import llm_handler
from app.logging_utils import log_routing_decision

# Which classifier the live pipeline uses. Both share a (subject, body)
# -> category signature. eval_run.py rebinds classify_node directly to
# compare them.
#
# DistilBERT (transformers + torch) is NOT imported unless explicitly
# asked for via CLASSIFIER=distilbert: importing torch alone commonly
# costs 300MB+ RSS before a single email is processed, which reliably
# OOMs a memory-constrained deploy (e.g. Render's 512MB Starter plan).
# It also needs data/distilbert_model/ present, which is gitignored and
# not part of a fresh deploy's checkout — set this only on an instance
# that actually has the trained model file and enough RAM.
if os.environ.get("CLASSIFIER", "rules") == "distilbert":
    from app.distilbert_classifier import classify_email_distilbert
    ACTIVE_CLASSIFIER = classify_email_distilbert
else:
    ACTIVE_CLASSIFIER = classify_email


def classify_node(state: EmailState) -> EmailState:
    state["category"] = ACTIVE_CLASSIFIER(state["subject"], state["body"])
    return state


def route_decision(state: EmailState) -> str:
    return state["category"]


def spam_node(state: EmailState) -> EmailState:
    """Terminal node for emails the CLASSIFIER labels spam.

    This is not a pre-pipeline filter: it runs after classification, so
    spam detection performance here is classifier accuracy, not the
    accuracy of a separate spam filter. It also does not touch Gmail
    labels — that happens in the poller, outside the evaluated graph.
    """
    start = time.perf_counter()
    state["handler_used"] = "blocked"
    state["response"] = "[blocked — flagged as spam/phishing]"
    state["tokens_used"] = 0
    state["input_tokens"] = 0
    state["output_tokens"] = 0
    state["latency_ms"] = (time.perf_counter() - start) * 1000
    return state


def build_graph():
    g = StateGraph(EmailState)

    # Looked up in module globals at call time, so eval_run.py can rebind
    # graph_module.classify_node / graph_module.calendar_handler before
    # calling build_graph() and have the change take effect.
    g.add_node("classify", classify_node)
    g.add_node("template", template_handler)
    g.add_node("cache", cache_handler)
    g.add_node("retrieval", retrieval_handler)
    g.add_node("calendar", calendar_handler)
    g.add_node("llm", llm_handler)
    g.add_node("spam", spam_node)

    g.set_entry_point("classify")

    g.add_conditional_edges(
        "classify",
        route_decision,
        {
            "spam": "spam",
            "ack": "template",
            "faq": "retrieval",
            "meeting": "calendar",
            "emotional": "llm",
            "support": "cache",
            "ambiguous": "llm",
        },
    )

    g.add_node("log", log_routing_decision)
    for node in ["template", "cache", "retrieval", "calendar", "llm", "spam"]:
        g.add_edge(node, "log")

    g.add_edge("log", END)

    return g.compile()