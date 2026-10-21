"""One-time: upload the trained DistilBERT model to the Hugging Face Hub,
so a deploy can download it instead of needing it committed to git (the
model is 255MB+, which is what caused the original 'file exceeds
GitHub's 100MB limit' push failure early in this project).

Run this on your own machine, where data/distilbert_model/final (the
actual trained weights) exists -- not on the server.

Setup (once):
    pip install huggingface_hub
    huggingface-cli login
        # paste a token from https://huggingface.co/settings/tokens
        # needs "Write" access

Usage:
    python scripts/upload_model_to_hf.py <your-hf-username>/<repo-name>
    python scripts/upload_model_to_hf.py --model-dir data/academic_v2 <your-hf-username>/<repo-name>

--model-dir is the --out folder given to research/distilbert_cv.py
(default: data). Its label_map.json is uploaded next to the weights, so
the deploy reads category names that match the model it downloaded.

Creates the repo if it doesn't exist (public by default -- the model is
just classifier weights trained on your own labeled eval set, nothing
participant- or email-content-specific, so there's nothing confidential
in it; pass --private if you'd rather keep it private, which then also
requires setting HF_TOKEN in the deploy environment so it can download).
"""

import shutil
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi, create_repo


def main():
    args = sys.argv[1:]
    private = "--private" in args
    args = [a for a in args if a != "--private"]
    model_dir = Path("data")
    if "--model-dir" in args:
        i = args.index("--model-dir")
        model_dir = Path(args[i + 1])
        del args[i:i + 2]

    if len(args) != 1:
        print(f"Usage: {sys.argv[0]} [--private] [--model-dir DIR] <hf-username>/<repo-name>")
        sys.exit(1)

    repo_id = args[0]
    weights = model_dir / "distilbert_model" / "final"
    label_map = model_dir / "label_map.json"
    for needed in (weights, label_map):
        if not needed.exists():
            print(f"Missing {needed} -- train with --out {model_dir} first.")
            sys.exit(1)

    with tempfile.TemporaryDirectory() as staging:
        shutil.copytree(weights, staging, dirs_exist_ok=True)
        shutil.copy(label_map, Path(staging) / "label_map.json")
        create_repo(repo_id, private=private, exist_ok=True)
        HfApi().upload_folder(folder_path=staging, repo_id=repo_id, repo_type="model")

    print(f"\nUploaded to https://huggingface.co/{repo_id}")
    print(f"Set DISTILBERT_MODEL_REPO={repo_id} in your deploy environment.")
    if private:
        print("Repo is private — also set HF_TOKEN (a read-access token) in the deploy environment.")


if __name__ == "__main__":
    main()
