from langgraph.graph import StateGraph, END
from app.state import EmailState
from app.classifier import classify_email

def classify_node(state: EmailState) -> EmailState:
    state["category"] = classify_email(state["subject"], state["body"])
    return state

def route_decision(state: EmailState) -> str:
    # placeholder routing function — maps category -> node name
    return state["category"]

def spam_node(state: EmailState) -> EmailState:
    state["handler_used"] = "blocked"
    state["response"] = "[blocked — flagged as spam/phishing]"
    return state

def template_node(state: EmailState) -> EmailState:
    state["handler_used"] = "template"
    state["response"] = "[template response placeholder]"
    return state

def cache_node(state: EmailState) -> EmailState:
    state["handler_used"] = "cache"
    state["response"] = "[cache response placeholder]"
    return state

def retrieval_node(state: EmailState) -> EmailState:
    state["handler_used"] = "retrieval"
    state["response"] = "[retrieval response placeholder]"
    return state

def calendar_node(state: EmailState) -> EmailState:
    state["handler_used"] = "calendar"
    state["response"] = "[calendar response placeholder]"
    return state

def llm_node(state: EmailState) -> EmailState:
    state["handler_used"] = "llm"
    state["response"] = "[llm response placeholder]"
    return state

def build_graph():
    g = StateGraph(EmailState)

    g.add_node("classify", classify_node)
    g.add_node("template", template_node)
    g.add_node("cache", cache_node)
    g.add_node("retrieval", retrieval_node)
    g.add_node("calendar", calendar_node)
    g.add_node("llm", llm_node)
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

    for node in ["template", "cache", "retrieval", "calendar", "llm", "spam"]:
        g.add_edge(node, END)

    return g.compile()