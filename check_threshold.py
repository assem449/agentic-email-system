#!/usr/bin/env python3
"""
Verify that switching ChromaDB to cosine distance does not change which
FAQ emails hit versus miss.

Makes NO API calls -- it queries the vector store directly and compares
the threshold verdict against handler_used in the existing log.

Run from project root, AFTER backing up the old log:
    cp logs/eval_3baseline.json logs/eval_3baseline_OLD_squaredL2.json
    ./venv/bin/python3 check_threshold.py
"""
import json
import sys

from app.handlers.retrieval import _collection, CONFIDENCE_THRESHOLD

OLD_LOG = "logs/eval_3baseline_OLD_squaredL2.json"
EVAL_SET = "data/eval_set.json"

# ---------------------------------------------------------------- setup

print("Collection metadata:", _collection.metadata)
if (_collection.metadata or {}).get("hnsw:space") != "cosine":
    print("\n!! Collection is NOT using cosine.")
    print("   ChromaDB ignores the metadata= argument if a collection with")
    print("   this name already exists in the process. If you see this in a")
    print("   fresh process, the edit to retrieval.py did not take effect.")
    sys.exit(1)

print(f"FAQ entries in collection: {_collection.count()}")
print(f"CONFIDENCE_THRESHOLD: {CONFIDENCE_THRESHOLD} (cosine distance)\n")

with open(EVAL_SET) as f:
    emails = {e["id"]: e for e in json.load(f)}

with open(OLD_LOG) as f:
    old = json.load(f)

# Collect every email the old run sent through the retrieval handler,
# from either classifier pass. Old labels were retrieval_hit /
# retrieval_miss.
old_verdict = {}
for run in ("rules", "distilbert"):
    for r in old.get(run, []):
        h = r.get("handler_used")
        if h in ("retrieval_hit", "retrieval_miss"):
            old_verdict.setdefault(r["id"], h == "retrieval_hit")

if not old_verdict:
    print("No retrieval rows found in the old log. Check OLD_LOG path.")
    sys.exit(1)

print(f"Re-scoring {len(old_verdict)} emails that previously hit retrieval...\n")

# ------------------------------------------------------------ re-score

rows = []
for eid, was_hit in sorted(old_verdict.items()):
    email = emails.get(eid)
    if email is None:
        print(f"  (skipping {eid} — not in current eval set)")
        continue
    res = _collection.query(query_texts=[email["body"]], n_results=1)
    dist = res["distances"][0][0]
    rows.append({"id": eid, "distance": dist,
                 "old_hit": was_hit, "new_hit": dist <= CONFIDENCE_THRESHOLD})

agree = [r for r in rows if r["old_hit"] == r["new_hit"]]
disagree = [r for r in rows if r["old_hit"] != r["new_hit"]]

print(f"Agree:    {len(agree)}/{len(rows)}")
print(f"Disagree: {len(disagree)}/{len(rows)}")

if disagree:
    print("\nMismatches (old -> new):")
    for r in sorted(disagree, key=lambda x: x["distance"]):
        old_s = "hit " if r["old_hit"] else "miss"
        new_s = "hit " if r["new_hit"] else "miss"
        print(f"  {r['id']:<16} d={r['distance']:.4f}  {old_s} -> {new_s}")

# -------------------------------------------------- threshold guidance

old_hits = [r["distance"] for r in rows if r["old_hit"]]
old_misses = [r["distance"] for r in rows if not r["old_hit"]]

print("\nCosine-distance distribution under the OLD hit/miss labels:")
if old_hits:
    print(f"  hits   n={len(old_hits):<4} min={min(old_hits):.4f}  "
          f"max={max(old_hits):.4f}")
if old_misses:
    print(f"  misses n={len(old_misses):<4} min={min(old_misses):.4f}  "
          f"max={max(old_misses):.4f}")

if old_hits and old_misses:
    hi, lo = max(old_hits), min(old_misses)
    if hi < lo:
        print(f"\n  Classes are separable. Any threshold in "
              f"({hi:.4f}, {lo:.4f}) reproduces the old split exactly.")
        print(f"  Midpoint: {(hi + lo) / 2:.4f}")
        if not (hi < CONFIDENCE_THRESHOLD < lo):
            print(f"  -> Your current {CONFIDENCE_THRESHOLD} is OUTSIDE that "
                  f"range. Set it to the midpoint to make the switch a no-op.")
    else:
        print(f"\n  Classes OVERLAP (max hit {hi:.4f} >= min miss {lo:.4f}).")
        print("  No single threshold reproduces the old split. That means")
        print("  the metrics are not monotonically related on this data --")
        print("  worth investigating before you re-run.")

# ------------------------------------------------------- what changes

n_miss_now = sum(1 for r in rows if not r["new_hit"])
print(f"\nUnder the fixed handler, {n_miss_now} of these {len(rows)} emails")
print("will now fall through to the LLM instead of returning a placeholder.")
print("Those calls are the token and latency cost the old run was hiding.")

if not disagree:
    print("\nVERDICT: metric switch is a no-op. Safe to run eval_run.py.")
else:
    print("\nVERDICT: metric switch CHANGES routing. Adjust the threshold")
    print("using the guidance above before running eval_run.py.")