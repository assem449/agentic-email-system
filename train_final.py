#!/usr/bin/env python3
"""Train ONE DistilBERT model on the full 363-email corpus.

Why this exists: distilbert_cv.py produces five fold models, each trained on
80% of the data. Those are the right thing for estimating variance, but you
cannot test a fold model on a fresh held-out set -- you would be reporting the
performance of a model trained on four fifths of the data while claiming it
represents the system. The standard arrangement is: cross-validation estimates
generalisation and its variance, and the deployed model is trained on
everything. This script produces that deployed model.

Run from project root:
    ./venv/bin/python3 train_final.py

Takes roughly five times a single fold -- a few minutes on CPU.
"""
import json
import os
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset
from transformers import (DistilBertForSequenceClassification,
                          DistilBertTokenizerFast, Trainer, TrainingArguments)

MODEL_NAME = "distilbert-base-uncased"
DATA = "data/eval_set.json"
LABEL_MAP = "data/label_map.json"
OUT_DIR = "models/distilbert_final"
MAX_LEN = 128
EPOCHS = 10
BATCH = 8
SEED = 20260824


def load_label_map(path):
    """Accepts either {"ack": 0, ...} or {"0": "ack", ...}."""
    with open(path) as f:
        raw = json.load(f)
    first_key = next(iter(raw))
    if str(first_key).isdigit():                 # id -> label
        id2label = {int(k): v for k, v in raw.items()}
        label2id = {v: k for k, v in id2label.items()}
    else:                                        # label -> id
        label2id = {k: int(v) for k, v in raw.items()}
        id2label = {v: k for k, v in label2id.items()}
    return label2id, id2label


class EmailDataset(Dataset):
    def __init__(self, encodings, labels):
        self.encodings = encodings
        self.labels = labels

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, i):
        item = {k: torch.tensor(v[i]) for k, v in self.encodings.items()}
        item["labels"] = torch.tensor(self.labels[i])
        return item


def main():
    torch.manual_seed(SEED)
    np.random.seed(SEED)

    label2id, id2label = load_label_map(LABEL_MAP)
    with open(DATA) as f:
        emails = json.load(f)

    # Must match the featurisation used at inference time in
    # app/distilbert_classifier.py: subject and body concatenated.
    texts = [f"{e['subject']} {e['body']}" for e in emails]
    labels = [label2id[e["true_category"]] for e in emails]

    print(f"Training on all {len(texts)} emails "
          f"across {len(label2id)} categories.")
    dist = {}
    for e in emails:
        dist[e["true_category"]] = dist.get(e["true_category"], 0) + 1
    for c, n in sorted(dist.items(), key=lambda kv: -kv[1]):
        print(f"  {c:<12}{n:>4}")

    tokenizer = DistilBertTokenizerFast.from_pretrained(MODEL_NAME)
    encodings = tokenizer(texts, truncation=True, padding=True, max_length=MAX_LEN)
    dataset = EmailDataset(encodings, labels)

    model = DistilBertForSequenceClassification.from_pretrained(
        MODEL_NAME, num_labels=len(label2id),
        id2label=id2label, label2id=label2id)

    args = TrainingArguments(
        output_dir="models/_train_final_tmp",
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=BATCH,
        logging_steps=50,
        save_strategy="no",
        seed=SEED,
        report_to=[],
    )
    Trainer(model=model, args=args, train_dataset=dataset).train()

    Path(OUT_DIR).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(OUT_DIR)
    tokenizer.save_pretrained(OUT_DIR)
    with open(os.path.join(OUT_DIR, "training_manifest.json"), "w") as f:
        json.dump({
            "trained_on": DATA,
            "n_emails": len(texts),
            "category_distribution": dist,
            "epochs": EPOCHS,
            "batch_size": BATCH,
            "max_length": MAX_LEN,
            "seed": SEED,
            "base_model": MODEL_NAME,
            "note": ("Trained on 100% of eval_set.json. Valid ONLY for scoring a "
                     "separately generated held-out set. Scoring this model on "
                     "eval_set.json reproduces the original leakage."),
        }, f, indent=2)

    print(f"\nSaved to {OUT_DIR}")
    print("This model has seen every email in eval_set.json. Do not score it on "
          "that file -- use eval_heldout.py against the held-out set.")


if __name__ == "__main__":
    main()
