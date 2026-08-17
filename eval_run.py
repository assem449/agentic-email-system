import json
import time
from pathlib import Path
from app.classifier import classify_email
from app.distilbert_classifier import classify_email_distilbert
from app.handlers.llm import llm_handler
import app.graph as graph_module
from app.graph import build_graph
import random

# calendar stub
def fake_calendar(state):
    state["handler_used"] = "calendar"
    state["response"] = "[eval mode — calendar stubbed]"
    state["tokens_used"] = 0
    state["latency_ms"] = 0.1
    return state

graph_module.calendar_handler = fake_calendar

with open("data/eval_set.json") as f:
    eval_set = json.load(f)

CATEGORIES = ["ack", "meeting", "faq", "support", "emotional", "ambiguous", "spam"]

def run_eval(classifier_fn, classifier_name):
    def make_node(fn):
        def classify_node(state):
            state["category"] = fn(state["subject"], state["body"])
            return state
        return classify_node

    graph_module.classify_node = make_node(classifier_fn)
    graph = build_graph()

    results = []
    for item in eval_set:
        base_state = {
            "email_id": item["id"], "sender": "eval@test.com",
            "subject": item["subject"], "body": item["body"],
            "category": None, "handler_used": None, "response": None,
            "tokens_used": None, "latency_ms": None,
        }
        routed = graph.invoke(dict(base_state))
        results.append({
            "id": item["id"],
            "true_category": item["true_category"],
            "predicted_category": routed["category"],
            "correct": routed["category"] == item["true_category"],
            "handler_used": routed["handler_used"],
            "tokens_used": routed["tokens_used"] or 0,
            "latency_ms": routed["latency_ms"],
        })

    accuracy = sum(r["correct"] for r in results) / len(results)
    total_tokens = sum(r["tokens_used"] for r in results)
    total_latency = sum(r["latency_ms"] for r in results)
    misses = [r for r in results if not r["correct"]]

    print(f"\n=== {classifier_name} ===")
    print(f"Accuracy: {accuracy:.2%}")
    print(f"Routed tokens: {total_tokens} | Routed latency: {total_latency:.1f}ms")
    print(f"Misclassified ({len(misses)}):")
    for m in misses:
        print(f"  {m['id']}: true={m['true_category']} predicted={m['predicted_category']}")
    return results

def run_baseline_llm():
    results = []
    for item in eval_set:
        if item["true_category"] == "spam":
            continue
        state = {
            "email_id": item["id"], "sender": "eval@test.com",
            "subject": item["subject"], "body": item["body"],
            "category": None, "handler_used": None, "response": None,
            "tokens_used": None, "latency_ms": None,
        }
        result = llm_handler(state)
        results.append({
            "id": item["id"],
            "tokens_used": result["tokens_used"],
            "latency_ms": result["latency_ms"],
        })
    return results

def run_baseline_random():
    results = []
    for item in eval_set:
        predicted = random.choice(CATEGORIES)
        results.append({
            "id": item["id"],
            "true_category": item["true_category"],
            "predicted_category": predicted,
            "correct": predicted == item["true_category"],
        })
    accuracy = sum(r["correct"] for r in results) / len(results)
    print(f"\n=== Random Routing Baseline ===")
    print(f"Accuracy: {accuracy:.2%} (expected ~14.3% for 7 categories)")
    return results

# Run all 3
rules_results = run_eval(classify_email, "Rules-based Classifier (v1)")
# distilbert_results = run_eval(classify_email_distilbert, "DistilBERT Classifier (v2)")
# random_results = run_baseline_random()

# print("\n=== Always-LLM Baseline ===")
# print("Running LLM on all non-spam emails...")
# llm_results = run_baseline_llm()
llm_tokens = sum(r["tokens_used"] for r in llm_results)
llm_latency = sum(r["latency_ms"] for r in llm_results)
print(f"Total tokens: {llm_tokens} | Total latency: {llm_latency:.1f}ms")

# Summary comparison
rules_tokens = sum(r["tokens_used"] for r in rules_results)
rules_latency = sum(r["latency_ms"] for r in rules_results)
distilbert_tokens = sum(r["tokens_used"] for r in distilbert_results)
distilbert_latency = sum(r["latency_ms"] for r in distilbert_results)

print("\n=== Summary ===")
print(f"{'Baseline':<30} {'Accuracy':<12} {'Tokens':<10} {'Token Reduction':<18} {'Latency Reduction'}")
print(f"{'Always-LLM':<30} {'N/A':<12} {llm_tokens:<10} {'0%':<18} {'0%'}")
print(f"{'Random Routing':<30} {sum(r['correct'] for r in random_results)/len(random_results):<12.2%} {'N/A':<10} {'N/A':<18} {'N/A'}")
print(f"{'Rules v1':<30} {sum(r['correct'] for r in rules_results)/len(rules_results):<12.2%} {rules_tokens:<10} {(1-rules_tokens/llm_tokens):<18.2%} {(1-rules_latency/llm_latency):.2%}")
print(f"{'DistilBERT v2':<30} {sum(r['correct'] for r in distilbert_results)/len(distilbert_results):<12.2%} {distilbert_tokens:<10} {(1-distilbert_tokens/llm_tokens):<18.2%} {(1-distilbert_latency/llm_latency):.2%}")

Path("logs").mkdir(exist_ok=True)
with open("logs/eval_3baseline.json", "w") as f:
    json.dump({
        "rules": rules_results,
        "distilbert": distilbert_results,
        "random": random_results,
        "llm_baseline": llm_results,
    }, f, indent=2)

print("\nSaved to logs/eval_3baseline.json")