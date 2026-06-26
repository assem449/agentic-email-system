import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
LLM_MODEL = "claude-sonnet-4-6"

GOOGLE_CALENDAR_ID = "primary"
GOOGLE_CREDENTIALS_PATH = "credentials.json"
GOOGLE_TOKEN_PATH = "token.json"