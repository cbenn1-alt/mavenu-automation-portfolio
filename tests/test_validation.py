"""Unit tests: server-side validation."""
import pytest

from mavenu.validation import (
    ValidationError,
    in_service_area,
    normalize_email,
    normalize_phone,
    validate_lead_payload,
)

from .conftest import GOOD_LEAD


def test_valid_payload_is_cleaned():
    cleaned = validate_lead_payload(dict(GOOD_LEAD))
    assert cleaned["phone"] == "7015550142"
    assert cleaned["email"] == "dana.rivera@example.com"  # lowercased
    assert cleaned["service"] == "hvac"
    assert cleaned["zip"] == "58102"


def test_missing_name_rejected():
    data = dict(GOOD_LEAD, name="   ")
    with pytest.raises(ValidationError) as ei:
        validate_lead_payload(data)
    assert "name" in ei.value.field_errors


def test_bad_email_rejected_but_phone_only_ok():
    data = dict(GOOD_LEAD, email="not-an-email")
    with pytest.raises(ValidationError) as ei:
        validate_lead_payload(data)
    assert "email" in ei.value.field_errors

    ok = validate_lead_payload({**GOOD_LEAD, "email": ""})
    assert ok["email"] is None and ok["phone"] == "7015550142"


def test_no_contact_channel_rejected():
    data = dict(GOOD_LEAD, phone="", email="")
    with pytest.raises(ValidationError) as ei:
        validate_lead_payload(data)
    assert "contact" in ei.value.field_errors


def test_bad_phone_rejected():
    data = dict(GOOD_LEAD, phone="12345", email="")
    with pytest.raises(ValidationError) as ei:
        validate_lead_payload(data)
    assert "phone" in ei.value.field_errors


@pytest.mark.parametrize("raw,expected", [
    ("(701) 555-0142", "7015550142"),
    ("701-555-0142", "7015550142"),
    ("+1 701 555 0142", "7015550142"),
    ("17015550142", "7015550142"),
    ("555-0142", None),
    ("abcdefghij", None),
])
def test_phone_normalization(raw, expected):
    assert normalize_phone(raw) == expected


def test_unknown_service_rejected():
    data = dict(GOOD_LEAD, service="dog-walking")
    with pytest.raises(ValidationError) as ei:
        validate_lead_payload(data)
    assert "service" in ei.value.field_errors


def test_bad_zip_rejected():
    for bad in ["1234", "123456", "abcde", ""]:
        with pytest.raises(ValidationError):
            validate_lead_payload(dict(GOOD_LEAD, zip=bad))


def test_notes_length_capped():
    with pytest.raises(ValidationError) as ei:
        validate_lead_payload(dict(GOOD_LEAD, notes="x" * 2001))
    assert "notes" in ei.value.field_errors


def test_service_area_membership():
    assert in_service_area("58102")
    assert not in_service_area("99999")


def test_email_normalization():
    assert normalize_email("  Dana@Example.COM ") == "dana@example.com"
    assert normalize_email("bad") is None
    assert normalize_email("") is None
