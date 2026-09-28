from typing import TypedDict, Optional

class EmailState(TypedDict):
    email_id: str
    sender: str
    subject: str
    body: str
    category: Optional[str]      # set by classifier node
    handler_used: Optional[str]  # set by the handler node
    response: Optional[str]
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
    gmail_id: Optional[str]