#!/usr/bin/env python3
"""Score the final model and the frozen rule set on a separately generated
held-out test set.

This answers a question cross-validation cannot: whether 92.56% reflects
learning the categories, or learning the house style of the model that
generated the corpus. Every email in eval_set.json came from one of seven
prompts, so CV folds contain siblings of their own test emails. If accuracy
holds on emails from different prompts and a different generating model, the
CV figure is validated. If it falls sharply, the gap is generator leakage.

Prerequisites:
    1. data/heldout_set.json exists (see heldout_prompts.md)
    2. ./venv/bin/python3 train_final.py has been run

Run from project root:
    ./venv/bin/python3 eval_heldout.py
"""
import json
from pathlib import Path

import torch
from transformers import (DistilBertForSequenceClassification,
                          DistilBertTokenizerFast)

from app.classifier import classify_email          # frozen rules v1
from app.metrics import report, CATEGORIES

MODEL_DIR = "models/distilbert_final"
HELDOUT = "data/heldout_set.json"
TRAIN = "data/eval_set.json"
MAX_LEN = 128


def contamination_check(heldout, train):
    """A held-out email that also appears in training invalidates the test."""
    def norm(e):
        return " ".join(f"{e['subject']} {e['body']}".lower().split())

    train_texts = {norm(e) for e in train}
    dupes = [e["id"] for e in heldout if norm(e) in train_texts]
    train_ids = {e["id"] for e in train}
    id_clash = [e["id"] for e in heldout if e["id"] in train_ids]

    print(f"Contamination check: {len(heldout)} held-out vs {len(train)} training")
    print(f"  exact text overlap : {len(dupes)}")
    print(f"  id collisions      : {len(id_clash)}")
    if dupes:
        print(f"  !! remove these before trusting the result: {dupes[:10]}")
    if id_clash:
        print(f"  !! duplicate ids: {id_clash[:10]}")
    return not (dupes or id_clash)


def main():
    for p in (HELDOUT, MODEL_DIR):
        if not Path(p).exists():
            raise SystemExit(f"missing: {p}")

    with open(HELDOUT) as f:
        heldout = json.load(f)
    with open(TRAIN) as f:
        train = json.load(f)

    clean = contamination_check(heldout, train)
    if not clean:
        print("\nAborting: held-out set overlaps training data.")
        raise SystemExit(1)

    labels_present = sorted({e["true_category"] for e in heldout})
    print(f"\nHeld-out categories: {labels_present}")
    missing = set(CATEGORIES) - set(labels_present)
    if missing:
        print(f"  note: no examples for {sorted(missing)} — those rows will read 0")

    # ---- DistilBERT trained on all 363
    tokenizer = DistilBertTokenizerFast.from_pretrained(MODEL_DIR)
    model = DistilBertForSequenceClassification.from_pretrained(MODEL_DIR)
    model.eval()

    distil_rows = []
    with torch.no_grad():
        for e in heldout:
            enc = tokenizer(f"{e['subject']} {e['body']}", truncation=True,
                            padding=True, max_length=MAX_LEN, return_tensors="pt")
            pred_id = int(model(**enc).logits.argmax(dim=-1)[0])
            distil_rows.append({
                "id": e["id"],
                "true_category": e["true_category"],
                "predicted_category": model.config.id2label[pred_id],
            })

    # ---- frozen rules v1
    rules_rows = [{
        "id": e["id"],
        "true_category": e["true_category"],
        "predicted_category": classify_email(e["subject"], e["body"]),
    } for e in heldout]

    m_rules = report(rules_rows, "Rules v1 (frozen) — held-out")
    m_distil = report(distil_rows, "DistilBERT (trained on all 363) — held-out")

    # ---- the comparison that matters
    CV_ACC, CV_MACRO_F1 = 0.9256, 0.923
    print("\n=== generalisation gap ===")
    print(f"  cross-validated accuracy (in-corpus) : {CV_ACC:.4f}")
    print(f"  held-out accuracy (fresh prompts)    : {m_distil['accuracy']:.4f}")
    drop = CV_ACC - m_distil["accuracy"]
    print(f"  drop                                 : {drop:+.4f}")
    print(f"  macro-F1 {CV_MACRO_F1:.3f} -> {m_distil['macro_f1']:.3f} "
          f"({m_distil['macro_f1'] - CV_MACRO_F1:+.3f})")
    if drop < 0.05:
        print("\n  Small drop. The CV estimate is not substantially inflated by")
        print("  generator artifacts. Report both figures and say so.")
    elif drop < 0.15:
        print("\n  Moderate drop. Report both. The honest reading is that CV")
        print("  overstates performance on text from a different generator.")
    else:
        print("\n  Large drop. The CV figure largely reflects recognising the")
        print("  generating prompts. This is a finding, not a failure — but the")
        print("  held-out number is the one to headline.")
    print("\n  Caveat for the writeup: the held-out set holds the domain fixed,")
    print("  so this measures robustness to generation process, not to real")
    print("  inbox traffic, which remains untested.")

    Path("logs").mkdir(exist_ok=True)
    with open("logs/heldout_results.json", "w") as f:
        json.dump({"rules": rules_rows, "distilbert": distil_rows,
                   "macro_rules": m_rules, "macro_distilbert": m_distil,
                   "cv_accuracy": CV_ACC, "cv_macro_f1": CV_MACRO_F1}, f, indent=2)
    print("\nSaved to logs/heldout_results.json")


if __name__ == "__main__":
    main()
