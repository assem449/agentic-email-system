#!/usr/bin/env python3
"""Rescore the held-out corpus against adjudicated ground-truth labels.

Only 9 of 105 held-out labels changed during double annotation. The model
predictions in logs/heldout_results.json did not change (nothing about
the classifiers was rerun), so there is no need to rerun eval_heldout.py
or reload the DistilBERT checkpoint. This script just re-applies the
corrected ground truth to the existing predictions and recomputes every
downstream figure: accuracy, macro-F1, per-category P/R/F1, and the same
Wilson / bootstrap CIs used elsewhere in the paper.

Prerequisites:
    1. logs/heldout_results.json exists (produced by eval_heldout.py)
    2. adjudicated_ground_truth.csv exists, columns:
       orig_id, original_label, adjudicated_label, changed

Run from project root:
    python3 rescore_heldout.py
"""
import csv
import json
import math
from pathlib import Path

import numpy as np
from sklearn.metrics import precision_recall_fscore_support

RESULTS_PATH = "logs/heldout_results.json"
ADJUDICATED_PATH = "adjudicated_ground_truth.csv"
CATEGORIES = ["ack", "meeting", "faq", "support", "emotional", "ambiguous", "spam"]
N_BOOTSTRAP = 10000
BOOTSTRAP_SEED = 20260824


def wilson_ci(k, n, z=1.96):
    """Wilson score interval for a proportion k/n, matching the CIs
    already reported elsewhere in the paper for accuracy."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z**2 / n
    centre = p + z**2 / (2 * n)
    adj = z * math.sqrt((p * (1 - p) + z**2 / (4 * n)) / n)
    lo = (centre - adj) / denom
    hi = (centre + adj) / denom
    return (max(0.0, lo), min(1.0, hi))


def macro_f1(y_true, y_pred):
    _, _, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=CATEGORIES, average=None, zero_division=0
    )
    return f1.mean()


def bootstrap_macro_f1_ci(y_true, y_pred, n_boot=N_BOOTSTRAP, seed=BOOTSTRAP_SEED):
    rng = np.random.default_rng(seed)
    y_true = np.array(y_true)
    y_pred = np.array(y_pred)
    n = len(y_true)
    scores = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        scores[i] = macro_f1(y_true[idx], y_pred[idx])
    lo, hi = np.percentile(scores, [2.5, 97.5])
    return float(lo), float(hi)


def load_adjudicated_labels(path):
    corrected = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            corrected[row["orig_id"]] = row["adjudicated_label"]
    return corrected


def apply_corrections(rows, corrected):
    out = []
    n_changed = 0
    for r in rows:
        new_row = dict(r)
        adj_label = corrected.get(r["id"])
        if adj_label is not None and adj_label != r["true_category"]:
            n_changed += 1
        if adj_label is not None:
            new_row["true_category"] = adj_label
        new_row["correct"] = new_row["true_category"] == new_row["predicted_category"]
        out.append(new_row)
    return out, n_changed


def report(rows, name):
    y_true = [r["true_category"] for r in rows]
    y_pred = [r["predicted_category"] for r in rows]
    n = len(rows)
    k = sum(1 for r in rows if r["correct"])
    acc = k / n
    acc_lo, acc_hi = wilson_ci(k, n)

    mf1 = macro_f1(y_true, y_pred)
    mf1_lo, mf1_hi = bootstrap_macro_f1_ci(y_true, y_pred)

    p, r, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=CATEGORIES, average=None, zero_division=0
    )

    print(f"\n=== {name} ===")
    print(f"Accuracy : {acc:.4f}  ({k}/{n})  95% CI [{acc_lo:.4f}, {acc_hi:.4f}]")
    print(f"Macro-F1 : {mf1:.4f}  95% CI [{mf1_lo:.4f}, {mf1_hi:.4f}]")
    print(f"\n{'Category':<14}{'n':<6}{'P':<8}{'R':<8}{'F1':<8}")
    for i, cat in enumerate(CATEGORIES):
        print(f"{cat:<14}{support[i]:<6}{p[i]:<8.3f}{r[i]:<8.3f}{f1[i]:<8.3f}")

    return {
        "accuracy": acc, "accuracy_ci": [acc_lo, acc_hi],
        "macro_f1": mf1, "macro_f1_ci": [mf1_lo, mf1_hi],
        "per_category": {
            cat: {"n": int(support[i]), "precision": float(p[i]),
                  "recall": float(r[i]), "f1": float(f1[i])}
            for i, cat in enumerate(CATEGORIES)
        },
    }


def main():
    for p in (RESULTS_PATH, ADJUDICATED_PATH):
        if not Path(p).exists():
            raise SystemExit(f"missing: {p}")

    with open(RESULTS_PATH) as f:
        results = json.load(f)

    corrected = load_adjudicated_labels(ADJUDICATED_PATH)

    rules_rows, n_changed_rules = apply_corrections(results["rules"], corrected)
    distil_rows, n_changed_distil = apply_corrections(results["distilbert"], corrected)
    assert n_changed_rules == n_changed_distil, "correction count mismatch between rows"
    print(f"Applying {n_changed_rules} corrected labels to {len(rules_rows)} held-out emails.")

    m_rules = report(rules_rows, "Rules v1 (frozen) — held-out, adjudicated labels")
    m_distil = report(distil_rows, "DistilBERT (trained on all 363) — held-out, adjudicated labels")

    Path("logs").mkdir(exist_ok=True)
    with open("logs/heldout_results_adjudicated.json", "w") as f:
        json.dump({
            "n_labels_changed": n_changed_rules,
            "rules": rules_rows,
            "distilbert": distil_rows,
            "macro_rules": m_rules,
            "macro_distilbert": m_distil,
        }, f, indent=2)

    print("\nSaved to logs/heldout_results_adjudicated.json")


if __name__ == "__main__":
    main()