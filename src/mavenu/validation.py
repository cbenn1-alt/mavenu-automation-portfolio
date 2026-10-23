"""Server-side validation for lead intake.

All validation happens here, on the server. Client-side checks (if any) are
a convenience only and are never trusted.
"""
from __future__ import annotations

import re

# Supported home-service verticals for the demo.
SERVICES = ("hvac", "plumbing", "electrical", "roofing", "landscaping")

# Synthetic service-area ZIP codes used by the demo. These are stand-ins;
# they do not represent a real service territory.
SERVICE_AREA_ZIPS = frozenset(
    {"58102", "58103", "58104", "58105", "56560", "56515", "58078"}
)

URGENCIES = ("standard", "priority")

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_NON_DIGIT_RE = re.compile(r"\D")

MAX_NAME_LEN = 120
MAX_NOTES_LEN = 2000


class ValidationError(Exception):
    """Raised when a payload fails server-side validation.

    Carries a dict of {field: message} so callers can render field errors.
    """

    def __init__(self, field_errors: dict[str, str]):
        super().__init__("; ".join(f"{f}: {m}" for f, m in field_errors.items()))
        self.field_errors = field_errors


def normalize_phone(raw: str) -> str | None:
    """Return normalized digits, or None when the value is not a valid phone.

    Accepts common formatting; valid = 10 digits, or 11 digits starting with 1.
    """
    if raw is None:
        return None
    digits = _NON_DIGIT_RE.sub("", str(raw))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return digits


def normalize_email(raw: str) -> str | None:
    """Return lowercased email, or None when invalid."""
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if not value:
        return None
    if not _EMAIL_RE.match(value):
        return None
    return value


def validate_lead_payload(data: dict) -> dict:
    """Validate raw intake data. Returns cleaned values or raises ValidationError."""
    errors: dict[str, str] = {}
    cleaned: dict = {}

    name = str(data.get("name", "")).strip()
    if not name:
        errors["name"] = "Name is required."
    elif len(name) > MAX_NAME_LEN:
        errors["name"] = f"Name must be {MAX_NAME_LEN} characters or fewer."
    else:
        cleaned["name"] = name

    service = str(data.get("service", "")).strip().lower()
    if service not in SERVICES:
        errors["service"] = f"Service must be one of: {', '.join(SERVICES)}."
    else:
        cleaned["service"] = service

    zip_code = str(data.get("zip", "")).strip()
    if not re.fullmatch(r"\d{5}", zip_code):
        errors["zip"] = "ZIP must be 5 digits."
    else:
        cleaned["zip"] = zip_code

    phone_raw = data.get("phone")
    email_raw = data.get("email")
    phone = normalize_phone(phone_raw) if phone_raw not in (None, "") else None
    email = normalize_email(email_raw) if email_raw not in (None, "") else None
    if phone_raw not in (None, "") and phone is None:
        errors["phone"] = "Phone must be a valid 10-digit number."
    if email_raw not in (None, "") and email is None:
        errors["email"] = "Email must be a valid email address."
    if phone is None and email is None and "phone" not in errors and "email" not in errors:
        errors["contact"] = "Provide at least a phone number or an email address."
    cleaned["phone"] = phone
    cleaned["email"] = email

    urgency = str(data.get("urgency", "standard")).strip().lower() or "standard"
    if urgency not in URGENCIES:
        errors["urgency"] = f"Urgency must be one of: {', '.join(URGENCIES)}."
    else:
        cleaned["urgency"] = urgency

    notes = data.get("notes", "")
    notes = "" if notes is None else str(notes).strip()
    if len(notes) > MAX_NOTES_LEN:
        errors["notes"] = f"Notes must be {MAX_NOTES_LEN} characters or fewer."
    cleaned["notes"] = notes

    if errors:
        raise ValidationError(errors)
    return cleaned


def in_service_area(zip_code: str) -> bool:
    """True when the ZIP is inside the synthetic demo service area."""
    return zip_code in SERVICE_AREA_ZIPS
