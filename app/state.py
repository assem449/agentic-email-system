from typing import TypedDict, Optional

class EmailState(TypedDict):
    email_id: str
    sender: str
    subject: str
    body: str                    # cleaned: quoted history and signature removed
    category: Optional[str]      # set by classifier node
    handler_used: Optional[str]  # set by the handler node
    response: Optional[str]      # None when no reply should be drafted
    tokens_used: Optional[int]
    latency_ms: Optional[float]
    input_tokens: int
    output_tokens: int
    retrieval_distance: float
    # Which enrolled study participant this email belongs to (app.db row
    # id). None for the no-account /route-email form path, in which case
    # the calendar node has nothing to hold a proposal against and just
    # returns a dry-run description instead of persisting anything.
    participant_id: Optional[str]
    gmail_id: Optional[str]    # Live-pipeline fields. Eval runs leave them unset, which routes every
    # email exactly as before the bulk filter existed.
    quoted_text: Optional[str]   # earlier messages in the thread, for the LLM
    bulk_reason: Optional[str]   # set when headers/labels/body mark bulk mail
    classifier_category: Optional[str]  # classifier's label before bulk override
    reply_needed: Optional[bool]
    needs_review: Optional[bool]
    auth_verdict: Optional[str]  # Gmail's DMARC verdict: pass | fail | none
    suspicious: Optional[bool]   # held back by the header safety check
    role: Optional[str]          # inbox owner: student | instructor | None (not chosen yet)
    faq_entry_id: Optional[str]  # course_logistics: the FAQ entry the reply came from
