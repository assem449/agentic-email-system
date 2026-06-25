from app.graph import build_graph

graph = build_graph()

result = graph.invoke({
    "email_id": "1",
    "sender": "test@example.com",
    "subject": "test",
    "body": "Thanks!",
    "category": None,
    "handler_used": None,
    "response": None,
    "tokens_used": None,
    "latency_ms": None,
})

print(result)