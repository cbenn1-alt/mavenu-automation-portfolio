"""Project Q06 — deterministic contact-data normalizers.

Every cleaner in this module is a pure function of its input and is
**idempotent**: ``normalize(normalize(x)) == normalize(x)`` for every input
(asserted by the test suite). Normalization never invents data: it only
collapses case, whitespace, and formatting variants so that the *same*
real-world value compares equal.

Cleaners:

- ``normalize_name`` — strip, collapse internal whitespace, title-case.
  Display/storage canonical form.
- ``name_key`` — lowercase, punctuation stripped, tokens sorted
  alphabetically. Comparison/blocking key; token sorting makes
  "Smith John" and "John Smith" equivalent.
- ``normalize_phone`` — digits extracted; 10 digits render as
  ``(XXX) XXX-XXXX``; an 11-digit leading-``1`` NANP number is trimmed to
  10. Anything else is kept as bare digits (never discarded, never
  reformatted into a guess).
- ``phone_digits`` — digits only; the blocking key.
- ``normalize_email`` — strip + lowercase.
- ``normalize_address`` — strip, collapse whitespace, title-case, then
  expand common US street suffixes to a canonical form
  (``St``/``Street`` -> ``Street``, ``Ave``/``Avenue`` -> ``Avenue`` ...).
- ``normalize_zip`` — first five digits (ZIP+4 collapses to ZIP).
- ``sanitize_cell`` — CSV-formula guard (``=``, ``+``, ``-``, ``@``
  leading cells neutralized with a leading quote), same convention as Q05.

ALL DATA PROCESSED HERE IS SYNTHETIC DEMONSTRATION DATA. The hashing
strategy for real deployments is documented in
projects/project_q06/SECURITY.md — raw PII is never the blocking key in a
real deployment; keyed hashes (HMAC) are.
"""
from __future__ import annotations

import re
from typing import Any

_WS_RE = re.compile(r"\s+")
_NON_ALNUM_SPACE_RE = re.compile(r"[^a-z0-9\s]")
_DIGITS_RE = re.compile(r"\D")

# Canonical US street-suffix forms. Keys are lowercase; values are the
# canonical display form. Applied whole-token only.
_STREET_SUFFIXES = {
    "street": "Street", "st": "Street", "str": "Street",
    "avenue": "Avenue", "ave": "Avenue", "av": "Avenue",
    "road": "Road", "rd": "Road",
    "drive": "Drive", "dr": "Drive",
    "lane": "Lane", "ln": "Lane",
    "boulevard": "Boulevard", "blvd": "Boulevard",
    "court": "Court", "ct": "Court",
    "circle": "Circle", "cir": "Circle",
    "place": "Place", "pl": "Place",
    "terrace": "Terrace", "ter": "Terrace",
    "parkway": "Parkway", "pkwy": "Parkway",
    "trail": "Trail", "trl": "Trail",
    "way": "Way",
}

# Cells starting with these characters are interpreted as formulas by
# spreadsheet apps (CSV injection). Neutralize on ingest with a leading
# quote — the same convention as Q05's reconcile.sanitize_cell.
_FORMULA_LEADS = ("=", "+", "-", "@")


def _clean(value: Any) -> str:
    """Strip and collapse all whitespace runs to a single space."""
    return _WS_RE.sub(" ", str(value or "")).strip()


def normalize_name(value: Any) -> str:
    """Canonical display form of a person/business name.

    >>> normalize_name("  MARCUS   bell ")
    'Marcus Bell'
    """
    return _clean(value).title()


def name_key(value: Any) -> str:
    """Comparison/blocking key for a name.

    Lowercase, punctuation removed, tokens sorted alphabetically — so
    "Bell, Marcus" and "marcus bell" produce the same key.

    >>> name_key("Bell, Marcus")
    'bell marcus'
    """
    text = _NON_ALNUM_SPACE_RE.sub("", _clean(value).lower())
    return " ".join(sorted(text.split()))


def phone_digits(value: Any) -> str:
    """Digits-only form of a phone number; the blocking key.

    An 11-digit number with a leading ``1`` (NANP country code) is trimmed
    to 10 digits so "+1 (701) 555-0142" and "7015550142" share the same
    blocking key.

    >>> phone_digits("(701) 555-0142")
    '7015550142'
    >>> phone_digits("+1 701-555-0142")
    '7015550142'
    """
    digits = _DIGITS_RE.sub("", str(value or ""))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def normalize_phone(value: Any) -> str:
    """Canonical display form of a phone number.

    10 digits -> ``(XXX) XXX-XXXX``; 11 digits with a leading ``1``
    (NANP country code) are trimmed to 10 first. Anything else is kept as
    bare digits — the normalizer never guesses a format it cannot verify.

    >>> normalize_phone("+1 701-555-0142")
    '(701) 555-0142'
    """
    digits = phone_digits(value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return digits


def normalize_email(value: Any) -> str:
    """Canonical form of an email address: stripped, lowercased.

    >>> normalize_email("  Marcus.Bell@Example.COM ")
    'marcus.bell@example.com'
    """
    return _clean(value).lower()


def normalize_address(value: Any) -> str:
    """Canonical display form of a street address.

    Whitespace collapsed, title-cased, common suffixes expanded to one
    canonical form so "123 main st" and "123 Main Street" compare equal.

    >>> normalize_address("  42 prairie LN ")
    '42 Prairie Lane'
    """
    tokens = _clean(value).title().split(" ")
    return " ".join(_STREET_SUFFIXES.get(tok.lower(), tok) for tok in tokens)


def normalize_zip(value: Any) -> str:
    """Canonical ZIP: first five digits (ZIP+4 collapses to ZIP).

    >>> normalize_zip("58102-4301")
    '58102'
    """
    return phone_digits(value)[:5]


def sanitize_cell(value: Any) -> tuple[str, bool]:
    """Return (sanitized_value, was_sanitized).

    Strips surrounding whitespace; a cell whose first non-space character
    is a formula trigger (= + - @) is prefixed with a single quote so
    spreadsheet apps treat it as literal text. All other values pass
    through unchanged.
    """
    text = "" if value is None else str(value).strip()
    if text and text[0] in _FORMULA_LEADS:
        return "'" + text, True
    return text, False
