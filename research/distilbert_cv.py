"""
Stratified 5-fold cross-validation for the DistilBERT email classifier.

Why this exists (see professor feedback point 1):
  The original distilbert_trainer.py does an 80/20 split for training,
  but eval_run.py then evaluates the saved model against the FULL
  eval_set.json — including the 80% the model was trained on. The
  reported accuracy was therefore mostly measuring memorization, not
  generalization.

What this script does instead:
  - Splits the eval set into 5 stratified folds (same class distribution
    in every fold).
  - For each fold: trains a fresh DistilBERT model on the other 4 folds,
    then predicts ONLY on the held-out fold (data that model has never
    seen).
  - Collects these out-of-fold (OOF) predictions across all 5 folds —
    together they cover 100% of the dataset, and every single prediction
    comes from a model that never trained on that email.
  - Reports per-fold accuracy plus mean ± std (what the professor asked
    for), and also the overall accuracy computed from the pooled OOF
    predictions (a second, complementary number worth reporting too).
  - Writes oof_predictions.json: {email_id: predicted_category}, which
    eval_run.py can use to compute token/latency reduction WITHOUT
    leakage (see integration note at the bottom of this file).

Usage:
    ./venv/bin/python3 distilbert_cv.py

Runtime note: this trains 5 full DistilBERT models instead of 1, so
expect roughly 5x the runtime of the original trainer.py. Reduce
num_train_epochs below if you need it to run faster before the deadline
— fewer epochs is a reasonable, disclosable tradeoff; reusing the same
80/20 split is not.
"""

import json
import numpy as np
from pathlib import Path
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import LabelEncoder
from datasets import Dataset
from transformers import (
    DistilBertTokenizerFast,
    DistilBertForSequenceClassification,
    TrainingArguments,
    Trainer,
)
import torch

N_FOLDS = 5
SEED = 42
MODEL_NAME = "distilbert-base-uncased"
MAX_LENGTH = 128
NUM_EPOCHS = 10  # match original trainer; lower this if runtime is a problem

# --- Load eval set ---
with open("data/eval_set.json") as f:
    data = json.load(f)

ids = [d["id"] for d in data]
texts = [f"{d['subject']} {d['body']}" for d in data]
labels = [d["true_category"] for d in data]

# --- Encode labels (same mapping for every fold — fit once on full label set) ---
le = LabelEncoder()
encoded_labels = le.fit_transform(labels)
label_map = {i: label for i, label in enumerate(le.classes_)}
Path("data/label_map.json").write_text(json.dumps(label_map))
print("Labels:", label_map)

tokenizer = DistilBertTokenizerFast.from_pretrained(MODEL_NAME)


def tokenize(batch):
    return tokenizer(batch["text"], truncation=True, padding=True, max_length=MAX_LENGTH)


def compute_metrics(eval_pred):
    logits, labels_ = eval_pred
    preds = np.argmax(logits, axis=-1)
    acc = (preds == labels_).mean()
    return {"accuracy": acc}


skf = StratifiedKFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED)

fold_accuracies = []
oof_predictions = {}  # email_id -> predicted category (string)
fold_reports = []

X = np.array(texts)
y = encoded_labels
ID = np.array(ids)

for fold_idx, (train_idx, test_idx) in enumerate(skf.split(X, y), start=1):
    print(f"\n{'='*50}")
    print(f"FOLD {fold_idx}/{N_FOLDS}")
    print(f"{'='*50}")

    X_train, X_test = X[train_idx].tolist(), X[test_idx].tolist()
    y_train, y_test = y[train_idx].tolist(), y[test_idx].tolist()
    ids_test = ID[test_idx].tolist()

    print(f"Train: {len(X_train)}, Held-out (never seen by this model): {len(X_test)}")

    train_dataset = Dataset.from_dict({"text": X_train, "label": y_train})
    test_dataset = Dataset.from_dict({"text": X_test, "label": y_test})
    train_dataset = train_dataset.map(tokenize, batched=True)
    test_dataset = test_dataset.map(tokenize, batched=True)

    model = DistilBertForSequenceClassification.from_pretrained(
        MODEL_NAME, num_labels=len(le.classes_)
    )

    args = TrainingArguments(
        output_dir=f"data/distilbert_cv/fold_{fold_idx}",
        num_train_epochs=NUM_EPOCHS,
        per_device_train_batch_size=8,
        per_device_eval_batch_size=8,
        eval_strategy="epoch",
        save_strategy="no",  # don't keep 5 full checkpoints unless you want them
        logging_steps=10,
        seed=SEED,
        report_to=[],
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_dataset,
        eval_dataset=test_dataset,
        compute_metrics=compute_metrics,
    )

    trainer.train()
    eval_result = trainer.evaluate()
    fold_acc = eval_result["eval_accuracy"]
    fold_accuracies.append(fold_acc)
    print(f"Fold {fold_idx} accuracy (held-out, never trained on): {fold_acc:.4f}")

    # --- Predict on held-out fold to build OOF predictions ---
    predictions = trainer.predict(test_dataset)
    pred_ids = np.argmax(predictions.predictions, axis=-1)
    for eid, pred_id, true_id in zip(ids_test, pred_ids, y_test):
        oof_predictions[eid] = {
            "predicted_category": label_map[int(pred_id)],
            "true_category": label_map[int(true_id)],
            "correct": int(pred_id) == true_id,
            "fold": fold_idx,
        }

    fold_reports.append({"fold": fold_idx, "accuracy": fold_acc, "n_test": len(X_test)})

    # free GPU/CPU memory between folds
    del model, trainer
    torch.cuda.empty_cache() if torch.cuda.is_available() else None

# --- Aggregate results ---
mean_acc = float(np.mean(fold_accuracies))
std_acc = float(np.std(fold_accuracies))

pooled_correct = sum(1 for v in oof_predictions.values() if v["correct"])
pooled_acc = pooled_correct / len(oof_predictions)

print(f"\n{'='*50}")
print("5-FOLD CROSS-VALIDATION RESULTS")
print(f"{'='*50}")
for r in fold_reports:
    print(f"  Fold {r['fold']}: {r['accuracy']:.4f}  (n={r['n_test']})")
print(f"\nMean accuracy: {mean_acc:.4f} ± {std_acc:.4f}")
print(f"Pooled OOF accuracy (all {len(oof_predictions)} emails, each predicted "
      f"by a model that never trained on it): {pooled_acc:.4f}")

# --- Save everything ---
Path("logs").mkdir(exist_ok=True)
with open("logs/distilbert_cv_results.json", "w") as f:
    json.dump({
        "fold_accuracies": fold_accuracies,
        "mean_accuracy": mean_acc,
        "std_accuracy": std_acc,
        "pooled_oof_accuracy": pooled_acc,
        "n_folds": N_FOLDS,
        "seed": SEED,
    }, f, indent=2)

with open("logs/oof_predictions.json", "w") as f:
    json.dump(oof_predictions, f, indent=2)

print("\nSaved logs/distilbert_cv_results.json (report this mean ± std in the paper)")
print("Saved logs/oof_predictions.json (leakage-free predictions for every email)")

# --- Train final deployment model on ALL data ---
# This is the model that actually ships in the pipeline. Its accuracy is NOT
# independently verified (it trained on everything) — its expected
# performance is what the CV mean above estimates. State this explicitly
# in the paper: the deployed model uses all available data for the best
# real-world performance, and CV is how you estimate how well it generalizes.
print("\nTraining final deployment model on full dataset...")
full_dataset = Dataset.from_dict({"text": texts, "label": encoded_labels.tolist()})
full_dataset = full_dataset.map(tokenize, batched=True)

final_model = DistilBertForSequenceClassification.from_pretrained(
    MODEL_NAME, num_labels=len(le.classes_)
)
final_args = TrainingArguments(
    output_dir="data/distilbert_model",
    num_train_epochs=NUM_EPOCHS,
    per_device_train_batch_size=8,
    seed=SEED,
    report_to=[],
)
final_trainer = Trainer(model=final_model, args=final_args, train_dataset=full_dataset)
final_trainer.train()
final_trainer.save_model("data/distilbert_model/final")
tokenizer.save_pretrained("data/distilbert_model/final")
print("Final deployment model saved to data/distilbert_model/final")