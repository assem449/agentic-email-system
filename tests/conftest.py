"""Runs before any app module is imported: a throwaway study.db and a dummy
API key, so tests never touch real data or call the Anthropic API."""

import os
import tempfile

os.environ["STUDY_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_study.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
