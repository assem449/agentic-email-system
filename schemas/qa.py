from pydantic import BaseModel, field_validator
from typing import Literal, Optional
from .email import EmailObject
from .draft import DraftOutput
from .research import ResearchOutput


class QAInput(BaseModel):
    """
    What the QA Agent receives.
    It needs all three:the original email, the research context, and the draft to properly verify tone, accuracy, and safety.
    """

    email: EmailObject
    research: Optional[ResearchOutput] = None   # None if no research was done
    draft: DraftOutput


class QAOutput(BaseModel):
    """
    What the QA Agent returns.

    This output controls the LangGraph loop:
    - APPROVED  → move forward to HIL rules check
    - REJECTED  → send back to Drafting Agent with feedback (loop)
    - ESCALATE_TO_HUMAN → skip drafting, go straight to human review

    feedback is required when status is REJECTED so the Drafting Agent
    knows exactly what to fix. Without specific feedback the loop is useless.
    """

    status: Literal["APPROVED", "REJECTED", "ESCALATE_TO_HUMAN"]
    confidence_score: float             # 0.0 to 1.0 — below 0.90 triggers HIL review
    feedback: Optional[str] = None      # required if REJECTED, explains what needs to change
    security_flag: bool = False         # True if PII or sensitive content was detected in the draft

    @field_validator("confidence_score")
    @classmethod
    def score_must_be_valid(cls, v):
        if not (0.0 <= v <= 1.0):
            raise ValueError("Confidence score must be between 0 and 1")
        return v

    @field_validator("feedback")
    @classmethod
    def feedback_required_on_rejection(cls, v, info):
        # if status is REJECTED, feedback must explain why
        if info.data.get("status") == "REJECTED" and not v:
            raise ValueError("Feedback is required when status is REJECTED")
        return v
