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