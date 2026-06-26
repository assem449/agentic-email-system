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

def classify_node(state: EmailState) -> EmailState:
    state["category"] = classify_email(state["subject"], state["body"])
    return state

def route_decision(state: EmailState) -> str:
    # placeholder routing function — maps category -> node name
    return state["category"]

def spam_node(state: EmailState) -> EmailState:
    start = time.perf_counter()
    state["handler_used"] = "blocked"
    state["response"] = "[blocked — flagged as spam/phishing]"
    state["tokens_used"] = 0
    state["latency_ms"] = (time.perf_counter() - start) * 1000
    return state


def build_graph():
    g = StateGraph(EmailState)

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