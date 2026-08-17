# loads the saved model and classifies emails

import json
from pathlib import Path
from transformers import DistilBertTokenizerFast, DistilBertForSequenceClassification
import torch

MODEL_PATH = "data/distilbert_model/final"
LABEL_MAP_PATH = "data/label_map.json"

_model = None
_tokenizer = None
_label_map = None

def _load():
    global _model, _tokenizer, _label_map
    if _model is None:
        _tokenizer = DistilBertTokenizerFast.from_pretrained(MODEL_PATH)
        _model = DistilBertForSequenceClassification.from_pretrained(MODEL_PATH)
        _model.eval()
        _label_map = {int(k): v for k, v in json.loads(
            Path(LABEL_MAP_PATH).read_text()
        ).items()}

def classify_email_distilbert(subject: str, body: str) -> str:
    _load()
    text = f"{subject} {body}".strip()
    inputs = _tokenizer(
        text, return_tensors="pt", truncation=True,
        padding=True, max_length=128
    )
    with torch.no_grad():
        logits = _model(**inputs).logits
    pred_id = logits.argmax(dim=-1).item()
    return _label_map[pred_id]