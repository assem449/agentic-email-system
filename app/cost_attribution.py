"""Attributable cost reduction.

A routed system's headline cost reduction counts every token it avoided
spending, regardless of whether the handler that avoided them could answer
the email. A misroute into a zero-token handler -- a support request sent to
the acknowledgment template, an FAQ question sent to the calendar -- registers
in that metric exactly like a correct route.

This module separates the two. For each email we compute what the always-LLM
baseline paid and what the routed system paid; the difference is the saving
for that email. Savings are then summed separately over correctly and
incorrectly routed emails.

    measured      = sum of all savings          / total baseline cost
    attributable  = savings on correct routes   / total baseline cost

On the 363-email corpus rules v1 shows a measured reduction of 29.02% but an
attributable reduction of 13.03%: more than half its apparent savings come
from emails it got wrong. DistilBERT v2 shows 38.72% measured against 36.10%
attributable.

Caveat worth stating wherever these numbers are reported: this credits a
misroute with its full saving, which slightly overstates the misrouted share.
An ambiguous email answered by a template is not necessarily unanswerable,
only unanswered as intended.
"""

# Claude Sonnet 4.6, USD per million tokens.
PRICE_IN = 3.00
PRICE_OUT = 15.00


def email_cost(row):
    """Monetary cost of one email, from its recorded input/output token split."""
    return (row.get("input_tokens", 0) / 1e6 * PRICE_IN
            + row.get("output_tokens", 0) / 1e6 * PRICE_OUT)


def decompose(routed_rows, baseline_rows):
    """Split a routed system's savings by whether each route was correct.

    routed_rows   : per-email dicts with 'id', 'correct', and token counts
    baseline_rows : the always-LLM pass over the SAME emails

    Returns measured and attributable reduction as fractions of baseline cost.
    """
    baseline = {r["id"]: email_cost(r) for r in baseline_rows}
    total_baseline = sum(baseline.values())
    if not total_baseline:
        raise ValueError("baseline cost is zero -- are token counts recorded?")

    missing = [r["id"] for r in routed_rows if r["id"] not in baseline]
    if missing:
        raise ValueError(f"{len(missing)} routed emails absent from the "
                         f"baseline; the two passes must cover the same set "
                         f"(first few: {missing[:5]})")

    saved_correct = saved_misrouted = 0.0
    n_correct = n_misrouted = 0
    for r in routed_rows:
        saving = baseline[r["id"]] - email_cost(r)
        if r["correct"]:
            saved_correct += saving
            n_correct += 1
        else:
            saved_misrouted += saving
            n_misrouted += 1

    total_saved = saved_correct + saved_misrouted
    return {
        "baseline_cost": total_baseline,
        "routed_cost": total_baseline - total_saved,
        "saved_total": total_saved,
        "saved_correct": saved_correct,
        "saved_misrouted": saved_misrouted,
        "measured_reduction": total_saved / total_baseline,
        "attributable_reduction": saved_correct / total_baseline,
        "misrouted_share_of_savings": (saved_misrouted / total_saved
                                       if total_saved else 0.0),
        "n_correct": n_correct,
        "n_misrouted": n_misrouted,
    }


def zero_token_breakdown(routed_rows,
                         zero_handlers=("template", "calendar", "blocked",
                                        "cache_hit", "retrieval_hit")):
    """Which zero-token handlers absorbed emails, and how many were misroutes.

    This is the mechanism behind the gap between measured and attributable
    reduction: the cost metric records which handler ran, not whether it
    could answer.
    """
    out = {}
    for h in zero_handlers:
        rows = [r for r in routed_rows if r.get("handler_used") == h]
        if rows:
            correct = sum(r["correct"] for r in rows)
            out[h] = {"total": len(rows), "correct": correct,
                      "misrouted": len(rows) - correct}
    totals = {"total": sum(v["total"] for v in out.values()),
              "correct": sum(v["correct"] for v in out.values()),
              "misrouted": sum(v["misrouted"] for v in out.values())}
    return out, totals


def report(routed_rows, baseline_rows, name):
    d = decompose(routed_rows, baseline_rows)
    by_handler, totals = zero_token_breakdown(routed_rows)

    print(f"\n=== {name} ===")
    print(f"  baseline cost                    ${d['baseline_cost']:.4f}")
    print(f"  routed cost                      ${d['routed_cost']:.4f}")
    print(f"  measured cost reduction          {d['measured_reduction']:>7.2%}")
    print(f"  attributable to correct routing  {d['attributable_reduction']:>7.2%}")
    print(f"  savings arising from misroutes   {d['misrouted_share_of_savings']:>7.1%}"
          f"  (${d['saved_misrouted']:.4f} of ${d['saved_total']:.4f})")

    if totals["total"]:
        print(f"\n  zero-token routings: {totals['total']} "
              f"({totals['misrouted']} misrouted, "
              f"{totals['misrouted'] / totals['total']:.0%})")
        print(f"  {'handler':<16}{'total':>7}{'correct':>9}{'misrouted':>11}")
        for h, v in sorted(by_handler.items(), key=lambda kv: -kv[1]["total"]):
            print(f"  {h:<16}{v['total']:>7}{v['correct']:>9}{v['misrouted']:>11}")
    return d


if __name__ == "__main__":
    import json
    with open("logs/eval_3baseline.json") as f:
        data = json.load(f)
    baseline = data["llm_baseline"]
    for label, key in (("Rules v1 (frozen)", "rules"),
                       ("DistilBERT v2 (out-of-fold)", "distilbert")):
        report(data[key], baseline, label)