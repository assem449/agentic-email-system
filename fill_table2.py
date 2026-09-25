#!/usr/bin/env python3
"""Fill in Table II: per-category P/R/F1 for both classifiers on both corpora.

Uses logs/eval_3baseline.json (primary, 363 emails) and
logs/heldout_results.json (held-out, 105 emails) -- both already produced by
earlier runs. No new evaluation, no API calls. Pure arithmetic over predictions
that already exist.

    ./venv/bin/python3 fill_table2.py
"""
import json
from collections import defaultdict

CATEGORIES = ["ack", "meeting", "faq", "support", "emotional", "ambiguous", "spam"]


def per_category(rows, categories=CATEGORIES):
    tp, fp, fn = defaultdict(int), defaultdict(int), defaultdict(int)
    for r in rows:
        t, p = r["true_category"], r["predicted_category"]
        if t == p:
            tp[t] += 1
        else:
            fp[p] += 1
            fn[t] += 1
    out = {}
    for c in categories:
        pd, rd = tp[c] + fp[c], tp[c] + fn[c]
        P = tp[c] / pd if pd else 0.0
        R = tp[c] / rd if rd else 0.0
        F = 2 * P * R / (P + R) if P + R else 0.0
        out[c] = {"n": rd, "P": P, "R": R, "F1": F}
    return out


def macro(pc, categories=CATEGORIES):
    n = len(categories)
    return {"P": sum(v["P"] for v in pc.values()) / n,
           "R": sum(v["R"] for v in pc.values()) / n,
           "F1": sum(v["F1"] for v in pc.values()) / n}


def load(path, key):
    with open(path) as f:
        return json.load(f)[key]


def main():
    primary_rules = load("logs/eval_3baseline.json", "rules")
    primary_distil = load("logs/eval_3baseline.json", "distilbert")
    heldout_rules = load("logs/heldout_results.json", "rules")
    heldout_distil = load("logs/heldout_results.json", "distilbert")

    pc_pr = per_category(primary_rules)
    pc_pd = per_category(primary_distil)
    pc_hr = per_category(heldout_rules)
    pc_hd = per_category(heldout_distil)

    print(f"{'Category':<12}{'n':>4} | {'F1 v1':>6}{'P v2':>7}{'R v2':>7}{'F1 v2':>7}"
         f"  ||  {'n':>4}{'F1 v1':>7}{'P v2':>7}{'R v2':>7}{'F1 v2':>7}")
    print("-" * 100)
    for c in CATEGORIES:
        p, d, h_r, h_d = pc_pr[c], pc_pd[c], pc_hr[c], pc_hd[c]
        print(f"{c:<12}{p['n']:>4} | {p['F1']:>6.3f}{d['P']:>7.3f}{d['R']:>7.3f}{d['F1']:>7.3f}"
             f"  ||  {h_r['n']:>4}{h_r['F1']:>7.3f}{h_d['P']:>7.3f}{h_d['R']:>7.3f}{h_d['F1']:>7.3f}")

    m_pr, m_pd = macro(pc_pr), macro(pc_pd)
    m_hr, m_hd = macro(pc_hr), macro(pc_hd)
    n_p = sum(v["n"] for v in pc_pr.values())
    n_h = sum(v["n"] for v in pc_hr.values())
    print("-" * 100)
    print(f"{'macro avg':<12}{n_p:>4} | {m_pr['F1']:>6.3f}{m_pd['P']:>7.3f}{m_pd['R']:>7.3f}{m_pd['F1']:>7.3f}"
         f"  ||  {n_h:>4}{m_hr['F1']:>7.3f}{m_hd['P']:>7.3f}{m_hd['R']:>7.3f}{m_hd['F1']:>7.3f}")

    print("\nRule-set macro P/R (for the prose sentence citing them):")
    print(f"  primary : P={m_pr['P']:.3f} R={m_pr['R']:.3f}")
    print(f"  held-out: P={m_hr['P']:.3f} R={m_hr['R']:.3f}")

    # sanity check against numbers already committed to the paper
    checks = [("primary DistilBERT macro-F1", m_pd["F1"], 0.923),
             ("primary rules macro-F1", m_pr["F1"], 0.386),
             ("held-out rules macro-F1", m_hr["F1"], 0.422),
             ("held-out DistilBERT macro-F1", m_hd["F1"], 0.868),
             ("held-out support F1 (v2)", pc_hd["support"]["F1"], 0.769),
             ("held-out FAQ F1 (v2)", pc_hd["faq"]["F1"], 0.788),
             ("held-out support P (v2)", pc_hd["support"]["P"], 0.909),
             ("held-out support R (v2)", pc_hd["support"]["R"], 0.667)]
    print("\nsanity check against figures already stated in the paper:")
    bad = 0
    for label, got, want in checks:
        ok = abs(got - want) < 0.002
        bad += not ok
        print(f"  {'OK ' if ok else '** MISMATCH'}  {label:<32} computed={got:.3f}  paper={want:.3f}")
    if bad:
        print(f"\n{bad} mismatch(es) -- do not paste this table into the paper "
             f"until resolved. Likely cause: different category list, category-name "
             f"mismatch, or a different model/log file than what the paper's prose "
             f"figures came from.")
    else:
        print("\nAll paper figures reproduced exactly. Table is consistent with the "
             "prose you already committed to.")


if __name__ == "__main__":
    main()