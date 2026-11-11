#!/usr/bin/env python3
"""Paired comparison of DistilBERT and the TF-IDF baselines on the held-out set.

The held-out accuracy intervals of DistilBERT and TF-IDF + SVM overlap almost
entirely, and unpaired intervals are the wrong test anyway: both classifiers
score the same 105 emails. This runs an exact McNemar test on the emails
where exactly one of the two is right, against the adjudicated labels.

Prerequisites (run from project root):
    python3 eval_heldout.py                                       -> logs/heldout_results.json
    python3 tfidf_baseline.py --adjudicated adjudicated_ground_truth.csv
                                                                  -> logs/tfidf_heldout_results.json

    python3 compare_heldout.py
"""
import csv
import json
from math import comb

ADJ = "adjudicated_ground_truth.csv"
DISTIL = "logs/heldout_results.json"
TFIDF = "logs/tfidf_heldout_results.json"


def mcnemar_exact(b, c):
    """Two-sided exact McNemar p-value for discordant counts b, c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def main():
    adj = {r["orig_id"]: r["adjudicated_label"] for r in csv.DictReader(open(ADJ))}
    distil = {r["id"]: r["predicted_category"] for r in json.load(open(DISTIL))["distilbert"]}
    tfidf = json.load(open(TFIDF))
    if tfidf["meta"]["heldout_labels"] != "adjudicated":
        raise SystemExit("rerun tfidf_baseline.py with --adjudicated first")

    ids = sorted(adj)
    d_ok = {i: distil[i] == adj[i] for i in ids}
    print(f"DistilBERT: {sum(d_ok.values())}/{len(ids)} correct (adjudicated labels)")
    for kind in ("tfidf_svm", "tfidf_lr"):
        pred = {r["id"]: r["predicted_category"] for r in tfidf[kind]["rows"]}
        t_ok = {i: pred[i] == adj[i] for i in ids}
        b = sum(d_ok[i] and not t_ok[i] for i in ids)   # only DistilBERT right
        c = sum(t_ok[i] and not d_ok[i] for i in ids)   # only TF-IDF right
        print(f"\n{kind}: {sum(t_ok.values())}/{len(ids)} correct")
        print(f"  only DistilBERT right: {b}   only {kind} right: {c}   "
              f"both right: {sum(d_ok[i] and t_ok[i] for i in ids)}   "
              f"both wrong: {sum(not d_ok[i] and not t_ok[i] for i in ids)}")
        print(f"  exact McNemar p = {mcnemar_exact(b, c):.3f}")


if __name__ == "__main__":
    main()
