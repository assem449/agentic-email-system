"""Classification metrics: per-category precision, recall, F1 and macro-F1.

Accuracy alone hides uneven performance across categories. On the current
evaluation set rules v1 scores 39.67% accuracy but 0.386 macro-F1, and the
gap is the point: it catches 4 of 45 spam emails (recall 0.089) while being
reasonably precise on the few it does catch (0.667). Macro-F1 weights every
category equally regardless of size, so a class the classifier has effectively
given up on cannot be masked by a larger class it handles well.

No new evaluation run is needed -- these are computed from the true and
predicted labels already stored in logs/eval_3baseline.json.
"""
from collections import defaultdict

CATEGORIES = ["ack", "meeting", "faq", "support", "emotional", "ambiguous", "spam"]


def per_category(rows, categories=CATEGORIES):
    """rows: dicts with 'true_category' and 'predicted_category'.

    Returns {category: {'precision','recall','f1','support'}}.
    """
    tp, fp, fn = defaultdict(int), defaultdict(int), defaultdict(int)
    for r in rows:
        t, p = r["true_category"], r["predicted_category"]
        if t == p:
            tp[t] += 1
        else:
            fp[p] += 1
            fn[t] += 1

    out = {}
    for c in categories:
        p_den, r_den = tp[c] + fp[c], tp[c] + fn[c]
        precision = tp[c] / p_den if p_den else 0.0
        recall = tp[c] / r_den if r_den else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        out[c] = {"precision": precision, "recall": recall, "f1": f1, "support": r_den}
    return out


def macro(rows, categories=CATEGORIES):
    """Unweighted mean of per-category precision, recall and F1, plus accuracy."""
    pc = per_category(rows, categories)
    n = len(categories)
    return {
        "macro_precision": sum(v["precision"] for v in pc.values()) / n,
        "macro_recall": sum(v["recall"] for v in pc.values()) / n,
        "macro_f1": sum(v["f1"] for v in pc.values()) / n,
        "accuracy": sum(r["true_category"] == r["predicted_category"] for r in rows) / len(rows),
        "n": len(rows),
    }


def report(rows, name, categories=CATEGORIES):
    """Print a per-category table followed by macro averages. Returns the macro dict."""
    pc = per_category(rows, categories)
    m = macro(rows, categories)
    print(f"\n=== {name} ===")
    print(f"{'category':<12}{'n':>5}{'precision':>11}{'recall':>9}{'F1':>8}")
    for c in sorted(categories):
        v = pc[c]
        print(f"{c:<12}{v['support']:>5}{v['precision']:>11.3f}"
              f"{v['recall']:>9.3f}{v['f1']:>8.3f}")
    print(f"{'macro avg':<12}{m['n']:>5}{m['macro_precision']:>11.3f}"
          f"{m['macro_recall']:>9.3f}{m['macro_f1']:>8.3f}")
    print(f"accuracy: {m['accuracy']:.4f}")
    return m


if __name__ == "__main__":
    import json
    with open("logs/eval_3baseline.json") as f:
        data = json.load(f)
    for label, key in (("Rules v1 (frozen)", "rules"),
                       ("DistilBERT v2 (out-of-fold)", "distilbert"),
                       ("Random routing", "random")):
        if key in data:
            report(data[key], label)
