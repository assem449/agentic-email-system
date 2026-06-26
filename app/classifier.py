import re

# Order matters — checked top to bottom, first match wins
RULES = [
    ("spam", [
        r"\bviagra\b", r"\bcrypto\s*giveaway\b", r"\bclick here now\b",
        r"\bwire transfer\b.*\burgent\b", r"\bverify your account\b",
    ]),
    ("ack", [
        r"^\s*thanks?!?\s*$", r"^\s*thank you!?\s*$", r"^\s*ok!?\s*$",
        r"^\s*got it!?\s*$", r"^\s*sounds good!?\s*$",
    ]),
    ("meeting", [
        r"\bschedule\b", r"\bmeeting\b", r"\bcalendar\b", r"\bavailab(le|ility)\b",
        r"\breschedule\b", r"\bbook(ing)? a (call|meeting)\b",
    ]),
    ("faq", [
        r"\bhow do i\b", r"\bwhat is\b", r"\bwhere can i\b", r"\bdo you support\b",
        r"\bpricing\b", r"\bdocumentation\b",
    ]),
    ("emotional", [
        r"\bfrustrat(ed|ing)\b", r"\bangry\b", r"\bdisappoint(ed|ing)\b",
        r"\bupset\b", r"\bunacceptable\b", r"\bhorrible\b",
    ]),
    ("support", [
        r"\bnot working\b", r"\berror\b", r"\bissue\b", r"\bbroken\b",
        r"\bcan't (log in|login|access)\b",
        r"\b(reset (my )?password|password reset)\b",
    ]),
]

def classify_email(subject: str, body: str) -> str:
    text = f"{subject}\n{body}".lower().strip()

    for category, patterns in RULES:
        for pattern in patterns:
            if re.search(pattern, text, re.MULTILINE):
                return category

    return "ambiguous"