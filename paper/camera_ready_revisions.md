# Camera-ready revisions (deadline Nov 20)

Written against `paper_v15.pdf` and the code on `main`. Section and table
numbers refer to v15. `[[...]]` marks a number that has to come from a run
you do locally (it needs the Anthropic API key and/or the DistilBERT
weights, and neither is available in the repo). Everything else is either
already in v15 or was computed from the repo as committed.

## How to produce the missing numbers

Run from the project root, in this order:

```bash
pip install -r requirements.txt
```

```bash
python3 tfidf_baseline.py --adjudicated adjudicated_ground_truth.csv
```

```bash
python3 app/distilbert_cv.py
```

```bash
python3 train_final.py
```

```bash
python3 latency_bench.py
```

```bash
python3 eval_run.py
```

```bash
python3 app/metrics.py
```

- `tfidf_baseline.py` runs on CPU in seconds and needs no API key. Once
  `logs/oof_predictions.json` exists, it checks that its folds match
  DistilBERT's, so you can run it again after `distilbert_cv.py` for that
  check.
- `distilbert_cv.py` and `train_final.py` regenerate the out-of-fold
  predictions and the deployed model. Neither is in the repo: `logs/` is
  gitignored and the model weights were never committed. `distilbert_cv.py`
  uses seed 42 and should reproduce 336/363. If it doesn't exactly,
  report what you get.
- `latency_bench.py` times per-email classifier inference. Run it on the
  laptop the paper refers to ("roughly 64 seconds on a laptop CPU").
- `eval_run.py` is the only step that calls the API (~$1–2 in total). It
  now also routes both TF-IDF baselines and reports end-to-end latency.

---

## 1. Generator models and prompts

**Repo:** `data/DATASET.md` is the dataset card. The generator model names,
dates, settings and the 14 prompts are `TODO(author)` because they are
not recorded anywhere in the repository. Fill them in from the chat or API
history of the account that generated the emails. If a prompt really can't
be recovered, say so in the paper rather than reconstructing it.

**Also commit `adjudicated_ground_truth.csv`.** `data/heldout_set.json`
holds the **pre-adjudication** labels: its counts are ack 15 / support 15,
while Table II has 13 / 18. So none of the paper's held-out figures can be
reproduced from the repo as it stands. `*.csv` is gitignored, so add it
with `git add -f`.

**Paper, new Appendix A (or a paragraph at the end of §V-A):**

```latex
\paragraph{Generation details.} The primary corpus was generated with
[[MODEL A, version]] via [[API / interface]] in [[month year]] using seven
category-specific prompts; the held-out corpus was generated with
[[MODEL B, version]] in [[month year]] using seven reworded prompts. All
fourteen prompts are reproduced verbatim in [Appendix A / the repository,
\texttt{data/DATASET.md}]. Replies on the LLM path are produced by Claude
Sonnet~4.6 (\texttt{claude-sonnet-4-6}) under the system prompt in the
repository; this model was not used to generate either corpus.
```

Delete the last clause if Sonnet 4.6 *was* one of the generators. If it was,
say so explicitly, because a reviewer will ask whether the response model
saw its own house style.

**Acknowledgment:** it currently says the emails were generated "under the
prompts described in Section V". Change this to "…under the prompts
reproduced in Appendix A / released with the code".

---

## 2. TF-IDF baselines

**Code:** `tfidf_baseline.py`. Two classifiers on TF-IDF features of word
1–2 grams (sublinear tf), fitted inside each fold on training emails only:
logistic regression and a linear SVM, both with C = 1.0 and no tuning. The
split is built exactly as in `app/distilbert_cv.py`: `LabelEncoder`, then
`StratifiedKFold(5, shuffle=True, random_state=42)`. The reporting matches
the paper: Wilson CIs, and a 10,000-resample bootstrap for macro-F1 with
seed 20260824. Results are committed in `results/tfidf/`.

**Primary corpus (5-fold out-of-fold), computed from the repo:**

| System | Acc. (pooled OOF) | 95% CI | Fold mean ± sd | Macro-F1 | 95% CI |
|---|---|---|---|---|---|
| Rules v1 (frozen) | 39.67% (144/363) | — | — | 0.386 | 0.333–0.435 |
| TF-IDF + LR | **79.06%** (287/363) | 74.6–82.9 | 79.07 ± 3.70 | **0.792** | 0.748–0.832 |
| TF-IDF + linear SVM | **84.57%** (307/363) | 80.5–87.9 | 84.57 ± 3.20 | **0.842** | 0.803–0.877 |
| DistilBERT v2 | 92.56% (336/363) | 89.4–94.8 | 92.57 ± 1.85 | 0.923 | 0.894–0.949 |

The SVM and DistilBERT accuracy intervals are disjoint, so on the primary
corpus DistilBERT's lead over the strongest linear baseline holds up.

**Held-out corpus: read this before writing anything.** On the
pre-adjudication labels in the repo, the linear SVM scores **88/105
(83.81%), macro-F1 0.841** and LR scores 81/105 (77.14%), macro-F1 0.779.
DistilBERT scores 84.76% / 0.851 on the adjudicated labels. The label sets
differ, so these figures can't be compared yet. Rerun with `--adjudicated`.
If the SVM figure holds after adjudication, it changes the story in §V-E:

- DistilBERT drops 7.80 points from CV to held-out. The SVM would drop
  about 0.8.
- On the held-out corpus, the generalisation test the paper treats as the
  stronger evidence, the two would be statistically indistinguishable.

That is worth reporting rather than burying. It suggests part of
DistilBERT's in-corpus lead comes from fitting the primary generator's
style, which is exactly the risk §V-E describes. Below is suggested text
for the case where the gap stays small; adjust it to the adjudicated
numbers.

**Table I: add two rows** (fill token/cost/latency from `eval_run.py`):

```latex
TF-IDF + LR (OOF)    & 79.06\% & 0.792 & [[tok]] & [[cost]] & [[lat]] \\
TF-IDF + SVM (OOF)   & 84.57\% & 0.842 & [[tok]] & [[cost]] & [[lat]] \\
```

**§IV-B, one sentence after the DistilBERT description:**

```latex
As an intermediate baseline we train two linear classifiers on TF-IDF
features (word unigrams and bigrams, sublinear term frequency) of the same
concatenation: multinomial logistic regression and a linear SVM, both with
$C{=}1$ and no tuning. The vocabulary is fitted within each training fold,
and both use the same five folds as DistilBERT, so all three trained
classifiers are compared on identical out-of-fold predictions.
```

**§V-C, new paragraph after the Table I paragraph:**

```latex
The linear baselines close most of the gap between the rules and
DistilBERT. TF-IDF with a linear SVM attains 84.57\% (95\% CI 80.5--87.9)
and macro-F1 0.842 (0.803--0.877); logistic regression attains 79.06\% and
0.792. DistilBERT's lead over the SVM, 7.99 points, is outside both
intervals, so fine-tuning buys a real in-corpus improvement, but most of
the distance from the rule set (44.9 of 52.9 points) is recovered by a
bag-of-words model that trains in under a second per fold and classifies an email in
under a millisecond.
```

**§V-E, after the DistilBERT held-out result:**

```latex
The linear SVM, refitted on all 363 primary emails, attains [[k]]/105
([[acc]]\%, 95\% CI [[lo--hi]]) and macro-F1 [[f1]] on the held-out
corpus, a decline of [[d]] points from its cross-validated figure against
7.80 for DistilBERT. [[If the intervals overlap:]] On the held-out corpus
the two are not separable, which suggests that part of DistilBERT's
in-corpus advantage reflects the primary generator's style rather than the
categories themselves.
```

---

## 3. End-to-end latency

**What was wrong:** `classify_node` was never timed, so every latency in
v15 is handler-only. In `eval_run.py`, DistilBERT's routing comes from an
out-of-fold dictionary lookup, so its inference cost appeared nowhere.

**What changed:**

- `app/graph.py` times classification into `classify_latency_ms`, which is
  logged next to the handler's `latency_ms`.
- `eval_run.py` still routes from out-of-fold predictions, so accuracy and
  cost are unchanged. For classification time it runs the *deployed* model
  on the same email and discards that prediction; inference cost doesn't
  depend on the weights.
- `eval_run.py` reports a new "end-to-end" column, Σ(classify + handler)
  against the always-LLM baseline, under all three existing views: all
  emails, non-spam, and calendar excluded.
- Model load time is reported once, separately.
- `latency_bench.py` gives per-email inference latency without the API.

**Measured here** (a 4-vCPU cloud Xeon at 2.3 GHz, not your laptop; rerun
for the paper):

| Classifier | Load | Median / email | p95 |
|---|---|---|---|
| Rules v1 | <1 ms | 0.11 ms | 0.30 ms |
| TF-IDF + LR | — | 0.41 ms | 0.52 ms |
| TF-IDF + SVM | — | 0.39 ms | 0.47 ms |
| DistilBERT | [[ms]] | [[ms]] | [[ms]] |

For scale: the always-LLM baseline averages about 1 s of API time per
email. DistilBERT on CPU at 128 tokens is typically tens of milliseconds,
so the end-to-end reduction should be a few points below 36.51%, not
qualitatively different. Report the measured numbers whatever they are.

**§V-D, replace the last two sentences** ("The calendar handler is
stubbed…") with:

```latex
Latency in Table~I is end-to-end within the pipeline: classifier inference
plus handler time, excluding Gmail fetch and draft I/O, which is identical
across systems. DistilBERT inference adds a median [[m]]~ms per email on
[[CPU]] ([[p95]]~ms at the 95th percentile; model load, [[load]]~ms, is
paid once at start-up), against [[t]]~ms for the TF-IDF baselines and
[[r]]~ms for the rules; including it lowers DistilBERT's latency reduction
from 36.51\% (handler only) to [[e2e]]\%. Calendar latency is a lower
bound: during evaluation the calendar handler is replaced by a fixed
0.1~ms stub, so neither date extraction nor the Calendar API round trip is
measured, and the live handler's date extraction is itself a naive fuzzy
parse of the message body rather than a validated parser. Excluding the
[[n]] calendar-routed emails, the end-to-end reduction is [[x]]\%.
```

If Table I's latency column changes to end-to-end, update the abstract,
§VI-A ("latency by 36.51%") and the caption ("Latency includes
calendar-routed emails…") to match.

---

## 4. Savings are LLM-side compute only

**§VI-A, new closing paragraph:**

```latex
These reductions are LLM-side compute savings only: tokens, API cost and
pipeline latency. They are not end-to-end savings for the user. Every
handler's output is staged for human review, so the operational cost of
an email also includes the time a person spends reading, correcting or
discarding its draft, and that cost is not measured here. It need not
move in the same direction as token cost: a templated reply to a misrouted
email costs nothing to generate but may cost more to repair than an LLM
draft, which is the mechanism behind the gap between measured and
attributable savings in Section~VI-B. The figures also exclude the
classifier's own compute and the embedding model behind retrieval, both of
which run locally. A full accounting would add review time per draft,
which the user study described in Section~VI-C is designed to measure.
```

---

## Future work (§VI-C): make the scope explicit

Replace the last three sentences of §VI-C ("Response quality is
unmeasured…") with:

```latex
Three questions are out of scope and left explicitly to future work.
\emph{Response quality, user acceptance and review burden:} we measure
whether an email reaches the intended handler, not whether the draft it
produces is acceptable; a planned user study will measure draft acceptance
rate and editing effort per handler, which also supplies the human-review
term missing from the cost accounting above. \emph{Real email:} both
corpora are synthetic; the held-out corpus, generated by a different model
from reworded prompts and independently double-annotated
($\kappa{=}0.900$), tests robustness to the generation process, not to
real inbox traffic, and evaluation on consented real email is the next
step. \emph{Untuned components:} the retrieval threshold, cache design and
rate limiting are fixed a priori or not yet implemented.
```

To make the held-out set and IAA more visible:

- Add "held-out" and the κ to the contributions list in §I. Contribution
  (2) already names the held-out corpus but not that it is double-annotated.
- Move the κ sentence in §V-B up so it opens the second paragraph.
- Add n = 105 and "different generator" to the Table II caption.

---

## Required fix: the paper describes a calendar approval flow the code doesn't have

| Paper says | Code (`main`) does |
|---|---|
| Abstract: "Neither side-effecting path acts without human approval" | — |
| §III-B: the calendar handler "performs no write: it stages a pending record" | `app/handlers/calendar.py` calls `service.events().insert(...)` immediately |
| §III-C: a confirmation token and an idempotent endpoint | `app/main.py` has only `/route-email` and `/health` |
| §IV-A: "the Calendar API is called only from the confirmation endpoint" | Not true of the committed code |

No reported number depends on this, because the handler is stubbed in
evaluation. But anyone who opens the released repo will find the
threat-model argument unimplemented. Either implement staging plus
`/confirm/{token}` before release, or revise those four passages to
describe the current behaviour. Email replies are correctly staged as
Gmail drafts (`app/poller.py`).
