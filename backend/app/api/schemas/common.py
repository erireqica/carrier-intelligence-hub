import re
from typing import Annotated

from email_validator import EmailNotValidError, validate_email
from pydantic import AfterValidator

from app.core.security import normalize_email

DEMO_EMAIL_PATTERN = re.compile(r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@demo\.local$")


def validate_internal_email(value: str) -> str:
    normalized = normalize_email(value)
    if DEMO_EMAIL_PATTERN.fullmatch(normalized):
        return normalized
    try:
        validated = validate_email(normalized, check_deliverability=False)
    except EmailNotValidError as error:
        raise ValueError("Enter a valid internal email address") from error
    return normalize_email(validated.normalized)


InternalEmail = Annotated[str, AfterValidator(validate_internal_email)]
