from pydantic import BaseModel, field_validator
from typing import Optional
from .email import EmailObject


class RetrievedFact(BaseModel):
    """
    A single piece of information retrieved from the Pinecone vector database.
    Each fact comes from a specific source document.
    """

    content: str                        # the actual text retrieved
    source_file: str                    # which document it came from (e.g. "Project_Orion_Brief.pdf")
    similarity_score: float             # how closely it matched the query (must be above 0.75 to be used)
    client_id: str                      # which client this fact belongs to

    @field_validator("similarity_score")
    @classmethod
    def score_must_be_valid(cls, v):
        if not (0.0 <= v <= 1.0):
            raise ValueError("Similarity score must be between 0 and 1")
        return v


class ResearchInput(BaseModel):
    """
    What the Research Agent receives.
    It gets the original email plus confirmation that research is actually needed.
    """

    email: EmailObject
    requires_research: bool             # passed from TriageOutput — should always be True here


class ResearchOutput(BaseModel):
    """
    What the Research Agent returns.
    
    Key design decision: if no facts are found above the similarity threshold,
    missing_information is set to True. This forces the Drafting Agent to say
    "I'll need to follow up on that" instead of making something up.
    """

    found_facts: list[RetrievedFact]    # list of relevant facts retrieved from the database
    missing_information: bool           # True if nothing useful was found — hallucination prevention
    missing_details: Optional[str] = None  # describes what was missing, if anything

    @field_validator("found_facts")
    @classmethod
    def validate_facts_above_threshold(cls, v):
        # only facts above the 0.75 cosine similarity threshold should make it here
        for fact in v:
            if fact.similarity_score < 0.75:
                raise ValueError(
                    f"Fact from '{fact.source_file}' has similarity score {fact.similarity_score} "
                    f"which is below the required threshold of 0.75"
                )
        return v
