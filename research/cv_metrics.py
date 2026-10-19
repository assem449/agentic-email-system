"""Per-category and per-role scores for out-of-fold predictions.

Overall accuracy can look good while a rare category is mostly missed, so
this reports, for every category:
  - recall:    of the emails that really are X, the share predicted X
  - precision: of the emails predicted X, the share that really are X
  - F1:        the balance of the two
plus macro-F1 (every category weighted equally, however rare) and accuracy
per inbox role when the dataset records one.

Kept separate from distilbert_cv.py so it can be run and tested without
torch/transformers installed.
"""

from collections import defaultdict


def per_category_scores(y_true, y_pred):
    categories = sorted(set(y_true) | set(y_pred))
    scores = {}
    for c in categories:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == c and p == c)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != c and p == c)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == c and p != c)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        scores[c] = {
            "precision": precision, "recall": recall, "f1": f1,
            "support": sum(1 for t in y_true if t == c),
        }
    # Macro-F1 over categories that actually occur in the data.
    present = [c for c in categories if scores[c]["support"] > 0]
    macro_f1 = sum(scores[c]["f1"] for c in present) / len(present) if present else 0.0
    return scores, macro_f1


def per_group_accuracy(y_true, y_pred, groups):
    totals, correct = defaultdict(int), defaultdict(int)
    for t, p, g in zip(y_true, y_pred, groups):
        totals[g] += 1
        correct[g] += int(t == p)
    return {g: {"accuracy": correct[g] / totals[g], "n": totals[g]} for g in sorted(totals)}


def format_report(scores, macro_f1, role_acc=None) -> str:
    lines = [f"{'category':28s} {'precision':>9s} {'recall':>7s} {'f1':>6s} {'n':>4s}"]
    for c, s in scores.items():
        lines.append(f"{c:28s} {s['precision']:9.3f} {s['recall']:7.3f} {s['f1']:6.3f} {s['support']:4d}")
    lines.append(f"\nMacro-F1 (each category weighted equally): {macro_f1:.4f}")
    if role_acc:
        lines.append("Accuracy by inbox role:")
        for g, s in role_acc.items():
            lines.append(f"  {g:12s} {s['accuracy']:.4f}  (n={s['n']})")
    return "\n".join(lines)
