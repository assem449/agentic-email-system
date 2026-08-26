"""Three-baseline evaluation for the adaptive email routing pipeline.

Changes from the previous version:
  * cache is cleared before every run (it used to persist across runs, so
    whichever classifier ran second got free hits on the first one's misses)
  * always-LLM baseline covers every email instead of skipping true-spam
    via ground-truth labels
  * input/output token split and response text are recorded per email
  * random baseline is seeded
  * latency is reported both with and without calendar-stubbed emails
"""

import json
import random
from pathlib import Path

from app.classifier import classify_email
from app.oof_classifier import classify_email_distilbert_oof
from app.handlers.llm import llm_handler
from app.handlers.cache import clear_cache
import app.graph as graph_module
from app.graph import build_graph

# Claude Sonnet 4.6, USD per million tokens.
PRICE_IN = 3.00
PRICE_OUT = 15.00

RANDOM_SEED = 20260824

# The calendar handler is stubbed so evaluation does not create real
# events. This latency is FICTIONAL — a real Google Calendar round trip
# is orders of magnitude slower. Any latency figure that includes
# calendar-routed emails is an artifact of this constant, which is why
# the summary reports latency reduction both ways.
CALENDAR_STUB_LATENCY_MS = 0.1


def fake_calendar(state):
    state["handler_used"] = "calendar"
    state["response"] = "[eval mode — calendar stubbed]"
    state["tokens_used"] = 0
    state["input_tokens"] = 0
    state["output_tokens"] = 0
    state["latency_ms"] = CALENDAR_STUB_LATENCY_MS
    return state


graph_module.calendar_handler = fake_calendar

with open("data/eval_set.json") as f:
    eval_set = json.load(f)

CATEGORIES = ["ack", "meeting", "faq", "support", "emotional", "ambiguous", "spam"]


def _blank_state(item):
    return {
        "email_id": item["id"], "sender": "eval@test.com",
        "subject": item["subject"], "body": item["body"],
        "category": None, "handler_used": None, "response": None,
        "tokens_used": None, "input_tokens": None, "output_tokens": None,
        "latency_ms": None,
    }


def run_eval(classifier_fn, classifier_name, id_aware=False):
    """
    id_aware=False: classifier_fn(subject, body) -> category
        Rule-based classifier. Not trained on the data, so no leakage
        concern from the model side -- but note the rules were tuned by
        hand against an earlier version of this eval set, which is its
        own form of contamination. They are frozen here.

    id_aware=True: classifier_fn(email_id, subject, body) -> category
        DistilBERT out-of-fold lookup. Each email is scored only by the
        fold model that never saw it in training.
    """
    # Critical: without this, run N+1 inherits run N's cache.
    clear_cache()

    def make_node(fn, item_id=None):
        def classify_node(state):
            if id_aware:
                state["category"] = fn(item_id, state["subject"], state["body"])
            else:
                state["category"] = fn(state["subject"], state["body"])
            return state
        return classify_node

    results = []
    for item in eval_set:
        graph_module.classify_node = make_node(classifier_fn, item["id"])
        graph = build_graph()

        routed = graph.invoke(_blank_state(item))
        results.append({
            "id": item["id"],
            "true_category": item["true_category"],
            "predicted_category": routed["category"],
            "correct": routed["category"] == item["true_category"],
            "handler_used": routed["handler_used"],
            "response": routed.get("response"),
            "tokens_used": routed.get("tokens_used") or 0,
            "input_tokens": routed.get("input_tokens") or 0,
            "output_tokens": routed.get("output_tokens") or 0,
            "latency_ms": routed.get("latency_ms") or 0.0,
            "retrieval_distance": routed.get("retrieval_distance"),
        })

    accuracy = sum(r["correct"] for r in results) / len(results)
    misses = [r for r in results if not r["correct"]]

    print(f"\n=== {classifier_name} ===")
    print(f"Accuracy: {accuracy:.2%} "
          f"({sum(r['correct'] for r in results)}/{len(results)})")
    print(f"Misclassified: {len(misses)}")
    return results


def run_baseline_llm():
    """Every email goes to the LLM.

    The previous version skipped emails whose true_category was 'spam',
    which handed the baseline perfect oracle spam detection for free
    while the routed systems paid tokens for every spam email they
    misrouted. Same emails, same denominator.
    """
    results = []
    for item in eval_set:
        result = llm_handler(_blank_state(item))
        results.append({
            "id": item["id"],
            "true_category": item["true_category"],
            "response": result.get("response"),
            "tokens_used": result["tokens_used"],
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "latency_ms": result["latency_ms"],
        })
    return results


def run_baseline_random():
    rng = random.Random(RANDOM_SEED)
    results = [{
        "id": item["id"],
        "true_category": item["true_category"],
        "predicted_category": rng.choice(CATEGORIES),
    } for item in eval_set]
    for r in results:
        r["correct"] = r["predicted_category"] == r["true_category"]

    accuracy = sum(r["correct"] for r in results) / len(results)
    print(f"\n=== Random Routing Baseline ===")
    print(f"Accuracy: {accuracy:.2%} (expected ~14.3% for 7 categories)")
    return results


# ---------------------------------------------------------------- metrics

def totals(rows, ids=None):
    rs = rows if ids is None else [r for r in rows if r["id"] in ids]
    return {
        "n": len(rs),
        "tokens": sum(r.get("tokens_used") or 0 for r in rs),
        "input": sum(r.get("input_tokens") or 0 for r in rs),
        "output": sum(r.get("output_tokens") or 0 for r in rs),
        "latency": sum(r.get("latency_ms") or 0 for r in rs),
    }


def cost(t):
    return t["input"] / 1e6 * PRICE_IN + t["output"] / 1e6 * PRICE_OUT


def report(label, routed, baseline, ids=None):
    r, b = totals(routed, ids), totals(baseline, ids)
    print(f"  {label:<26} "
          f"tokens {1 - r['tokens']/b['tokens']:>7.2%}   "
          f"cost {1 - cost(r)/cost(b):>7.2%}   "
          f"latency {1 - r['latency']/b['latency']:>7.2%}")


if __name__ == "__main__":
    rules_results = run_eval(classify_email, "Rules-based Classifier (v1)")
    distilbert_results = run_eval(
        classify_email_distilbert_oof,
        "DistilBERT Classifier (v2, 5-fold CV, OOF)",
        id_aware=True,
    )
    random_results = run_baseline_random()

    print("\n=== Always-LLM Baseline ===")
    print(f"Running LLM on all {len(eval_set)} emails...")
    llm_results = run_baseline_llm()
    b = totals(llm_results)
    print(f"Tokens: {b['tokens']} (in {b['input']} / out {b['output']})  "
          f"Cost: ${cost(b):.4f}  Latency: {b['latency']:,.0f}ms")

    all_ids = {r["id"] for r in llm_results}
    nonspam_ids = {r["id"] for r in llm_results if r["true_category"] != "spam"}
    runs = (("Rules v1", rules_results),
            ("DistilBERT v2", distilbert_results))

    print("\n=== Reduction vs. always-LLM (all emails) ===")
    for label, rows in runs:
        report(label, rows, llm_results, all_ids)

    print("\n=== Reduction vs. always-LLM (non-spam only) ===")
    for label, rows in runs:
        report(label, rows, llm_results, nonspam_ids)

    print("\n=== Latency excluding calendar-stubbed emails ===")
    for label, rows in runs:
        keep = {r["id"] for r in rows if r["handler_used"] != "calendar"}
        report(label, rows, llm_results, keep & all_ids)

    print("\n=== Handler distribution ===")
    for label, rows in runs:
        counts = {}
        for r in rows:
            counts[r["handler_used"]] = counts.get(r["handler_used"], 0) + 1
        print(f"  {label}: " + "  ".join(
            f"{h}={n}" for h, n in sorted(counts.items(), key=lambda kv: -kv[1])))

    print("\n=== Summary ===")
    print(f"{'System':<30}{'Accuracy':<12}{'Tokens':<10}{'Cost':<12}")
    print(f"{'Always-LLM':<30}{'N/A':<12}{b['tokens']:<10}${cost(b):<11.4f}")
    print(f"{'Random Routing':<30}"
          f"{sum(r['correct'] for r in random_results)/len(random_results):<12.2%}"
          f"{'N/A':<10}{'N/A':<12}")
    for label, rows in runs:
        t = totals(rows)
        print(f"{label:<30}"
              f"{sum(r['correct'] for r in rows)/len(rows):<12.2%}"
              f"{t['tokens']:<10}${cost(t):<11.4f}")

    Path("logs").mkdir(exist_ok=True)
    with open("logs/eval_3baseline.json", "w") as f:
        json.dump({
            "meta": {
                "n_emails": len(eval_set),
                "random_seed": RANDOM_SEED,
                "calendar_stub_latency_ms": CALENDAR_STUB_LATENCY_MS,
                "price_in_per_mtok": PRICE_IN,
                "price_out_per_mtok": PRICE_OUT,
            },
            "rules": rules_results,
            "distilbert": distilbert_results,
            "random": random_results,
            "llm_baseline": llm_results,
        }, f, indent=2)

    print("\nSaved to logs/eval_3baseline.json")