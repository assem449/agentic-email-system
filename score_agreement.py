"""
score_agreement.py

Computes raw agreement and Cohen's kappa between the original labels
and a second annotator's completed sheet, and writes out an
adjudication sheet listing every case where they disagree.

Usage:
    python score_agreement.py answer_key.csv completed_sheet.xlsx

Requires:
    pip install openpyxl scikit-learn

Inputs:
    answer_key.csv        columns: blind_id, orig_id, original_label
                           (built earlier by build_blind_sheet.py --
                            keep this file private, never sent to the
                            annotator)
    completed_sheet.xlsx   the annotator's filled-in sheet, columns:
                            id, subject, body, your_label
                           (a .csv with the same columns also works)

Outputs:
    adjudication_sheet.csv   every disagreement, with both labels
                              shown side by side and a blank
                              final_label column to fill in together
"""

import sys
import csv
from pathlib import Path

try:
    from sklearn.metrics import cohen_kappa_score
except ImportError:
    print("Missing dependency: pip install scikit-learn")
    sys.exit(1)


def load_completed_sheet(path: Path):
    """Load the annotator's completed sheet from .xlsx or .csv."""
    annot, content = {}, {}
    if path.suffix.lower() == ".xlsx":
        try:
            import openpyxl
        except ImportError:
            print("Missing dependency: pip install openpyxl")
            sys.exit(1)
        wb = openpyxl.load_workbook(path)
        ws = wb.active
        rows = ws.iter_rows(min_row=2, values_only=True)
        for eid, subj, body, lab in rows:
            if eid is None:
                continue
            annot[eid] = str(lab).strip().lower() if lab else ""
            content[eid] = (subj, body)
    else:
        with open(path, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                eid = row["id"]
                annot[eid] = row["your_label"].strip().lower()
                content[eid] = (row["subject"], row["body"])
    return annot, content


def load_answer_key(path: Path):
    orig, orig_id_map = {}, {}
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            orig[row["blind_id"]] = row["original_label"].strip().lower()
            orig_id_map[row["blind_id"]] = row["orig_id"]
    return orig, orig_id_map


def main():
    if len(sys.argv) != 3:
        print("Usage: python score_agreement.py answer_key.csv completed_sheet.xlsx")
        sys.exit(1)

    answer_key_path = Path(sys.argv[1])
    completed_path = Path(sys.argv[2])

    orig, orig_id_map = load_answer_key(answer_key_path)
    annot, content = load_completed_sheet(completed_path)

    missing_in_annot = set(orig) - set(annot)
    missing_in_orig = set(annot) - set(orig)
    if missing_in_annot or missing_in_orig:
        print("WARNING: id mismatch between the two sheets.")
        if missing_in_annot:
            print(f"  In answer key but not in completed sheet: {sorted(missing_in_annot)}")
        if missing_in_orig:
            print(f"  In completed sheet but not in answer key: {sorted(missing_in_orig)}")

    common_ids = sorted(set(orig) & set(annot))
    y_orig = [orig[k] for k in common_ids]
    y_annot = [annot[k] for k in common_ids]

    kappa = cohen_kappa_score(y_orig, y_annot)
    agree = sum(1 for a, b in zip(y_orig, y_annot) if a == b)
    n = len(common_ids)

    print(f"N = {n}")
    print(f"Raw agreement: {agree}/{n} = {agree/n:.4f}")
    print(f"Cohen's kappa: {kappa:.4f}")

    disagreements = [k for k in common_ids if orig[k] != annot[k]]
    print(f"Disagreements: {len(disagreements)}")

    out_path = Path("adjudication_sheet.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["blind_id", "orig_id", "subject", "body",
                     "original_label", "second_annotator_label", "final_label"])
        for k in disagreements:
            subj, body = content[k]
            w.writerow([k, orig_id_map.get(k, ""), subj, body,
                         orig[k], annot[k], ""])

    print(f"\nWrote {out_path.name} for adjudication.")


if __name__ == "__main__":
    main()