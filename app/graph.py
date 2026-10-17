import os
import re

from langgraph.graph import StateGraph, END
import time
from app.state import EmailState
from app.classifier import classify_email
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


# Categories that never get a drafted reply. `ack` is a thank-you or
# confirmation; replying "You're welcome!" to it is noise in a real inbox.
NO_REPLY_CATEGORIES = {"ack"}

# Drafts in these categories are flagged for a human to read before sending.
NEEDS_REVIEW_CATEGORIES = {"emotional"}

# Skipping a reply is the costly mistake (the sender is ignored), so a
# no-reply label is overridden when the email visibly asks for something:
# "Thanks, but can you check my grade?" goes to the LLM, not the bin.
_ASKS_SOMETHING = re.compile(
    r"\?|\b(can|could|would|will) you\b|\bplease\b|\blet me know\b"
    r"|\bi (have|had) a question\b|\bwondering\b",
    re.IGNORECASE,
)


def route_decision(state: EmailState) -> str:
    category = state["category"]
    # Spam wins over the bulk flag: phishing often carries list headers too.
    if category == "spam":
        return "spam"
    if state.get("bulk_reason"):
        return "no_reply"
    if category in NO_REPLY_CATEGORIES:
        if _ASKS_SOMETHING.search(state["body"]):
            return "ambiguous"
        return "no_reply"
    return category


def no_reply_node(state: EmailState) -> EmailState:
    """Terminal node for email that needs no answer: no draft is created.

    Bulk mail (newsletters, LinkedIn, mailing lists) is relabelled
    `announcement_promo` here rather than by the classifier, because the
    signal is in the headers, not the text. The classifier's own guess is
    kept in classifier_category for analysis.
    """
    start = time.perf_counter()
    state["classifier_category"] = state["category"]
    if state.get("bulk_reason"):
        state["handler_used"] = "no_reply_bulk"
        state["category"] = "announcement_promo"
    else:
        state["handler_used"] = "no_reply"
    state["reply_needed"] = False
    state["response"] = None
    state["tokens_used"] = 0
    state["input_tokens"] = 0
    state["output_tokens"] = 0
    state["latency_ms"] = (time.perf_counter() - start) * 1000
    return state


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
    state["reply_needed"] = False
    return state


def mark_reply_node(state: EmailState) -> EmailState:
    """Runs after every drafting handler, before logging."""
    state["reply_needed"] = True
    state["needs_review"] = state["category"] in NEEDS_REVIEW_CATEGORIES
    return state


def build_graph():
    g = StateGraph(EmailState)

    # Looked up in module globals at call time, so eval_run.py can rebind
    # graph_module.classify_node / graph_module.calendar_handler before
    # calling build_graph() and have the change take effect.
    g.add_node("classify", classify_node)
    g.add_node("cache", cache_handler)
    g.add_node("retrieval", retrieval_handler)
    g.add_node("calendar", calendar_handler)
    g.add_node("llm", llm_handler)
    g.add_node("spam", spam_node)
    g.add_node("no_reply", no_reply_node)
    g.add_node("mark_reply", mark_reply_node)

    g.set_entry_point("classify")

    g.add_conditional_edges(
        "classify",
        route_decision,
        {
            "spam": "spam",
            "no_reply": "no_reply",
            "faq": "retrieval",
            "meeting": "calendar",
            "emotional": "llm",
            "support": "cache",
            "ambiguous": "llm",
        },
    )

    g.add_node("log", log_routing_decision)
    for node in ["cache", "retrieval", "calendar", "llm"]:
        g.add_edge(node, "mark_reply")
    for node in ["mark_reply", "no_reply", "spam"]:
        g.add_edge(node, "log")

    g.add_edge("log", END)

    return g.compile()