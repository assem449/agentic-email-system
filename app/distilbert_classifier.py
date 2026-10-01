# loads the saved model and classifies emails

import json
import os
from pathlib import Path

# transformers/torch are imported lazily, inside _load() — not here —
# so this module (and _ensure_model_present's download logic) can be
# imported and tested without either installed, and so nothing pulls
# them in just by importing this file (app/graph.py already only
# imports this module at all when CLASSIFIER=distilbert).

# Local model path -- where the trained weights actually live once
# available. Defaults to the research artifact's local path for local
# dev; on a deploy this is pointed at the persistent disk
# (DISTILBERT_MODEL_PATH=/data/distilbert_model) so it's downloaded once
# and survives restarts/redeploys rather than re-fetched every boot.
MODEL_PATH = os.environ.get("DISTILBERT_MODEL_PATH", "data/distilbert_model/final")
LABEL_MAP_PATH = "data/label_map.json"

# If set, and MODEL_PATH doesn't already have the weights, download them
# from this Hugging Face Hub repo instead of expecting a local file --
# the trained model is 255MB+, gitignored (see the earlier git push
# failure over this exact file), and was never part of any deploy's
# checkout. See scripts/upload_model_to_hf.py for the one-time upload,
# run from wherever the model was actually trained.
MODEL_REPO = os.environ.get("DISTILBERT_MODEL_REPO")

_model = None
_tokenizer = None
_label_map = None


def _ensure_model_present() -> None:
    path = Path(MODEL_PATH)
    if path.exists() and any(path.iterdir()):
        return  # already there, from a previous download or local training

    if not MODEL_REPO:
        raise RuntimeError(
            f"{MODEL_PATH} doesn't exist and DISTILBERT_MODEL_REPO isn't set — "
            "nowhere to get the trained model from. Either put the trained "
            "model there yourself, or set DISTILBERT_MODEL_REPO to a Hugging "
            "Face Hub repo id (see scripts/upload_model_to_hf.py for the "
            "one-time upload)."
        )

    from huggingface_hub import snapshot_download
    print(f"Downloading DistilBERT model from https://huggingface.co/{MODEL_REPO} ...")
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=MODEL_REPO, local_dir=str(path))
    print("Model downloaded.")


def _load():
    global _model, _tokenizer, _label_map
    if _model is None:
        _ensure_model_present()
        from transformers import DistilBertTokenizerFast, DistilBertForSequenceClassification
        _tokenizer = DistilBertTokenizerFast.from_pretrained(MODEL_PATH)
        _model = DistilBertForSequenceClassification.from_pretrained(MODEL_PATH)
        _model.eval()
        _label_map = {int(k): v for k, v in json.loads(
            Path(LABEL_MAP_PATH).read_text()
        ).items()}

def classify_email_distilbert(subject: str, body: str) -> str:
    _load()
    import torch
    text = f"{subject} {body}".strip()
    inputs = _tokenizer(
        text, return_tensors="pt", truncation=True,
        padding=True, max_length=128
    )
    with torch.no_grad():
        logits = _model(**inputs).logits
    pred_id = logits.argmax(dim=-1).item()
    return _label_map[pred_id]
