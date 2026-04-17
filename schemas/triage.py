from pydantic import BaseModel, field_validator
from typing import Literal
from .email import EmailObject


class TriageInput(BaseModel):
    """
    What the Triage Agent receives.
    Just the parsed email — nothing else needed at this stage.
    """

    email: EmailObject


class TriageOutput(BaseModel):
    """
    What the Triage Agent returns.
    This output decides the entire routing of the workflow:
    - which intent category applies
    - how urgent the email is
    - whether the Research Agent needs to be called
    """

    intent_category: Literal[
        "scheduling",
        "pricing_inquiry",
        "status_update",
        "complaint",
        "spam",
        "other"
    ]
    urgency_score: int                  # 1 (low) to 5 (critical)
    requires_research: bool             # if True, Research Agent is called next; if False, go straight to Drafting
    reasoning: str                      # one sentence explaining the classification — useful for debugging

    @field_validator("urgency_score")
    @classmethod
    def urgency_must_be_valid(cls, v):
        if not (1 <= v <= 5):
            raise ValueError("Urgency score must be between 1 and 5")
        return v

    @field_validator("reasoning")
    @classmethod
    def reasoning_must_not_be_empty(cls, v):
        if not v.strip():
            raise ValueError("Reasoning cannot be empty")
        return v
