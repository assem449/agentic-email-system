from app.gmail_client import get_gmail_service, fetch_unread_emails

service = get_gmail_service()  # opens browser first time — log in with temp Gmail account
emails = fetch_unread_emails(service)

for e in emails:
    print(f"From: {e['sender']}")
    print(f"Subject: {e['subject']}")
    print(f"Body preview: {e['body'][:100]}")
    print("---")