#!/usr/bin/env python3
"""TF-IDF linear baselines between the frozen rules and DistilBERT.

Two classifiers, both on TF-IDF features of the same subject + body
concatenation DistilBERT sees:

    tfidf_lr   TF-IDF (word 1-2 grams) + multinomial logistic regression
    tfidf_svm  TF-IDF (word 1-2 grams) + linear SVM

Comparability with the DistilBERT figures in the paper:
  * Same corpus (data/eval_set.json, 363 emails).
  * Same folds. The split below is built exactly as in app/distilbert_cv.py:
    LabelEncoder over the full label set, then
    StratifiedKFold(n_splits=5, shuffle=True, random_state=42) over the
    encoded labels. The script asserts the fold assignment is identical to
    the one recorded in logs/oof_predictions.json when that file exists.
  * Same reporting: per-fold accuracy (mean +/- population std, as in
    distilbert_cv.py), pooled out-of-fold accuracy with a 95% Wilson
    interval, macro-F1 with a 95% bootstrap interval (10,000 resamples,
    seed 20260824, as in bootstrap_heldout.py).
  * Hyperparameters are library defaults fixed before any run (C=1.0, no
    grid search). Tuning on the CV folds would make the OOF estimate
    optimistic; tuning on a nested split is not worth it for a baseline.
    The TF-IDF vocabulary is fitted inside each fold, on training emails
    only, so no test-fold text leaks into the features.

Held-out: each model is refit on all 363 primary emails and scored on
data/heldout_set.json. NOTE: that file holds the PRE-adjudication labels.
The paper's held-out figures use the adjudicated labels (9 of 105 changed).
Pass --adjudicated adjudicated_ground_truth.csv (columns orig_id,
adjudicated_label) to score against the same ground truth as the paper.

Also measures per-email inference latency (one email at a time, as the
pipeline classifies), so the result feeds the end-to-end latency table.

Outputs:
    logs/tfidf_cv_results.json
    logs/tfidf_lr_oof_predictions.json    same format as oof_predictions.json,
    logs/tfidf_svm_oof_predictions.json   usable by eval_run.py for cost
    logs/tfidf_heldout_results.json

Run from project root (no API calls, no GPU, a few seconds on CPU):
    python3 tfidf_baseline.py [--adjudicated adjudicated_ground_truth.csv]
"""
import argparse
import csv
import json
import math
import statistics
import time
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import LabelEncoder
from sklearn.svm import LinearSVC

PRIMARY = "data/eval_set.json"
HELDOUT = "data/heldout_set.json"
DISTILBERT_OOF = "logs/oof_predictions.json"
CATEGORIES = ["ack", "meeting", "faq", "support", "emotional", "ambiguous", "spam"]

# Must match app/distilbert_cv.py exactly.
N_FOLDS = 5
CV_SEED = 42

N_BOOTSTRAP = 10000
BOOTSTRAP_SEED = 20260824
LATENCY_REPEATS = 5   # timed passes over the corpus; first pass is warm-up


def make_model(kind):
    vec = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), sublinear_tf=True)
    if kind == "tfidf_lr":
        clf = LogisticRegression(C=1.0, max_iter=2000, random_state=0)
    elif kind == "tfidf_svm":
        clf = LinearSVC(C=1.0, random_state=0)
    else:
        raise ValueError(kind)
    return make_pipeline(vec, clf)


def text_of(e):
    # Same featurisation as distilbert_cv.py / train_final.py.
    return f"{e['subject']} {e['body']}"


def wilson(k, n, z=1.96):
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return centre - half, centre + half


def macro_f1(y_true, y_pred):
    _, _, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=CATEGORIES, average=None, zero_division=0)
    return float(f1.mean())


def bootstrap_f1(y_true, y_pred):
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    yt, yp = np.array(y_true), np.array(y_pred)
    n = len(yt)
    s = np.array([macro_f1(yt[i], yp[i])
                  for i in (rng.integers(0, n, n) for _ in range(N_BOOTSTRAP))])
    lo, hi = np.percentile(s, [2.5, 97.5])
    return float(lo), float(hi)


def summarise(name, y_true, y_pred):
    n = len(y_true)
    k = sum(t == p for t, p in zip(y_true, y_pred))
    lo, hi = wilson(k, n)
    f1 = macro_f1(y_true, y_pred)
    f1_lo, f1_hi = bootstrap_f1(y_true, y_pred)
    p, r, f, sup = precision_recall_fscore_support(
        y_true, y_pred, labels=CATEGORIES, average=None, zero_division=0)

    print(f"\n=== {name} ===")
    print(f"accuracy  {k}/{n} = {k / n:.4f}   95% Wilson CI [{lo:.4f}, {hi:.4f}]")
    print(f"macro-F1  {f1:.4f}            95% bootstrap CI [{f1_lo:.4f}, {f1_hi:.4f}]")
    print(f"  {'category':<12}{'n':>4}{'P':>8}{'R':>8}{'F1':>8}")
    for i, c in enumerate(CATEGORIES):
        print(f"  {c:<12}{sup[i]:>4}{p[i]:>8.3f}{r[i]:>8.3f}{f[i]:>8.3f}")
    return {
        "n": n, "correct": int(k), "accuracy": k / n, "accuracy_ci": [lo, hi],
        "macro_f1": f1, "macro_f1_ci": [f1_lo, f1_hi],
        "per_category": {c: {"n": int(sup[i]), "precision": float(p[i]),
                             "recall": float(r[i]), "f1": float(f[i])}
                         for i, c in enumerate(CATEGORIES)},
    }


def per_email_latency_ms(model, texts):
    """Classify one email per call, as the pipeline does. Returns per-email ms
    from the timed passes (the first pass over the corpus is discarded)."""
    times = []
    for rep in range(LATENCY_REPEATS + 1):
        for t in texts:
            start = time.perf_counter()
            model.predict([t])
            elapsed = (time.perf_counter() - start) * 1000
            if rep:
                times.append(elapsed)
    times.sort()
    return {
        "median_ms": statistics.median(times),
        "mean_ms": statistics.fmean(times),
        "p95_ms": times[int(0.95 * len(times)) - 1],
        "n_calls": len(times),
    }


def load_adjudicated(path):
    with open(path, newline="", encoding="utf-8") as f:
        return {row["orig_id"]: row["adjudicated_label"].strip().lower()
                for row in csv.DictReader(f)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adjudicated", help="adjudicated_ground_truth.csv for held-out labels")
    args = ap.parse_args()

    primary = json.load(open(PRIMARY))
    heldout = json.load(open(HELDOUT))
    ids = np.array([e["id"] for e in primary])
    X = np.array([text_of(e) for e in primary])
    labels = [e["true_category"] for e in primary]

    le = LabelEncoder()
    y = le.fit_transform(labels)
    skf = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=CV_SEED)
    folds = list(skf.split(X, y))

    # Verify the split matches DistilBERT's, if its OOF log is available.
    fold_of = {ids[i]: k for k, (_, te) in enumerate(folds, 1) for i in te}
    if Path(DISTILBERT_OOF).exists():
        ref = json.load(open(DISTILBERT_OOF))
        mismatch = [i for i in fold_of if ref.get(i, {}).get("fold") != fold_of[i]]
        if mismatch:
            raise SystemExit(f"fold assignment differs from {DISTILBERT_OOF}: {mismatch[:5]}")
        print(f"Fold assignment verified identical to {DISTILBERT_OOF}.")
    else:
        print(f"{DISTILBERT_OOF} not found; split built with the same code and "
              "seed as distilbert_cv.py but not cross-checked against it.")

    adjudicated = load_adjudicated(args.adjudicated) if args.adjudicated else None
    ho_true = [adjudicated.get(e["id"], e["true_category"]) if adjudicated
               else e["true_category"] for e in heldout]
    ho_label_note = ("adjudicated" if adjudicated
                     else "PRE-adjudication (not the paper's held-out ground truth)")

    cv_out, ho_out = {}, {}
    Path("logs").mkdir(exist_ok=True)
    for kind in ("tfidf_lr", "tfidf_svm"):
        fold_acc, oof, fit_s = [], {}, []
        for k, (tr, te) in enumerate(folds, 1):
            model = make_model(kind)
            t0 = time.perf_counter()
            model.fit(X[tr], y[tr])
            fit_s.append(time.perf_counter() - t0)
            pred = model.predict(X[te])
            fold_acc.append(float((pred == y[te]).mean()))
            for eid, p, t in zip(ids[te], pred, y[te]):
                oof[str(eid)] = {
                    "predicted_category": le.classes_[p],
                    "true_category": le.classes_[t],
                    "correct": bool(p == t),
                    "fold": k,
                }

        order = [str(i) for i in ids]
        m = summarise(f"{kind} — primary, 5-fold out-of-fold",
                      [oof[i]["true_category"] for i in order],
                      [oof[i]["predicted_category"] for i in order])
        m["fold_accuracies"] = fold_acc
        m["fold_mean"] = float(np.mean(fold_acc))
        m["fold_std"] = float(np.std(fold_acc))  # population std, as distilbert_cv.py
        m["mean_fit_seconds_per_fold"] = float(np.mean(fit_s))
        print("  folds: " + "  ".join(f"{a:.4f}" for a in fold_acc)
              + f"   mean {m['fold_mean']:.4f} ± {m['fold_std']:.4f}")
        cv_out[kind] = m
        with open(f"logs/{kind}_oof_predictions.json", "w") as f:
            json.dump(oof, f, indent=2)

        # Refit on all 363 for the held-out set, mirroring train_final.py.
        final = make_model(kind)
        final.fit(X, y)
        ho_pred = le.classes_[final.predict([text_of(e) for e in heldout])]
        h = summarise(f"{kind} — held-out (trained on all 363), {ho_label_note} labels",
                      ho_true, list(ho_pred))
        h["latency"] = per_email_latency_ms(final, [text_of(e) for e in primary])
        print(f"  per-email inference: median {h['latency']['median_ms']:.3f} ms, "
              f"p95 {h['latency']['p95_ms']:.3f} ms")
        h["rows"] = [{"id": e["id"], "true_category": t, "predicted_category": p}
                     for e, t, p in zip(heldout, ho_true, ho_pred)]
        ho_out[kind] = h

    meta = {"n_folds": N_FOLDS, "cv_seed": CV_SEED, "bootstrap_seed": BOOTSTRAP_SEED,
            "n_bootstrap": N_BOOTSTRAP, "heldout_labels": ho_label_note,
            "features": "TF-IDF word 1-2 grams, sublinear tf, fitted per fold",
            "hyperparameters": "C=1.0 for both, not tuned"}
    with open("logs/tfidf_cv_results.json", "w") as f:
        json.dump({"meta": meta, **cv_out}, f, indent=2)
    with open("logs/tfidf_heldout_results.json", "w") as f:
        json.dump({"meta": meta, **ho_out}, f, indent=2)
    print("\nSaved logs/tfidf_cv_results.json, logs/tfidf_{lr,svm}_oof_predictions.json, "
          "logs/tfidf_heldout_results.json")


if __name__ == "__main__":
    main()
