"""
Dedupe eval_set.json — removes exact duplicate email bodies (case/whitespace
insensitive), keeps the first occurrence of each, and reports what was
removed so you can cite the cleanup in your dataset disclosure section.

Usage:
    ./venv/bin/python3 dedupe_eval_set.py data/eval_set.json data/eval_set_deduped.json
"""

import json
import sys
import collections


def normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def dedupe(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    seen: dict[str, dict] = {}
    kept: list[dict] = []
    removed: list[dict] = []

    for entry in entries:
        key = normalize(entry["body"])
        if key in seen:
            removed.append(entry)
        else:
            seen[key] = entry
            kept.append(entry)

    return kept, removed


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.json> <output.json>")
        sys.exit(1)

    in_path, out_path = sys.argv[1], sys.argv[2]

    with open(in_path, "r", encoding="utf-8") as f:
        entries = json.load(f)

    kept, removed = dedupe(entries)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(kept, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Input:   {len(entries)} entries")
    print(f"Kept:    {len(kept)} entries")
    print(f"Removed: {len(removed)} duplicate entries\n")

    if removed:
        print("Removed entries (id, category, body):")
        for r in removed:
            print(f"  [{r['id']}] ({r['true_category']}) {r['body']!r}")

    print("\nCategory balance after dedup:")
    cats = collections.Counter(e["true_category"] for e in kept)
    for cat, n in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {n}")

    print(f"\nWrote deduped set to {out_path}")


if __name__ == "__main__":
    main()