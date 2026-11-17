import re

EMAIL_MAX_LENGTH = 254
EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)


def is_valid_email(value: str) -> bool:
    if not isinstance(value, str) or len(value) > EMAIL_MAX_LENGTH:
        return False
    return EMAIL_PATTERN.fullmatch(value) is not None
