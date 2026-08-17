import re

# Order matters — checked top to bottom, first match wins
RULES = [
    ("spam", [
        r"\bviagra\b", r"\bcrypto\s*giveaway\b", r"\bclick here now\b",
        r"\bwire transfer\b", r"\burgent\b.*\bwire\b",
        r"\bverify your account\b", r"\binheritance\b",
        r"\bnigerian prince\b", r"\bclaim your prize\b",
        r"\baccount.*suspended\b", r"\bselected.*winner\b",
    ]),
    ("ack", [
        r"\bthanks?\b", r"\bthank you\b", r"^\s*ok\b", r"\bgot it\b",
        r"\bsounds good\b", r"\bnoted\b", r"\bwill do\b", r"\bawesome\b.*\bthank",
        r"\byep\b.*\bthanks\b", r"\ball good\b",
    ]),
    ("meeting", [
        r"\bschedule\b", r"\bmeeting\b", r"\bcalendar\b", r"\bavailab(le|ility)\b",
        r"\breschedule\b",
        r"\bbook(ing)?\b.*\b(call|meeting|time|slot)\b",
        r"\bfree\b.*\b(tomorrow|today|this week|next week|monday|tuesday|wednesday|thursday|friday)\b",
        r"\bcatch up\b", r"\bsync (call|meeting|up)\b", r"\bgrab coffee\b",
        r"\bfollow-?up call\b",
    ]),
    ("faq", [
        r"\bhow do i\b", r"\bcan you tell me how\b",
        r"\bwhat(\'s| is| are)\b",
        r"\bwhere can i\b", r"\bdo you (support|offer)\b",
        r"\bis it possible to\b", r"\bpricing\b", r"\bdocumentation\b",
        r"\brate limits?\b", r"\bfree trial\b", r"\brefund policy\b",
    ]),
    ("emotional", [
        r"\bfrustrat(ed|ing)\b", r"\bangry\b", r"\bdisappoint(ed|ing)\b",
        r"\bupset\b", r"\bunacceptable\b", r"\bhorrible\b",
        r"\bterrible\b", r"\bdisgusted\b", r"\bappalled\b",
        r"\bdevastated\b", r"\bfed up\b", r"\bstressing me out\b",
        r"\bat my limit\b", r"\bfurious\b", r"\blet down\b",
    ]),
    ("support", [
        r"\bnot working\b", r"\berror\b", r"\bissue\b", r"\bbroken\b",
        r"\bcan't (log in|login|access)\b",
        r"\b(reset (my )?password|password reset)\b",
        r"\bfix\b", r"\bcrash(ing|es)?\b", r"\bloading\b",
        r"\blocke?d\b", r"\btimeout\b", r"\bduplicate\b",
        r"\bnot (loading|syncing)\b", r"\bconnect(ing)?\b",
        r"\b500 error\b", r"\bcredentials\b",
    ]),
]

def classify_email(subject: str, body: str) -> str:
    text = f"{subject}\n{body}".lower().strip()

    for category, patterns in RULES:
        for pattern in patterns:
            if re.search(pattern, text, re.MULTILINE):
                return category

    return "ambiguous"