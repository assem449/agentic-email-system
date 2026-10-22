"""course_logistics: cache -> FAQ lookup -> LLM draft -> review if not covered.

Only for an instructor's inbox: the FAQ answers questions students ask about
the instructor's course. In a student's inbox, or before the participant has
chosen a role, the email gets AI/Needs review and no draft.

The FAQ is a demo for one course (data/academic/faq_discrete_math.json),
standing in for an outline the instructor would upload.

Cache: the reply written from one FAQ entry is stored without greeting or
sign-off and reused, with a fresh greeting, for the next email that matches
the same entry. The key includes a hash of the FAQ file, so any edit to the
FAQ (a changed policy) stops old replies from being reused. Stored in
study.db, per participant, so it survives restarts and one participant's
emails never make another's cheaper.
"""

import hashlib
import json
import re
import time
from email.utils import parseaddr
from pathlib import Path

from app import db
from app.config import LLM_MODEL
from app.handlers.llm import _client
from app.state import EmailState

FAQ_PATH = Path(__file__).parent.parent.parent / "data" / "academic" / "faq_discrete_math.json"

# Cosine distance, range [0, 2]; a match at or below this counts as covered.
# Not tuned: the same starting value as the v1 FAQ handler.
MATCH_THRESHOLD = 0.5

# A course code like "CHEM 1000". Upper case only, so "Room 3021" is not one.
_COURSE_CODE = re.compile(r"\b([A-Z]{2,4}) ?(\d{4})\b")

_TITLES = {"prof", "prof.", "professor", "dr", "dr.", "ta", "mr", "mr.", "ms", "ms.", "mrs", "mrs."}

SYSTEM_PROMPT = """\
You write the body of an email reply from the instructor of {course_name} \
({course}) to a student's question about course logistics. You are given \
one entry from the course FAQ. The same text will be reused for every \
student who asks this question, so:
- Answer the FAQ question using only the FAQ answer. Do not add dates, \
numbers, rules or promises that are not in it.
- Do not mention any particular student, assignment or situation beyond \
what the FAQ answer says.
- No greeting, no sign-off and no names: they are added separately.
- Two to four plain sentences, friendly and clear.\
"""

_faq = None
_collection = None


def _load_faq() -> dict:
    """The FAQ file, plus its version: a hash of the exact file contents."""
    global _faq
    if _faq is None:
        raw = FAQ_PATH.read_bytes()
        _faq = {**json.loads(raw), "version": hashlib.sha256(raw).hexdigest()[:16]}
    return _faq


def _match(text: str) -> tuple[dict, float]:
    """The FAQ entry closest in meaning, and its distance.

    Each entry is indexed as question + answer. Questions alone are too
    alike to tell apart ("When and where is the midterm?" vs "What does
    the midterm cover?" both matched "Which chapters are on the midterm?"
    to the date); the answer text carries the distinguishing words.
    """
    global _collection
    faq = _load_faq()
    if _collection is None:
        import chromadb  # only loaded once a course_logistics email arrives
        _collection = chromadb.Client().get_or_create_collection(
            f"course-faq-{faq['version']}", metadata={"hnsw:space": "cosine"}
        )
        if _collection.count() == 0:
            _collection.add(
                ids=[e["id"] for e in faq["entries"]],
                documents=[f"{e['question']} {e['answer']}" for e in faq["entries"]],
            )
    result = _collection.query(query_texts=[text], n_results=1)
    entry_id = result["ids"][0][0]
    entry = next(e for e in faq["entries"] if e["id"] == entry_id)
    return entry, result["distances"][0][0]


def _names_other_course(text: str, faq: dict) -> bool:
    """True if the email names a course code and none of them is this course."""
    ours = {a.replace(" ", "").upper() for a in faq["aliases"]}
    codes = {"".join(m) for m in _COURSE_CODE.findall(text)}
    return bool(codes) and not (codes & ours)


def _greeting(sender: str) -> str:
    name, _ = parseaddr(sender or "")
    words = [w for w in name.split() if w.lower() not in _TITLES]
    return f"Hi {words[0]}," if words else "Hi,"


def _write_reply(entry: dict, faq: dict) -> tuple[str, int, int]:
    message = _client.messages.create(
        model=LLM_MODEL,
        max_tokens=300,
        system=SYSTEM_PROMPT.format(course=faq["course"], course_name=faq["course_name"]),
        messages=[{"role": "user", "content":
                   f"FAQ question: {entry['question']}\nFAQ answer: {entry['answer']}"}],
    )
    text = next((b.text for b in message.content if b.type == "text"), "").strip()
    return text, message.usage.input_tokens, message.usage.output_tokens


def _review(state: EmailState, handler: str, start: float) -> EmailState:
    """No draft; the poller labels the email AI/Needs review."""
    state["handler_used"] = handler
    state["response"] = None
    state["needs_review"] = True
    state["tokens_used"] = state["input_tokens"] = state["output_tokens"] = 0
    state["latency_ms"] = (time.perf_counter() - start) * 1000
    return state


def course_logistics_handler(state: EmailState) -> EmailState:
    start = time.perf_counter()

    if state.get("role") != "instructor":
        return _review(state, "logistics_review_role", start)

    faq = _load_faq()
    text = f"{state['subject']}\n{state['body']}"
    if _names_other_course(text, faq):
        return _review(state, "logistics_other_course", start)

    entry, distance = _match(text)
    state["retrieval_distance"] = distance
    if distance > MATCH_THRESHOLD:
        return _review(state, "logistics_not_covered", start)

    key = (state.get("participant_id") or "", faq["course"], faq["term"],
           faq["version"], entry["id"])
    reply = db.get_faq_reply(*key) if state.get("participant_id") else None
    if reply is not None:
        state["handler_used"] = "faq_cache_hit"
        state["tokens_used"] = state["input_tokens"] = state["output_tokens"] = 0
    else:
        reply, input_tokens, output_tokens = _write_reply(entry, faq)
        if state.get("participant_id"):
            db.put_faq_reply(*key, reply)
        state["handler_used"] = "faq_llm"
        state["input_tokens"] = input_tokens
        state["output_tokens"] = output_tokens
        state["tokens_used"] = input_tokens + output_tokens

    state["faq_entry_id"] = entry["id"]
    state["response"] = f"{_greeting(state.get('sender', ''))}\n\n{reply}\n\nBest regards,\n[Your name]"
    state["latency_ms"] = (time.perf_counter() - start) * 1000
    return state
