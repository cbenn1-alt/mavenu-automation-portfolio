"""Server-side validation tests for request intake.

All contact details below are synthetic fixtures, not real people.
"""
import pytest

from mavenu.requests_approval import REQUEST_TYPES, validate_request_payload
from mavenu.validation import ValidationError

# All contact details below are synthetic fixtures, not real people.
GOOD_REQUEST = {
    "request_type": "purchase",
    "title": "Replacement HVAC blower motor",
    "amount": 2450.00,
    "cost_center": "OPS410",
    "justification": (
        "The blower motor in the main shop failed inspection and the "
        "replacement is required before the heating season starts."
    ),
    "requester_name": "Dana Rivera",
    "requester_email": "dana.rivera@example.com",
}


def _valid(**overrides):
    payload = dict(GOOD_REQUEST)
    payload.update(overrides)
    return validate_request_payload(payload)


def test_valid_payload_cleans_values():
    cleaned = _valid()
    assert cleaned["request_type"] == "purchase"
    assert cleaned["amount_cents"] == 245000
    assert cleaned["cost_center"] == "OPS410"
    assert cleaned["requester_email"] == "dana.rivera@example.com"


def test_cost_center_normalized_to_uppercase():
    assert _valid(cost_center="ops410")["cost_center"] == "OPS410"


@pytest.mark.parametrize("request_type", list(REQUEST_TYPES))
def test_all_request_types_accepted(request_type):
    amount = 100 if request_type != "access" else ""
    payload = _valid(request_type=request_type, amount=amount)
    assert payload["request_type"] == request_type


def test_non_monetary_type_may_have_zero_amount():
    cleaned = _valid(request_type="access", amount="")
    assert cleaned["amount_cents"] == 0


def test_monetary_type_requires_positive_amount():
    with pytest.raises(ValidationError) as exc:
        _valid(amount="")
    assert "amount" in exc.value.field_errors
    with pytest.raises(ValidationError) as exc:
        _valid(amount=0)
    assert "amount" in exc.value.field_errors


def test_amount_rejects_garbage_and_negatives():
    with pytest.raises(ValidationError):
        _valid(amount="lots")
    with pytest.raises(ValidationError):
        _valid(amount=-50)


def test_amount_cap_rejects_absurd_values():
    with pytest.raises(ValidationError) as exc:
        _valid(amount=99_999_999)
    assert "amount" in exc.value.field_errors


def test_justification_requires_minimum_length():
    with pytest.raises(ValidationError) as exc:
        _valid(justification="too short")
    assert "justification" in exc.value.field_errors


def test_justification_length_cap():
    with pytest.raises(ValidationError):
        _valid(justification="x" * 2001)


def test_cost_center_pattern_enforced():
    for bad in ["", "ab", "OPS 410", "ops-410!", "TOOLONGCODE123"]:
        with pytest.raises(ValidationError) as exc:
            _valid(cost_center=bad)
        assert "cost_center" in exc.value.field_errors


def test_requester_identity_fields_required():
    with pytest.raises(ValidationError) as exc:
        _valid(requester_name="")
    assert "requester_name" in exc.value.field_errors
    with pytest.raises(ValidationError) as exc:
        _valid(requester_email="not-an-email")
    assert "requester_email" in exc.value.field_errors


def test_unknown_request_type_rejected():
    with pytest.raises(ValidationError) as exc:
        _valid(request_type="spaceship")
    assert "request_type" in exc.value.field_errors


def test_title_required_and_capped():
    with pytest.raises(ValidationError):
        _valid(title="")
    with pytest.raises(ValidationError):
        _valid(title="x" * 121)


def test_multiple_field_errors_reported_together():
    with pytest.raises(ValidationError) as exc:
        _valid(request_type="nope", title="", requester_email="bad")
    fields = exc.value.field_errors
    assert {"request_type", "title", "requester_email"} <= set(fields)
