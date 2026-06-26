from app.graph import build_graph
from app.handlers.retrieval import _collection

graph = build_graph()

test_emails = [
    {"body": "Thanks!", "subject": ""},
    {"body": "Can we schedule a meeting for next Tuesday?", "subject": ""},
    {"body": "How do I reset my API key?", "subject": ""},
    {"body": "This is broken and I'm so frustrated, nothing works!", "subject": ""},
    {"body": "Click here now to verify your account urgent wire transfer", "subject": ""},
    {"body": "asdkjasd random text", "subject": ""},
]

for i, e in enumerate(test_emails):
    result = graph.invoke({
        "email_id": str(i), "sender": "test@example.com",
        "subject": e["subject"], "body": e["body"],
        "category": None, "handler_used": None, "response": None,
        "tokens_used": None, "latency_ms": None,
    })
    print(f"{e['body'][:40]:40} -> {result['category']:10} -> {result['handler_used']}")


result = graph.invoke({
    "email_id": "ack-1", "sender": "test@example.com",
    "subject": "", "body": "Thanks!",
    "category": None, "handler_used": None, "response": None,
    "tokens_used": None, "latency_ms": None,
})
print(result["response"], "| tokens:", result["tokens_used"], "| latency_ms:", result["latency_ms"])


support_email = {
    "email_id": "sup-1", "sender": "test@example.com",
    "subject": "", "body": "This is broken and I'm so frustrated, nothing works!",
    "category": None, "handler_used": None, "response": None,
    "tokens_used": None, "latency_ms": None,
}

# wait — this routes to "emotional" not "support" after our reorder!


print("\n--- Cache test ---")

support_email_text = "My password reset isn't working"

for attempt in range(2):
    result = graph.invoke({
        "email_id": f"sup-{attempt}", "sender": "test@example.com",
        "subject": "", "body": support_email_text,
        "category": None, "handler_used": None, "response": None,
        "tokens_used": None, "latency_ms": None,
    })
    print(f"Attempt {attempt+1}: {result['category']} -> {result['handler_used']} -> {result['response']}")


print("\n--- Retrieval test ---")
result = graph.invoke({
    "email_id": "faq-1", "sender": "test@example.com",
    "subject": "", "body": "How do I reset my API key?",
    "category": None, "handler_used": None, "response": None,
    "tokens_used": None, "latency_ms": None,
})
print(f"{result['category']} -> {result['handler_used']} -> {result['response']}")


r = _collection.query(query_texts=["How do I reset my API key?"], n_results=1)
print("distance:", r["distances"][0][0])

print("\n--- Retrieval test 2 (paraphrased) ---")
result = graph.invoke({
    "email_id": "faq-2", "sender": "test@example.com",
    "subject": "", "body": "Can you tell me how to get a new API key?",
    "category": None, "handler_used": None, "response": None,
    "tokens_used": None, "latency_ms": None,
})
print(f"{result['category']} -> {result['handler_used']} -> {result['response']}")

from app.handlers.retrieval import _collection
r = _collection.query(query_texts=["Can you tell me how to get a new API key?"], n_results=1)
print("distance:", r["distances"][0][0])


print("\n--- Calendar test ---")
result = graph.invoke({
    "email_id": "cal-1", "sender": "test@example.com",
    "subject": "", "body": "Can we schedule a meeting for next Tuesday?",
    "category": None, "handler_used": None, "response": None,
    "tokens_used": None, "latency_ms": None,
})
print(f"{result['category']} -> {result['handler_used']} -> {result['response']}")