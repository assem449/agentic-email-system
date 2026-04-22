from pydantic import BaseModel, field_validator
from typing import Optional
from .email import EmailObject
from .research import ResearchOutput


class DraftInput(BaseModel):
    """
    What the Drafting Agent receives.
    It gets the original email plus whatever the Research Agent found.
    If missing_information is True, it knows to write a follow-up response instead of guessing.
    """

    email: EmailObject
    research: Optional[ResearchOutput] = None   # None if requires_research was False


class DraftOutput(BaseModel):
    """
    What the Drafting Agent returns.

    Key safety check: placeholders_detected must be empty before this draft
    can move forward. If the agent left anything like [Insert Date] in the body,
    the system halts automatically.
    """

    subject_line: str                           # the reply subject line
    email_body: str                             # the full reply body
    tone_analysis: str                          # agent self-reports what tone it used (e.g. "professional and empathetic")
    placeholders_detected: list[str]            # any [brackets] left unfilled — must be empty to proceed

    @field_validator("placeholders_detected")
    @classmethod
    def no_placeholders_allowed(cls, v):
        if len(v) > 0:
            raise ValueError(
                f"Draft contains unfilled placeholders: {v}. "
                f"All placeholders must be resolved before the draft can proceed."
            )
        return v

    @field_validator("subject_line", "email_body")
    @classmethod
    def fields_must_not_be_empty(cls, v):
        if not v.strip():
            raise ValueError("Subject line and email body cannot be empty")
        return v
