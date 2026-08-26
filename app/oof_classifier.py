"""
Leakage-free stand-in for classify_email_distilbert, for use in eval_run.py.

Instead of calling the final model (which trained on 100% of the data,
so evaluating it against eval_set.json would leak), this looks up each
email's prediction from logs/oof_predictions.json — produced by
distilbert_cv.py, where every prediction came from a fold model that
never saw that email during training.

Integration into eval_run.py:

    from oof_classifier import classify_email_distilbert_oof

    # replace this line:
    #   distilbert_results = run_eval(classify_email_distilbert, "DistilBERT Classifier (v2)")
    # with:
    distilbert_results = run_eval(classify_email_distilbert_oof, "DistilBERT Classifier (v2, 5-fold CV)")

Note: run_eval() in your current eval_run.py calls the classifier as
classifier_fn(subject, body) with no email id, so you'll need one small
change — pass the id through so this lookup works. Easiest fix: in
run_eval()'s classify_node, change the call to pass item id via a
closure, e.g.:

    def make_node(fn, item_id):
        def classify_node(state):
            state["category"] = fn(item_id, state["subject"], state["body"])
            return state
        return classify_node

    graph_module.classify_node = make_node(classifier_fn, item["id"])

...set inside the per-item loop in run_eval(), right before graph.invoke().
(classify_email / classify_email_distilbert for the other two baselines
can just ignore the extra id argument, or you can keep two separate
node-maker functions — one id-aware for DistilBERT-CV, one not, for
the others.)
"""

import json
from pathlib import Path

_oof = None


def _load():
    global _oof
    if _oof is None:
        path = Path("logs/oof_predictions.json")
        if not path.exists():
            raise FileNotFoundError(
                "logs/oof_predictions.json not found — run distilbert_cv.py first."
            )
        _oof = json.loads(path.read_text())


def classify_email_distilbert_oof(email_id: str, subject: str, body: str) -> str:
    _load()
    if email_id not in _oof:
        raise KeyError(
            f"No OOF prediction found for email id {email_id!r} — "
            "make sure eval_set.json matches the file distilbert_cv.py was run on."
        )
    return _oof[email_id]["predicted_category"]