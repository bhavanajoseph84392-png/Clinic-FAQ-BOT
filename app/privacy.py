import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+91[\s-]*)?\d[\d\s-]{8,}\d")


def _mask_email(match: re.Match) -> str:
    email = match.group(0)
    local, domain = email.split("@", 1)
    return (local[:1] or "*") + "***@" + domain


def _mask_phone(match: re.Match) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if digits.startswith("91") and len(digits) >= 12:
        digits = digits[2:]
    if len(digits) < 10:
        return match.group(0)
    return digits[:2] + "xxxxxx" + digits[-2:]


def mask_contacts(text: str) -> str:
    """Mask phone numbers and email addresses in text before staff see it."""
    if not text:
        return text
    masked = EMAIL_RE.sub(_mask_email, text)
    return PHONE_RE.sub(_mask_phone, masked)
