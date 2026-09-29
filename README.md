# Agentic Email System

An email-routing agent: reads a Gmail inbox, classifies each message
(rules or a fine-tuned DistilBERT model), and handles it with the
cheapest adequate path — a template, a cached reply, a FAQ retrieval
hit, or a full LLM-drafted reply — instead of sending everything through
an LLM. Meeting requests are proposed, not auto-booked: a human reviewer
approves or rejects the calendar event before it's created.

## Layout

```
app/            The deployed service — classification, handlers, the
                FastAPI server, multi-participant OAuth, the poller.
research/       Offline evaluation and model-training tooling (not
                imported by the live app): eval_run.py (the 3-baseline
                accuracy/token/latency comparison), distilbert_cv.py
                (5-fold cross-validation training), oof_classifier.py
                (leakage-free eval helper), dedupe_eval_set.py.
scripts/        Manual, run-by-hand smoke tests — not an automated
                test suite.
data/           faq.json and label_map.json are live runtime
                dependencies of app/; eval_set.json is the research
                harness's labeled dataset.
docs/           NOTES.md (classifier iteration log / evaluation
                results) and STUDY_SETUP.md (deploying this for a
                real user study).
```

## Running the live app

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY, TOKEN_ENCRYPTION_KEY, ADMIN_TOKEN
uvicorn app.main:app --reload
```

See `docs/STUDY_SETUP.md` for the full multi-participant deployment —
Google Cloud OAuth setup, enrolling sandbox accounts, and reviewing
proposed calendar events at `/admin`.

For a single local account instead (the older, simpler path — no study
infrastructure), see `app/gmail_client.py` and `scripts/test_gmail.py`.

## Where does the data go?

No database of email content exists anywhere in this system. Emails are
read live from Gmail into memory, processed, and never written to disk.
The one thing the study deployment persists is a small SQLite file
holding each participant's OAuth token (encrypted at rest) and short
metadata on proposed-but-not-yet-approved calendar events. Full
data-flow writeup: `docs/NOTES.md`.

## Evaluation

```bash
python research/eval_run.py
```

Runs the classifier against `data/eval_set.json` and reports accuracy,
token reduction, and latency reduction versus an always-LLM baseline.
Headline numbers and the iteration history that produced them are in
`docs/NOTES.md`.
