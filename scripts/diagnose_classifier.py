"""Check which classifier the app is really using, and how it scores a set
of test emails.

    python scripts/diagnose_classifier.py data/academic/seed_categories_student.json

Run it where the app runs (Render: the Shell tab) to see the live setup, or
locally with the same environment variables. For each email it prints the
expected category (from the "expected" note), the top 3 predictions with
probabilities, and what the app would route on (below the confidence
threshold it becomes "ambiguous").

Nothing is sent, labelled or stored.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <seed file.json>")
        sys.exit(1)

    classifier = os.environ.get("CLASSIFIER", "rules")
    print(f"CLASSIFIER            = {classifier}")
    if classifier != "distilbert":
        print("\n-> The rules classifier is live, not the trained model. Set "
              "CLASSIFIER=distilbert in the environment.")
        sys.exit(0)

    import torch
    import app.distilbert_classifier as dc

    dc._load()
    bundled = Path(dc.MODEL_PATH) / "label_map.json"
    print(f"DISTILBERT_MODEL_PATH = {dc.MODEL_PATH}")
    print(f"DISTILBERT_MODEL_REPO = {dc.MODEL_REPO}")
    print(f"label map             = {bundled if bundled.exists() else dc.LABEL_MAP_PATH + '  (fallback: NOT bundled with the model)'}")
    print(f"model outputs         = {dc._model.config.num_labels}")
    print(f"category names        = {[dc._label_map[i] for i in sorted(dc._label_map)]}")
    if dc._model.config.num_labels != len(dc._label_map):
        print("\n-> MISMATCH: the model and the label map have a different number of "
              "categories. Re-upload with scripts/upload_model_to_hf.py --model-dir.")
    if "faq" in dc._label_map.values():
        print("\n-> These are the OLD v1 categories: the old model or old label map is loaded.")
    print()

    emails = json.loads(Path(sys.argv[1]).read_text())
    correct = 0
    for e in emails:
        expected = (e.get("expected") or "").split(" ")[0]
        inputs = dc._tokenizer(f"{e['subject']} {e['body']}".strip(), return_tensors="pt",
                               truncation=True, padding=True, max_length=128)
        with torch.no_grad():
            probs = torch.softmax(dc._model(**inputs).logits, dim=-1)[0]
        top = torch.topk(probs, k=min(3, len(probs)))
        ranked = [(dc._label_map[i.item()], p.item()) for p, i in zip(top.values, top.indices)]
        routed = ranked[0][0] if ranked[0][1] >= dc.CONFIDENCE_THRESHOLD else "ambiguous"
        ok = routed == expected
        correct += ok
        print(f"{'OK ' if ok else 'XX '} expected {expected:26} routed {routed:26} | "
              + ", ".join(f"{c} {p:.2f}" for c, p in ranked)
              + f" | {e['subject'][:50]}")
    print(f"\n{correct}/{len(emails)} routed to the expected category "
          f"(confidence threshold {dc.CONFIDENCE_THRESHOLD}).")


if __name__ == "__main__":
    main()
