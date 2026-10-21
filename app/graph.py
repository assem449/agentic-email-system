import os
import re

from langgraph.graph import StateGraph, END
import time
from app.state import EmailState
from app.classifier import classify_email
from app.handlers.calendar import calendar_handler
from app.handlers.course_logistics import course_logistics_handler
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


# The rules classifier (CLASSIFIER=rules) still speaks the v1 customer-
# support categories. Mapping them here keeps it usable as a fallback; the
# DistilBERT model trained on data/academic/dataset_v2.json already returns
# the 11 academic categories.
LEGACY_CATEGORIES = {
    "ack": "informational",
    "faq": "course_logistics",
    "meeting": "meeting_request",
    "emotional": "wellbeing",
    "support": "ambiguous",
}


def classify_node(state: EmailState) -> EmailState:
    category = ACTIVE_CLASSIFIER(state["subject"], state["body"])
    state["category"] = LEGACY_CATEGORIES.get(category, category)
    return state


# Categories that never get a drafted reply. The poller labels them:
# admin_action -> AI/Action needed, announcement_promo -> AI/Announcement,
# informational -> AI/No reply needed.
NO_REPLY_CATEGORIES = {"announcement_promo", "informational", "admin_action"}

# Drafts in these categories are flagged for a human to read before sending.
NEEDS_REVIEW_CATEGORIES = {"wellbeing", "ambiguous"}

# Drafting handler per category. Categories whose own handler isn't built
# yet go to the LLM for now; unknown categories do too.
DRAFT_ROUTES = {
    "meeting_request": "calendar",
    "course_logistics": "course_logistics",
    "request_exception": "llm",
    "academic_question": "llm",
    "collaboration_opportunity": "llm",
    "wellbeing": "llm",
    "ambiguous": "llm",
}

# Skipping a reply is the costly mistake (the sender is ignored), so an
# informational email is sent to the LLM when it visibly asks something:
# "Thanks, but can you check my grade?" gets a draft, not silence.
_ASKS_SOMETHING = re.compile(
    r"\?|\b(can|could|would|will) you\b|\bplease\b|\blet me know\b"
    r"|\bi (have|had) a question\b|\bwondering\b",
    re.IGNORECASE,
)


def route_decision(state: EmailState) -> str:
    category = LEGACY_CATEGORIES.get(state["category"], state["category"])
    # Gmail's DMARC verdict. Eval runs and seeded messages carry none.
    verdict = state.get("auth_verdict") or "none"

    # Spam is moved only when the headers agree. Spam from a domain that
    # passes DMARC may be a real notice the classifier misread (tuition,
    # payroll), and moving a real email to Spam effectively loses it.
    if category == "spam":
        return "spam" if verdict != "pass" else "suspicious"
    # Bulk mail never gets a draft; its category picks the label.
    if state.get("bulk_reason"):
        return "no_reply"
    # Failed DMARC: the sender may be forged, so no draft is written to it.
    if verdict == "fail":
        return "suspicious"
    if category in NO_REPLY_CATEGORIES:
        if category == "informational" and _ASKS_SOMETHING.search(state["body"]):
            return "llm"
        return "no_reply"
    return DRAFT_ROUTES.get(category, "llm")


def _no_cost(state: EmailState, start: float) -> None:
    state["response"] = None
    state["tokens_used"] = 0
    state["input_tokens"] = 0
    state["output_tokens"] = 0
    state["latency_ms"] = (time.perf_counter() - start) * 1000


def no_reply_node(state: EmailState) -> EmailState:
    """Terminal node for email that needs no answer: no draft is created.

    For bulk mail (newsletters, mailing lists) the classifier's category
    is kept: a faculty-office survey sent to a list is still admin_action
    and gets AI/Action needed, not AI/Announcement.
    """
    start = time.perf_counter()
    state["classifier_category"] = state["category"]
    state["handler_used"] = "no_reply_bulk" if state.get("bulk_reason") else "no_reply"
    state["reply_needed"] = False
    _no_cost(state, start)
    return state


def suspicious_node(state: EmailState) -> EmailState:
    """Header safety check: kept in the inbox with AI/Needs review, no draft.

    Two cases: the classifier said spam but DMARC passed (possibly a real
    notice, so not moved to Spam), or DMARC failed on an email the
    classifier didn't flag (possibly forged, so not answered).
    """
    start = time.perf_counter()
    state["handler_used"] = "spam_held" if state["category"] == "spam" else "auth_failed"
    state["reply_needed"] = False
    state["needs_review"] = True
    state["suspicious"] = True
    _no_cost(state, start)
    return state


def spam_node(state: EmailState) -> EmailState:
    """Terminal node for spam the headers don't vouch for: moved to Spam.

    This is not a pre-pipeline filter: it runs after classification, so
    spam detection performance here is classifier accuracy plus the header
    check in route_decision. It does not touch Gmail itself; the poller
    moves the message, outside the evaluated graph.
    """
    start = time.perf_counter()
    state["handler_used"] = "blocked"
    state["reply_needed"] = False
    _no_cost(state, start)
    state["response"] = "[blocked — flagged as spam/phishing]"
    return state


def mark_reply_node(state: EmailState) -> EmailState:
    """Runs after every drafting handler, before logging. A handler that
    decides not to draft (course_logistics without a matching FAQ entry)
    leaves response None and sets needs_review itself."""
    state["reply_needed"] = state.get("response") is not None
    state["needs_review"] = (
        state["category"] in NEEDS_REVIEW_CATEGORIES or bool(state.get("needs_review"))
    )
    return state


def build_graph():
    g = StateGraph(EmailState)

    # Looked up in module globals at call time, so eval_run.py can rebind
    # graph_module.classify_node / graph_module.calendar_handler before
    # calling build_graph() and have the change take effect.
    g.add_node("classify", classify_node)
    g.add_node("calendar", calendar_handler)
    g.add_node("course_logistics", course_logistics_handler)
    g.add_node("llm", llm_handler)
    g.add_node("spam", spam_node)
    g.add_node("suspicious", suspicious_node)
    g.add_node("no_reply", no_reply_node)
    g.add_node("mark_reply", mark_reply_node)

    g.set_entry_point("classify")

    g.add_conditional_edges(
        "classify",
        route_decision,
        {
            "spam": "spam",
            "suspicious": "suspicious",
            "no_reply": "no_reply",
            "calendar": "calendar",
            "course_logistics": "course_logistics",
            "llm": "llm",
        },
    )

    g.add_node("log", log_routing_decision)
    for node in ["calendar", "course_logistics", "llm"]:
        g.add_edge(node, "mark_reply")
    for node in ["mark_reply", "no_reply", "spam", "suspicious"]:
        g.add_edge(node, "log")

    g.add_edge("log", END)

    return g.compile()