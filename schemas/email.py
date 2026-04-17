from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import datetime


class EmailObject(BaseModel):
    """
    The core email object. This is the starting point of the entire pipeline.
    Every incoming email gets parsed into this structure before any agent touches it.
    """

    sender: str                          # who sent the email
    recipient: str                       # who received it
    subject: str                         # email subject line
    body: str                            # email body (PII will be scrubbed before this reaches any LLM)
    timestamp: datetime                  # when it was received
    thread_id: Optional[str] = None      # gmail thread id, useful for grouping replies
    client_id: Optional[str] = None      # which client this belongs to (used for Pinecone metadata filtering)
    is_new_contact: bool = False         # true if sender has never emailed before (triggers HIL review)

    @field_validator("body")
    @classmethod
    def body_must_not_be_empty(cls, v):
        if not v.strip():
            raise ValueError("Email body cannot be empty")
        return v

    @field_validator("sender", "recipient")
    @classmethod
    def must_contain_at_symbol(cls, v):
        if "@" not in v:
            raise ValueError(f"'{v}' does not look like a valid email address")
        return v
