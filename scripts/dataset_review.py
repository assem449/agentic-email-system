"""Check the academic dataset's labels in a spreadsheet, then merge them back.

    python scripts/dataset_review.py export   # dataset.json -> review.csv
    python scripts/dataset_review.py merge    # review.csv -> dataset.json

In review.csv (opens in Excel / Google Sheets / Numbers):
  - corrected_category: leave empty if the label is right; otherwise type
    the correct category name, or `delete` to drop the email.
  - To add one of your real emails, add a row with a new unique id
    (e.g. real-01), source = real, and its true_category. Remove names and
    personal details first.
  - notes: free text, kept in dataset.json for your own reference.

merge refuses to write anything if a category name is misspelled or an id
is duplicated, so a typo can't silently corrupt the dataset.
"""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data" / "academic" / "dataset.json"
REVIEW = ROOT / "data" / "academic" / "review.csv"

CATEGORIES = {
    "announcement_promo", "informational", "admin_action", "course_logistics",
    "academic_question", "meeting_request", "request_exception",
    "collaboration_opportunity", "wellbeing", "ambiguous", "spam",
}
ROLES = {"student", "instructor"}
COLUMNS = ["id", "role", "true_category", "corrected_category", "trap",
           "source", "sender", "subject", "body", "notes"]


def export():
    rows = json.loads(DATASET.read_text())
    with open(REVIEW, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({**{k: r.get(k, "") for k in COLUMNS}, "corrected_category": ""})
    print(f"Wrote {len(rows)} rows to {REVIEW.relative_to(ROOT)}")


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes", "y")


def merge():
    with open(REVIEW, newline="", encoding="utf-8") as f:
        sheet = list(csv.DictReader(f))

    errors, seen, out = [], set(), []
    changed = deleted = added = 0
    existing_ids = {r["id"] for r in json.loads(DATASET.read_text())}

    for line, row in enumerate(sheet, start=2):  # line 1 is the header
        rid = (row.get("id") or "").strip()
        if not rid:
            errors.append(f"line {line}: missing id")
            continue
        if rid in seen:
            errors.append(f"line {line}: duplicate id {rid}")
        seen.add(rid)

        corrected = (row.get("corrected_category") or "").strip()
        if corrected.lower() == "delete":
            deleted += 1
            continue
        label = corrected or (row.get("true_category") or "").strip()
        if label not in CATEGORIES:
            errors.append(f"line {line} ({rid}): unknown category '{label}'")
        role = (row.get("role") or "").strip()
        if role not in ROLES:
            errors.append(f"line {line} ({rid}): role must be student or instructor, got '{role}'")
        if not (row.get("body") or "").strip():
            errors.append(f"line {line} ({rid}): empty body")

        if corrected and corrected != row.get("true_category"):
            changed += 1
        if rid not in existing_ids:
            added += 1

        record = {
            "id": rid,
            "role": role,
            "sender": row.get("sender", ""),
            "subject": row.get("subject", ""),
            "body": row.get("body", ""),
            "true_category": label,
            "source": (row.get("source") or "generated").strip(),
            "trap": _truthy(row.get("trap", "")),
        }
        if (row.get("notes") or "").strip():
            record["notes"] = row["notes"].strip()
        out.append(record)

    if errors:
        print("Nothing written. Fix these in review.csv first:")
        for e in errors:
            print("  -", e)
        sys.exit(1)

    DATASET.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"Merged {len(out)} emails into {DATASET.relative_to(ROOT)}: "
          f"{changed} relabelled, {deleted} deleted, {added} added.")
    print("Run `python scripts/dataset_review.py export` again to refresh "
          "review.csv (it resets corrected_category).")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("export", "merge"):
        print(__doc__)
        sys.exit(1)
    {"export": export, "merge": merge}[sys.argv[1]]()
