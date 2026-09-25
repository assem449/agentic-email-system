#!/usr/bin/env python3
"""Bootstrap 95% intervals for the held-out results.

Wilson intervals cover accuracy exactly from the counts, but macro-F1 is a
non-linear function of the confusion matrix and has no closed form, so it
needs resampling. This resamples emails with replacement, recomputes macro-F1
on each resample, and takes the 2.5th and 97.5th percentiles.

Run from project root:
    ./venv/bin/python3 bootstrap_heldout.py
"""
import json
import math
import random
from collections import defaultdict

LOG = "logs/heldout_results.json"
N_RESAMPLES = 10000
SEED = 20260824
CATEGORIES = ["ack", "meeting", "faq", "support", "emotional", "ambiguous", "spam"]


def macro_f1(rows, categories=CATEGORIES):
    tp, fp, fn = defaultdict(int), defaultdict(int), defaultdict(int)
    for r in rows:
        t, p = r["true_category"], r["predicted_category"]
        if t == p:
            tp[t] += 1
        else:
            fp[p] += 1
            fn[t] += 1
    total = 0.0
    for c in categories:
        pd, rd = tp[c] + fp[c], tp[c] + fn[c]
        P = tp[c] / pd if pd else 0.0
        R = tp[c] / rd if rd else 0.0
        total += 2 * P * R / (P + R) if P + R else 0.0
    return total / len(categories)


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return centre - half, centre + half


def main():
    with open(LOG) as f:
        data = json.load(f)

    rng = random.Random(SEED)
    for label, key in (("Rules v1 (frozen)", "rules"),
                       ("DistilBERT (all 363)", "distilbert")):
        rows = data[key]
        n = len(rows)
        correct = sum(r["true_category"] == r["predicted_category"] for r in rows)

        lo, hi = wilson(correct, n)
        obs_f1 = macro_f1(rows)
        draws = sorted(
            macro_f1([rows[rng.randrange(n)] for _ in range(n)])
            for _ in range(N_RESAMPLES))
        f1_lo = draws[int(0.025 * N_RESAMPLES)]
        f1_hi = draws[int(0.975 * N_RESAMPLES)]

        print(f"\n=== {label} (held-out, n={n}) ===")
        print(f"  accuracy  {correct}/{n} = {correct / n:.4f}   "
              f"95% Wilson CI [{lo:.4f}, {hi:.4f}]")
        print(f"  macro-F1  {obs_f1:.4f}              "
              f"95% bootstrap CI [{f1_lo:.4f}, {f1_hi:.4f}]  "
              f"({N_RESAMPLES} resamples, seed {SEED})")

    # The comparison the paper makes, with its caveat.
    d = data["distilbert"]
    correct = sum(r["true_category"] == r["predicted_category"] for r in d)
    lo, hi = wilson(correct, len(d))
    cv_lo, cv_hi = wilson(336, 363)
    print(f"\n=== primary vs held-out ===")
    print(f"  primary  336/363 = 0.9256   CI [{cv_lo:.4f}, {cv_hi:.4f}]")
    print(f"  held-out {correct}/{len(d)} = {correct / len(d):.4f}   "
          f"CI [{lo:.4f}, {hi:.4f}]")
    print("  intervals overlap" if lo < cv_hi and cv_lo < hi
          else "  intervals do not overlap")
    print("  Note: the primary figure comes from out-of-fold models trained on")
    print("  ~80% of the corpus each; the held-out figure from one model trained")
    print("  on all 363. The two are not directly comparable.")


if __name__ == "__main__":
    main()