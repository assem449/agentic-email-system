import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
LLM_MODEL = "claude-sonnet-4-6"

GOOGLE_CALENDAR_ID = "primary"
GOOGLE_CREDENTIALS_PATH = "credentials.json"
GOOGLE_TOKEN_PATH = "token.json"

# Pending meeting proposals (app/pending.py). SQLite so the poller and the
# API process share one store; gitignored via *.sqlite3.
PENDING_DB_PATH = os.environ.get("PENDING_DB_PATH", "pending_meetings.sqlite3")
CALENDAR_TIMEZONE = "America/Toronto"
MEETING_MINUTES = 30
