from schemas.email import EmailObject

def test_valid_email():
    email = EmailObject(
        sender="client@example.com",
        recipient="me@company.com",
        subject="Project Orion update",
        body="Can you send me the latest status?",
        timestamp="2024-06-01T10:00:00",
        client_id="client_882"
    )
    assert email.sender == "client@example.com"

def test_missing_required_field():
    try:
        email = EmailObject(
            sender="client@example.com"
            # missing everything else
        )
    except Exception as e:
        assert e is not None