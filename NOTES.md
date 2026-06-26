## Classifier limitations log

### 2026-06-26 — Exact-match brittleness on natural phrasing
- Rule-based classifier uses literal regex anchors (^...$) for `ack` and 
  keyword lists for `faq`.
- Two failure modes observed in eval_run.py (n=14 eval set):
  - "ack": "Thanks so much!" and "Got it, appreciate the update." both 
    misclassified as "ambiguous" (exact-match regex doesn't tolerate 
    trailing/leading words)
  - "faq": "Can you tell me how to get a new API key?" misclassified as 
    "ambiguous" despite low ChromaDB retrieval distance (0.42) to an 
    existing FAQ — classifier and retrieval layers don't share signal
- Result: accuracy 85.71% on small eval set (12/14 correct)
- Implication for paper: rule-based layer trades recall for precision/
  speed; supports planned DistilBERT classifier upgrade as future work / 
  ablation comparison