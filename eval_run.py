import json
from pathlib import Path
from app.graph import build_graph
from app.handlers.llm import llm_handler
import app.graph as graph_module

def fake_calendar_handler(state):
    state["handler_used"] = "calendar"
    state["response"] = "[eval mode — calendar stubbed]"
    state["tokens_used"] = 0
    state["latency_ms"] = 0.1
    return state

graph_module.calendar_handler = fake_calendar_handler

graph = build_graph()

with open("data/eval_set.json") as f:
    eval_set = json.load(f)

routed_results = []
baseline_results = []

for item in eval_set:
    base_state = {
        "email_id": item["id"], "sender": "eval@test.com",
        "subject": item["subject"], "body": item["body"],
        "category": None, "handler_used": None, "response": None,
        "tokens_used": None, "latency_ms": None,
    }

    # Routed pipeline
    routed = graph.invoke(dict(base_state))
    routed_results.append({
        "id": item["id"],
        "true_category": item["true_category"],
        "predicted_category": routed["category"],
        "correct": routed["category"] == item["true_category"],
        "handler_used": routed["handler_used"],
        "tokens_used": routed["tokens_used"] or 0,
        "latency_ms": routed["latency_ms"],
    })

    # Baseline: skip spam-block, force everything through the LLM
    if item["true_category"] != "spam":
        baseline_state = dict(base_state)
        baseline = llm_handler(baseline_state)
        baseline_results.append({
            "id": item["id"],
            "tokens_used": baseline["tokens_used"],
            "latency_ms": baseline["latency_ms"],
        })

# --- Summary ---
routed_total_tokens = sum(r["tokens_used"] for r in routed_results)
routed_total_latency = sum(r["latency_ms"] for r in routed_results)
baseline_total_tokens = sum(b["tokens_used"] for b in baseline_results)
baseline_total_latency = sum(b["latency_ms"] for b in baseline_results)

accuracy = sum(r["correct"] for r in routed_results) / len(routed_results)

print(f"Classifier accuracy: {accuracy:.2%}")
print(f"\nRouted   - total tokens: {routed_total_tokens}, total latency: {routed_total_latency:.1f}ms")
print(f"Baseline - total tokens: {baseline_total_tokens}, total latency: {baseline_total_latency:.1f}ms")
print(f"\nToken reduction: {(1 - routed_total_tokens/baseline_total_tokens):.2%}")
print(f"Latency reduction: {(1 - routed_total_latency/baseline_total_latency):.2%}")

# Misclassifications
print("\nMisclassified:")
for r in routed_results:
    if not r["correct"]:
        print(f"  id={r['id']}: true={r['true_category']} predicted={r['predicted_category']}")

# Save raw results for the paper
Path("logs").mkdir(exist_ok=True)
with open("logs/eval_results.json", "w") as f:
    json.dump({"routed": routed_results, "baseline": baseline_results}, f, indent=2)