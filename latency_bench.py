#!/usr/bin/env python3
"""Per-email classifier inference latency for every routing classifier.

The paper's latency figures (Table I) are handler-only: classify_node was
not timed, and in eval_run.py DistilBERT's predictions are out-of-fold
lookups, so its inference cost never entered any reported number. This
script measures what each classifier costs per email as deployed, one email
per call (the pipeline classifies one message at a time), on the machine it
runs on. eval_run.py uses the same timing functions to add classification
time to every routed email and report end-to-end latency.

Classifiers:
  rules       app/classifier.py (frozen v1)
  tfidf_lr    TF-IDF + logistic regression, fitted on all 363 (tfidf_baseline.py)
  tfidf_svm   TF-IDF + linear SVM, fitted on all 363
  distilbert  models/distilbert_final (run train_final.py first). If the
              weights are missing, the base distilbert-base-uncased with a
              fresh 7-way head is timed instead: identical architecture and
              sequence length, so identical inference cost, but its
              predictions are meaningless -- timing only. The output says
              which was used.

Reported: one-off load time, then median / mean / p95 per-email latency over
REPEATS timed passes of the 363-email corpus (one warm-up pass discarded).
CPU only, default torch thread count; both are printed so the paper can
state the hardware.

Run from project root (no API calls):
    python3 latency_bench.py [--skip-distilbert]
"""
import argparse
import json
import os
import platform
import statistics
import time
from pathlib import Path

PRIMARY = "data/eval_set.json"
DISTIL_DIR = "models/distilbert_final"
MAX_LEN = 128
REPEATS = 3


def text_of(subject, body):
    return f"{subject} {body}"


# ---------------------------------------------------------------- loaders
# Each returns fn(subject, body) -> category, matching the pipeline's
# classifier signature, so eval_run.py can time the deployed model.

def load_rules():
    from app.classifier import classify_email
    return classify_email, "rules v1 (frozen)"


def load_tfidf(kind):
    import numpy as np
    from sklearn.preprocessing import LabelEncoder
    from tfidf_baseline import make_model, text_of as tf_text

    primary = json.load(open(PRIMARY))
    le = LabelEncoder()
    y = le.fit_transform([e["true_category"] for e in primary])
    model = make_model(kind)
    model.fit(np.array([tf_text(e) for e in primary]), y)

    def classify(subject, body):
        return le.classes_[model.predict([text_of(subject, body)])[0]]

    return classify, f"{kind} (fitted on all 363)"


def load_distilbert():
    import torch
    from transformers import (DistilBertForSequenceClassification,
                              DistilBertTokenizerFast)

    has_weights = any(Path(DISTIL_DIR, f).exists()
                      for f in ("model.safetensors", "pytorch_model.bin"))
    tokenizer = DistilBertTokenizerFast.from_pretrained(DISTIL_DIR)
    if has_weights:
        model = DistilBertForSequenceClassification.from_pretrained(DISTIL_DIR)
        note = f"distilbert ({DISTIL_DIR})"
    else:
        model = DistilBertForSequenceClassification.from_pretrained(
            "distilbert-base-uncased", num_labels=7)
        note = ("distilbert-base-uncased, untrained head -- TIMING ONLY "
                f"({DISTIL_DIR} has no weights; run train_final.py)")
    model.eval()
    id2label = model.config.id2label

    def classify(subject, body):
        # Same tokenisation as app/distilbert_classifier.py.
        enc = tokenizer(text_of(subject, body).strip(), return_tensors="pt",
                        truncation=True, padding=True, max_length=MAX_LEN)
        with torch.no_grad():
            pred = int(model(**enc).logits.argmax(dim=-1)[0])
        return id2label[pred]

    return classify, note


LOADERS = {
    "rules": load_rules,
    "tfidf_lr": lambda: load_tfidf("tfidf_lr"),
    "tfidf_svm": lambda: load_tfidf("tfidf_svm"),
    "distilbert": load_distilbert,
}


def timed_load(name):
    start = time.perf_counter()
    fn, note = LOADERS[name]()
    return fn, note, (time.perf_counter() - start) * 1000


def time_call(fn, subject, body):
    start = time.perf_counter()
    fn(subject, body)
    return (time.perf_counter() - start) * 1000


def bench(fn, emails, repeats=REPEATS):
    times = []
    for rep in range(repeats + 1):
        for e in emails:
            ms = time_call(fn, e["subject"], e["body"])
            if rep:  # discard warm-up pass
                times.append(ms)
    times.sort()
    return {"median_ms": statistics.median(times),
            "mean_ms": statistics.fmean(times),
            "p95_ms": times[int(0.95 * len(times)) - 1],
            "n_calls": len(times)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-distilbert", action="store_true")
    args = ap.parse_args()

    emails = json.load(open(PRIMARY))
    names = [n for n in LOADERS if not (args.skip_distilbert and n == "distilbert")]

    hw = {"platform": platform.platform(), "processor": platform.processor(),
          "cpu_count": os.cpu_count()}
    try:
        import torch
        hw["torch_threads"] = torch.get_num_threads()
        hw["cuda"] = torch.cuda.is_available()
    except ImportError:
        pass
    print("Hardware:", hw)

    out = {"hardware": hw, "n_emails": len(emails), "repeats": REPEATS}
    print(f"\n{'classifier':<12}{'load ms':>10}{'median':>10}{'mean':>10}{'p95':>10}")
    for name in names:
        fn, note, load_ms = timed_load(name)
        r = bench(fn, emails)
        r.update(load_ms=load_ms, note=note)
        out[name] = r
        print(f"{name:<12}{load_ms:>10.1f}{r['median_ms']:>10.3f}"
              f"{r['mean_ms']:>10.3f}{r['p95_ms']:>10.3f}   {note}")

    Path("logs").mkdir(exist_ok=True)
    with open("logs/latency_bench.json", "w") as f:
        json.dump(out, f, indent=2)
    print("\nSaved logs/latency_bench.json")


if __name__ == "__main__":
    main()
