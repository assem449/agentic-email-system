import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
LLM_MODEL = "claude-sonnet-4-6"

GOOGLE_CALENDAR_ID = "primary"

# Legacy single-account desktop-app OAuth (test_gmail.py, ad-hoc local runs).
# The multi-participant study flow below does not use these.
GOOGLE_CREDENTIALS_PATH = "credentials.json"
GOOGLE_TOKEN_PATH = "token.json"

# --- Multi-participant study deployment ---
#
# One combined OAuth "Web application" client (not "Desktop app") registered
# in the same Google Cloud project, used for every participant's sandbox
# account. Download its client secret JSON from the Cloud console and point
# this at it.
GOOGLE_OAUTH_CLIENT_SECRETS_PATH = os.environ.get(
    "GOOGLE_OAUTH_CLIENT_SECRETS_PATH", "oauth_client_secret.json"
)
# Must exactly match a redirect URI registered on that OAuth client.
OAUTH_REDIRECT_URI = os.environ.get(
    "OAUTH_REDIRECT_URI", "http://localhost:8000/auth/callback"
)

# Symmetric key (Fernet, url-safe base64, 32 bytes) used to encrypt every
# participant's stored OAuth token at rest. Generate one with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Must be set (and kept stable — regenerating it strands every stored token)
# before running the real study. Falling back to a freshly-generated key
# only keeps the eval/classifier scripts importable without it; anything
# that actually stores a token will produce data no later process can read.
from cryptography.fernet import Fernet as _Fernet  # noqa: E402

_token_key = os.environ.get("TOKEN_ENCRYPTION_KEY")
if not _token_key:
    print(
        "WARNING: TOKEN_ENCRYPTION_KEY not set — using a throwaway key for "
        "this process only. Set it in the environment before running the "
        "study, or every participant will need to reconnect on restart."
    )
    _token_key = _Fernet.generate_key().decode()
TOKEN_ENCRYPTION_KEY = _token_key

# Shared secret for the human-in-the-loop review endpoints (/admin/*).
# Placeholder auth for a small study — swap for real auth before wider use.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "dev-admin-token")

DB_PATH = os.environ.get("STUDY_DB_PATH", "study.db")

POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))

# What "a day" means for the check-in page's "Day N" count and "today's
# emails" filter -- an IANA zone name, not raw UTC. Participants
# experience their day changing at their own local midnight, not at
# UTC's; using plain UTC meant a participant connecting in the evening
# (local time) could already be on the next UTC calendar date, so their
# next real day's check-in would still read "Day 1" until UTC itself
# rolled over, hours after their own day already had. Defaults to
# Toronto since that's where this study's participants are.
STUDY_TIMEZONE = os.environ.get("STUDY_TIMEZONE", "America/Toronto")
