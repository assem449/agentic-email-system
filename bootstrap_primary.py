#!/usr/bin/env python3
"""95% intervals for the primary-corpus out-of-fold results.

Same method as the held-out intervals (rescore_heldout.py): Wilson for
accuracy, and a percentile bootstrap over emails for macro-F1, with 10,000
resamples and seed 20260824. Applied to every out-of-fold predictions file
that exists, so all classifiers in Table I get intervals computed the same
way.

Run from project root after app/distilbert_cv.py and tfidf_baseline.py:
    python3 bootstrap_primary.py
"""
import json
from pathlib import Path

from rescore_heldout import wilson_ci, macro_f1, bootstrap_macro_f1_ci

FILES = {
    "DistilBERT v2": "logs/oof_predictions.json",
    "TF-IDF + SVM": "logs/tfidf_svm_oof_predictions.json",
    "TF-IDF + LR": "logs/tfidf_lr_oof_predictions.json",
}


def main():
    out = {}
    for name, path in FILES.items():
        if not Path(path).exists():
            print(f"{name}: {path} missing, skipped")
            continue
        rows = list(json.load(open(path)).values())
        y_true = [r["true_category"] for r in rows]
        y_pred = [r["predicted_category"] for r in rows]
        k, n = sum(t == p for t, p in zip(y_true, y_pred)), len(rows)
        lo, hi = wilson_ci(k, n)
        f1 = macro_f1(y_true, y_pred)
        f_lo, f_hi = bootstrap_macro_f1_ci(y_true, y_pred)
        out[name] = {"correct": k, "n": n, "accuracy": k / n, "accuracy_ci": [lo, hi],
                     "macro_f1": f1, "macro_f1_ci": [f_lo, f_hi]}
        print(f"{name:<14} acc {k}/{n} = {k / n:.4f} [{lo:.4f}, {hi:.4f}]   "
              f"macro-F1 {f1:.4f} [{f_lo:.4f}, {f_hi:.4f}]")
    Path("logs").mkdir(exist_ok=True)
    with open("logs/primary_intervals.json", "w") as f:
        json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
