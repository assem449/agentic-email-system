from app.graph import build_graph

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