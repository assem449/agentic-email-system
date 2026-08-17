# trains and saves the model


import json
import numpy as np
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from datasets import Dataset
from transformers import (
    DistilBertTokenizerFast,
    DistilBertForSequenceClassification,
    TrainingArguments,
    Trainer,
)
import torch

# --- Load eval set ---
with open("data/eval_set.json") as f:
    data = json.load(f)

texts = [f"{d['subject']} {d['body']}" for d in data]
labels = [d["true_category"] for d in data]

# --- Encode labels ---
le = LabelEncoder()
encoded_labels = le.fit_transform(labels)

# Save label mapping
label_map = {i: label for i, label in enumerate(le.classes_)}
Path("data/label_map.json").write_text(json.dumps(label_map))
print("Labels:", label_map)

# --- Train/test split ---
X_train, X_test, y_train, y_test = train_test_split(
    texts, encoded_labels, test_size=0.2, random_state=42, stratify=encoded_labels
)

print(f"Train: {len(X_train)}, Test: {len(X_test)}")

# --- Tokenize ---
tokenizer = DistilBertTokenizerFast.from_pretrained("distilbert-base-uncased")

def tokenize(batch):
    return tokenizer(batch["text"], truncation=True, padding=True, max_length=128)

train_dataset = Dataset.from_dict({"text": X_train, "label": y_train.tolist()})
test_dataset = Dataset.from_dict({"text": X_test, "label": y_test.tolist()})

train_dataset = train_dataset.map(tokenize, batched=True)
test_dataset = test_dataset.map(tokenize, batched=True)

# --- Model ---
model = DistilBertForSequenceClassification.from_pretrained(
    "distilbert-base-uncased",
    num_labels=len(le.classes_),
)

# --- Training args ---
args = TrainingArguments(
    output_dir="data/distilbert_model",
    num_train_epochs=10,
    per_device_train_batch_size=8,
    per_device_eval_batch_size=8,
    eval_strategy="epoch",
    save_strategy="epoch",
    load_best_model_at_end=True,
    logging_steps=10,
    seed=42,
)

def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)
    acc = (preds == labels).mean()
    return {"accuracy": acc}

# --- Train ---
trainer = Trainer(
    model=model,
    args=args,
    train_dataset=train_dataset,
    eval_dataset=test_dataset,
    compute_metrics=compute_metrics,
)

trainer.train()
trainer.save_model("data/distilbert_model/final")
tokenizer.save_pretrained("data/distilbert_model/final")
print("Done — model saved to data/distilbert_model/final")