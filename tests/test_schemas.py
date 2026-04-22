import pytest
from datetime import datetime
from pydantic import ValidationError

from schemas.email import EmailObject
from schemas.triage import TriageInput, TriageOutput
from schemas.research import ResearchInput, ResearchOutput, RetrievedFact
from schemas.draft import DraftInput, DraftOutput
from schemas.qa import QAInput, QAOutput


# ──────────────────────────────────────────
# Helpers — reusable valid objects
# ──────────────────────────────────────────

def make_email():
    return EmailObject(
        sender="client@acme.com",
        recipient="agent@company.com",
        subject="Project Orion status update",
        body="Can you tell me the current status of Project Orion and the deadline?",
        timestamp=datetime(2024, 6, 1, 10, 0, 0),
        client_id="client_882",
        is_new_contact=False
    )

def make_fact():
    return RetrievedFact(
        content="Project Orion is 80% complete as of November 10.",
        source_file="Project_Orion_Brief.pdf",
        similarity_score=0.92,
        client_id="client_882"
    )

def make_research_output():
    return ResearchOutput(
        found_facts=[make_fact()],
        missing_information=False
    )

def make_draft_output():
    return DraftOutput(
        subject_line="Re: Project Orion status update",
        email_body="Hi, Project Orion is currently 80% complete with a deadline of November 30. Let me know if you need anything else.",
        tone_analysis="Professional and informative",
        placeholders_detected=[]
    )


# ──────────────────────────────────────────
# EmailObject tests
# ──────────────────────────────────────────

class TestEmailObject:

    def test_valid_email(self):
        email = make_email()
        assert email.sender == "client@acme.com"
        assert email.client_id == "client_882"

    def test_empty_body_fails(self):
        with pytest.raises(ValidationError):
            EmailObject(
                sender="client@acme.com",
                recipient="agent@company.com",
                subject="Test",
                body="   ",              # blank body
                timestamp=datetime.now()
            )

    def test_invalid_sender_fails(self):
        with pytest.raises(ValidationError):
            EmailObject(
                sender="not-an-email",   # missing @ symbol
                recipient="agent@company.com",
                subject="Test",
                body="Hello",
                timestamp=datetime.now()
            )

    def test_missing_required_field_fails(self):
        with pytest.raises(ValidationError):
            EmailObject(sender="client@acme.com")   # missing everything else


# ──────────────────────────────────────────
# Triage tests
# ──────────────────────────────────────────

class TestTriage:

    def test_valid_triage_output(self):
        output = TriageOutput(
            intent_category="status_update",
            urgency_score=3,
            requires_research=True,
            reasoning="Client is asking about project status which requires checking our records."
        )
        assert output.requires_research is True
        assert output.urgency_score == 3

    def test_urgency_out_of_range_fails(self):
        with pytest.raises(ValidationError):
            TriageOutput(
                intent_category="spam",
                urgency_score=9,            # invalid — must be 1 to 5
                requires_research=False,
                reasoning="This is spam."
            )

    def test_empty_reasoning_fails(self):
        with pytest.raises(ValidationError):
            TriageOutput(
                intent_category="other",
                urgency_score=1,
                requires_research=False,
                reasoning=""               # empty reasoning not allowed
            )

    def test_valid_intent_categories(self):
        valid_categories = ["scheduling", "pricing_inquiry", "status_update", "complaint", "spam", "other"]
        for category in valid_categories:
            output = TriageOutput(
                intent_category=category,
                urgency_score=1,
                requires_research=False,
                reasoning="Test reasoning."
            )
            assert output.intent_category == category

    def test_invalid_intent_category_fails(self):
        with pytest.raises(ValidationError):
            TriageOutput(
                intent_category="random_made_up_category",  # not in the allowed list
                urgency_score=1,
                requires_research=False,
                reasoning="Test."
            )


# ──────────────────────────────────────────
# Research tests
# ──────────────────────────────────────────

class TestResearch:

    def test_valid_retrieved_fact(self):
        fact = make_fact()
        assert fact.similarity_score == 0.92

    def test_fact_below_threshold_fails(self):
        with pytest.raises(ValidationError):
            ResearchOutput(
                found_facts=[
                    RetrievedFact(
                        content="Some weakly matched content.",
                        source_file="some_doc.pdf",
                        similarity_score=0.60,   # below 0.75 threshold
                        client_id="client_882"
                    )
                ],
                missing_information=False
            )

    def test_missing_information_flag(self):
        # when nothing useful is found, found_facts is empty and missing_information is True
        output = ResearchOutput(
            found_facts=[],
            missing_information=True,
            missing_details="No information found about Project Unicorn in the database."
        )
        assert output.missing_information is True
        assert len(output.found_facts) == 0

    def test_valid_research_output(self):
        output = make_research_output()
        assert len(output.found_facts) == 1
        assert output.missing_information is False


# ──────────────────────────────────────────
# Draft tests
# ──────────────────────────────────────────

class TestDraft:

    def test_valid_draft(self):
        draft = make_draft_output()
        assert draft.placeholders_detected == []
        assert "Project Orion" in draft.email_body

    def test_unfilled_placeholder_fails(self):
        with pytest.raises(ValidationError):
            DraftOutput(
                subject_line="Re: Your inquiry",
                email_body="Please contact us by [Insert Date].",   # placeholder not filled
                tone_analysis="Professional",
                placeholders_detected=["[Insert Date]"]
            )

    def test_empty_subject_fails(self):
        with pytest.raises(ValidationError):
            DraftOutput(
                subject_line="",            # empty subject not allowed
                email_body="Hello there.",
                tone_analysis="Friendly",
                placeholders_detected=[]
            )

    def test_draft_with_research_context(self):
        draft_input = DraftInput(
            email=make_email(),
            research=make_research_output()
        )
        assert draft_input.research is not None
        assert len(draft_input.research.found_facts) == 1

    def test_draft_without_research(self):
        # research is optional — some emails don't need it
        draft_input = DraftInput(
            email=make_email(),
            research=None
        )
        assert draft_input.research is None


# ──────────────────────────────────────────
# QA tests
# ──────────────────────────────────────────

class TestQA:

    def test_approved_status(self):
        output = QAOutput(
            status="APPROVED",
            confidence_score=0.95,
            security_flag=False
        )
        assert output.status == "APPROVED"
        assert output.security_flag is False

    def test_rejected_requires_feedback(self):
        with pytest.raises(ValidationError):
            QAOutput(
                status="REJECTED",
                confidence_score=0.70,
                feedback=None               # feedback is required when rejected
            )

    def test_rejected_with_feedback(self):
        output = QAOutput(
            status="REJECTED",
            confidence_score=0.70,
            feedback="Tone is too informal. Rewrite to be more professional."
        )
        assert output.feedback is not None

    def test_escalate_to_human(self):
        output = QAOutput(
            status="ESCALATE_TO_HUMAN",
            confidence_score=0.50,
            security_flag=True              # PII detected
        )
        assert output.status == "ESCALATE_TO_HUMAN"
        assert output.security_flag is True

    def test_confidence_out_of_range_fails(self):
        with pytest.raises(ValidationError):
            QAOutput(
                status="APPROVED",
                confidence_score=1.5        # invalid — must be between 0 and 1
            )

    def test_full_qa_input(self):
        qa_input = QAInput(
            email=make_email(),
            research=make_research_output(),
            draft=make_draft_output()
        )
        assert qa_input.draft.subject_line == "Re: Project Orion status update"
