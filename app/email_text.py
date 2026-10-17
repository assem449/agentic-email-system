"""Turns a raw Gmail message into the text the pipeline should see.

Real email is not the clean one-paragraph text in the eval set: it has
quoted earlier messages, sign-offs ("Thanks,\nSarah"), mobile footers and
HTML-only bodies. Left in, these push the classifier towards `ack`
(every "Thanks," sign-off looks like a thank-you) and give the LLM a
truncated or empty email to reply to.
"""

from __future__ import annotations  # `str | None` on Python 3.9

import html
import re

# Gmail's own tab labels. Promotions/Social/Updates/Forums are bulk mail by
# Gmail's definition; only Primary (no CATEGORY_* label, or
# CATEGORY_PERSONAL) is person-to-person.
BULK_GMAIL_LABELS = {
    "CATEGORY_PROMOTIONS",
    "CATEGORY_SOCIAL",
    "CATEGORY_UPDATES",
    "CATEGORY_FORUMS",
}

_BULK_SENDER = re.compile(
    r"no-?reply|do-?not-?reply|notifications?@|newsletter|mailer-daemon|"
    r"@(linkedin|facebookmail|joinhandshake|e\.)",
    re.IGNORECASE,
)

# A person rarely writes "unsubscribe"; mailing-list footers always do.
_UNSUBSCRIBE = re.compile(r"\bunsubscribe\b|\bopt[ -]out\b|email preferences", re.IGNORECASE)

_FORWARD_HEADER = re.compile(
    r"^\s*(-{2,}\s*Forwarded message\s*-{2,}|Begin forwarded message:)",
    re.IGNORECASE | re.MULTILINE,
)
_FORWARDED_FROM = re.compile(r"^\s*From:\s*(.+)$", re.IGNORECASE | re.MULTILINE)

# A forward with only a few words added ("FYI", "see below") is passing
# the original along, not asking anything.
_FORWARD_COMMENT_MAX_WORDS = 5

# A line that starts the quoted copy of an earlier message.
_QUOTE_HEADER = re.compile(
    r"^\s*(On .{0,200}wrote:\s*$"
    r"|-{2,}\s*Original Message\s*-{2,}"
    r"|-{2,}\s*Forwarded message\s*-{2,}"
    r"|From:\s.+$)",
    re.IGNORECASE,
)

# A line that is only a sign-off. Everything from here down is signature.
_SIGN_OFF = re.compile(
    r"^\s*(thanks|thank you|thanks so much|many thanks|best|best regards|"
    r"kind regards|warm regards|regards|cheers|sincerely|all the best|"
    r"respectfully|take care)\s*[,.!]?\s*$",
    re.IGNORECASE,
)

_MOBILE_FOOTER = re.compile(r"^\s*sent from my \w+", re.IGNORECASE)

# Sign-offs only count as a signature near the end of the message, so a
# body that opens with "Thanks," on its own line is not discarded.
_SIGNATURE_WINDOW = 6


def headers_dict(payload: dict) -> dict:
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


def bulk_reason(label_ids, headers: dict) -> str | None:
    """Why this message is bulk mail, or None if it looks person-to-person.

    Deterministic and free: these are signals the sender's mail system or
    Gmail already attached, so no model is needed to see them.
    """
    labels = set(label_ids or [])
    hit = labels & BULK_GMAIL_LABELS
    if hit:
        return f"gmail_label:{sorted(hit)[0]}"
    if "list-unsubscribe" in headers:
        return "header:list-unsubscribe"
    if "list-id" in headers:
        return "header:list-id"
    if headers.get("precedence", "").strip().lower() in ("bulk", "list", "junk"):
        return "header:precedence"
    if headers.get("auto-submitted", "no").strip().lower() != "no":
        return "header:auto-submitted"
    if _BULK_SENDER.search(headers.get("from", "")):
        return "sender:no-reply"
    return None


def body_bulk_reason(raw_body: str) -> str | None:
    """Bulk signals in the text itself, for mail whose headers say nothing.

    Two cases the header check misses: a newsletter forwarded by a person
    (the forward carries the forwarder's headers, not the list's), and
    seeded study scenarios, which are inserted without list headers.
    """
    fwd = _FORWARD_HEADER.search(raw_body)
    if fwd:
        comment = raw_body[:fwd.start()]
        if len(comment.split()) <= _FORWARD_COMMENT_MAX_WORDS:
            original = raw_body[fwd.end():]
            sender = _FORWARDED_FROM.search(original)
            if sender and _BULK_SENDER.search(sender.group(1)):
                return "forwarded:no-reply-sender"
            if _UNSUBSCRIBE.search(original):
                return "forwarded:unsubscribe"
        return None  # a forward with a real comment is the forwarder's own email
    if _UNSUBSCRIBE.search(raw_body):
        return "body:unsubscribe"
    return None


def html_to_text(raw_html: str) -> str:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style", "head"]):
            tag.decompose()
        for br in soup.find_all("br"):
            br.replace_with("\n")
        text = soup.get_text("\n")
    except ImportError:
        text = re.sub(r"(?is)<(script|style|head).*?</\1>", "", raw_html)
        text = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", text)
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
    lines = [line.strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def split_quoted(body: str) -> tuple[str, str]:
    """Split a reply into (new text, quoted earlier messages)."""
    lines = body.replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        if _QUOTE_HEADER.match(line):
            return "\n".join(lines[:i]).strip(), "\n".join(lines[i:]).strip()

    # No header line, but a trailing block of "> " lines is still a quote.
    new_lines, quoted_lines = [], []
    for line in lines:
        if line.lstrip().startswith(">"):
            quoted_lines.append(line.lstrip()[1:].lstrip())
        elif quoted_lines and line.strip():
            # Text after a quote block is an inline reply; keep it all as new.
            return body.strip(), ""
        else:
            new_lines.append(line)
    return "\n".join(new_lines).strip(), "\n".join(quoted_lines).strip()


def strip_signature(text: str) -> str:
    lines = text.split("\n")

    for i, line in enumerate(lines):
        if line.rstrip() == "--" or line == "-- " or _MOBILE_FOOTER.match(line):
            lines = lines[:i]
            break

    start = max(0, len(lines) - _SIGNATURE_WINDOW)
    for i in range(start, len(lines)):
        if _SIGN_OFF.match(lines[i]):
            lines = lines[:i]
            break

    stripped = "\n".join(lines).strip()
    # A body that was only a sign-off ("Thanks!") is the whole message.
    return stripped or text.strip()


def clean_body(raw_body: str) -> tuple[str, str]:
    """Return (body for classification and reply, quoted thread history)."""
    new_text, quoted = split_quoted(raw_body)
    return strip_signature(new_text or raw_body.strip()), quoted
