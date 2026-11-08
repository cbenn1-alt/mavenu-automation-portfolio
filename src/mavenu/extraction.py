"""Project P03 — deterministic rule-based field extraction.

This module is the extraction engine. It is a RULE-BASED demonstration:
every field is extracted by an ordered list of documented regex/fallback
rules, each carrying a fixed confidence. There is NO trained model, no
statistical inference, and no black box anywhere — the rule that fired,
the source line, and the raw matched text are stored as provenance for
every extracted field, so any extraction can be checked by hand.

Confidence policy (ExtractionConfig.accept_threshold, default 0.80):
a field extracted at/above the threshold is auto-accepted; a field
extracted below it stays ``proposed`` and MUST be human-reviewed — there
is no auto-accept path below the threshold (enforced in docintel.py).
A field no rule extracts is ``missing``.

ALL DATA IS SYNTHETIC DEMONSTRATION DATA. See the module README in
projects/project03/ for the honest-status banner.
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from .reconcile import cents_to_decimal, parse_amount_cents

DOC_TYPES = ("invoice", "receipt", "contract")

#: Default accept threshold: a field extracted with confidence >= this is
#: auto-accepted. Below it, the field stays proposed for human review.
DEFAULT_ACCEPT_THRESHOLD = Decimal("0.80")

#: Payment methods the validator accepts (receipts). Anything else is a
#: validation failure, not a silent normalization.
PAYMENT_METHODS = ("cash", "card", "check", "transfer")

_MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11,
    "December": 12,
}
_MONTH_NAMES = "|".join(_MONTHS)

# A first-line fallback only fires on a name-like line: 1-4 capitalized
# words, no punctuation. This is what keeps a garbage document
# ("lorem ipsum dolor sit amet") from "extracting" a vendor.
_NAME_LINE_RE = re.compile(r"^[A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*){0,3}$")


# ---------------------------------------------------------------------------
# Value transforms: candidate string -> (canonical value_text, value_cents)
# Raises ValueError when the candidate does not parse; the extractor then
# treats the rule as not having fired and tries the next rule.
# ---------------------------------------------------------------------------

def _t_text(candidate: str) -> tuple[str, None]:
    value = candidate.strip()
    if not value:
        raise ValueError("empty text value")
    return value, None


def _t_lower(candidate: str) -> tuple[str, None]:
    value = candidate.strip().lower()
    if not value:
        raise ValueError("empty text value")
    return value, None


def _t_money(candidate: str) -> tuple[str, int]:
    cents = parse_amount_cents(candidate)
    return str(cents_to_decimal(cents)), cents


def _t_date_iso(candidate: str) -> tuple[str, None]:
    return date.fromisoformat(candidate.strip()).isoformat(), None


def _t_date_us(candidate: str) -> tuple[str, None]:
    month, day, year = candidate.strip().split("/")
    return date(int(year), int(month), int(day)).isoformat(), None


def _t_date_long(candidate: str) -> tuple[str, None]:
    m = re.fullmatch(
        rf"({_MONTH_NAMES})\s+(\d{{1,2}}),\s+(\d{{4}})", candidate.strip()
    )
    if not m:
        raise ValueError(f"not a long-form date: {candidate!r}")
    return date(int(m.group(3)), _MONTHS[m.group(1)], int(m.group(2))).isoformat(), None


def _t_int(candidate: str) -> tuple[str, None]:
    return str(int(candidate.strip())), None


_TRANSFORMS = {
    "text": _t_text,
    "lower": _t_lower,
    "money": _t_money,
    "date_iso": _t_date_iso,
    "date_us": _t_date_us,
    "date_long": _t_date_long,
    "int": _t_int,
}


# ---------------------------------------------------------------------------
# Rule definitions.
#
# A rule is (rule_id, matcher, confidence, transform). ``matcher`` is
# either a compiled regex (searched with re.MULTILINE; capture group 1 is
# the candidate value) or one of the sentinel strings:
#   "FIRST_LINE_NAME"     — first non-empty line, must look like a name
#   "FIRST_LINE_CONTAINS" — first non-empty line containing
#                           "agreement" or "contract" (case-insensitive)
#   "LARGEST_AMOUNT"      — the largest $-amount in the whole text
# Rules are tried in order; the first rule that yields a parsable value
# wins. Confidence is the rule's documented confidence — it is not
# computed from the data.
# ---------------------------------------------------------------------------

def _rx(pattern: str) -> "re.Pattern[str]":
    return re.compile(pattern, re.IGNORECASE | re.MULTILINE)


_DATE_ISO = r"(\d{4}-\d{2}-\d{2})"
_DATE_US = r"(\d{1,2}/\d{1,2}/\d{4})"
# One capture group holding the whole long-form date: the transform
# receives group(1) and re-parses it, so the group must be the full date.
_DATE_LONG = rf"((?:{_MONTH_NAMES})\s+\d{{1,2}},\s+\d{{4}})"


def _date_rules(label: str) -> list[tuple]:
    """ISO / US / long-form date rules for a given label, in that order."""
    return [
        ("date_iso", _rx(rf"^{label}\s*:\s*{_DATE_ISO}"), Decimal("0.95"), "date_iso"),
        ("date_us", _rx(rf"^{label}\s*:\s*{_DATE_US}"), Decimal("0.85"), "date_us"),
        ("date_long", _rx(rf"^{label}\s*:\s*{_DATE_LONG}"), Decimal("0.80"), "date_long"),
    ]


_TOTAL_RULES: list[tuple] = [
    ("total_strict", _rx(r"^total\s*[:\s]+\$?([\d,]+\.\d{2})"), Decimal("0.95"), "money"),
    ("total_due", _rx(r"amount\s*due\s*[:\s]+\$?([\d,]+\.\d{2})"), Decimal("0.85"), "money"),
    ("total_largest", "LARGEST_AMOUNT", Decimal("0.70"), "money"),
]

# FIELD_SPECS[doc_type][field_name] = (kind, [rules]).
# kind drives correction-time validation in validate_corrected_value().
FIELD_SPECS: dict[str, dict[str, tuple[str, list[tuple]]]] = {
    "invoice": {
        "vendor": ("text", [
            ("vendor_labeled", _rx(r"^(?:vendor|from|bill\s+from)\s*:\s*(.+)$"),
             Decimal("0.90"), "text"),
            ("vendor_first_line", "FIRST_LINE_NAME", Decimal("0.60"), "text"),
        ]),
        "invoice_number": ("text", [
            ("invnum_labeled",
             _rx(r"^(?:invoice\s*(?:no\.?|#|number))\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9\-]{2,})"),
             Decimal("0.95"), "text"),
            ("invnum_bare", _rx(r"\b(INV[-\s]?\d{3,}(?:-\d+)?)\b"),
             Decimal("0.80"), "text"),
        ]),
        "invoice_date": ("date", _date_rules(r"(?:invoice\s*date|date)")),
        "due_date": ("date", _date_rules(r"due(?:\s*date)?")),
        "total_amount": ("money", _TOTAL_RULES),
    },
    "receipt": {
        "merchant": ("text", [
            ("merchant_labeled", _rx(r"^(?:merchant|store)\s*:\s*(.+)$"),
             Decimal("0.90"), "text"),
            ("merchant_first_line", "FIRST_LINE_NAME", Decimal("0.60"), "text"),
        ]),
        "receipt_date": ("date", _date_rules(r"date")),
        "total_amount": ("money", _TOTAL_RULES),
        "payment_method": ("enum", [
            ("payment_labeled",
             _rx(r"^payment(?:\s*method)?\s*:\s*([A-Za-z]+)"),
             Decimal("0.95"), "lower"),
        ]),
    },
    "contract": {
        "counterparty": ("text", [
            ("counterparty_labeled",
             _rx(r"^(?:counterparty|client|party)\s*:\s*(.+)$"),
             Decimal("0.90"), "text"),
            ("counterparty_first_line", "FIRST_LINE_NAME", Decimal("0.60"), "text"),
        ]),
        "contract_title": ("text", [
            ("title_labeled", _rx(r"^title\s*:\s*(.+)$"), Decimal("0.90"), "text"),
            ("title_contains", "FIRST_LINE_CONTAINS", Decimal("0.70"), "text"),
        ]),
        "effective_date": ("date", _date_rules(r"(?:effective\s*date|date)")),
        "term_months": ("int", [
            ("term_labeled", _rx(r"^term\s*:\s*(\d+)\s*months?"),
             Decimal("0.95"), "int"),
            ("term_bare", _rx(r"(\d+)\s*months?"), Decimal("0.80"), "int"),
        ]),
        "total_value": ("money", _TOTAL_RULES),
    },
}


def field_names(doc_type: str) -> list[str]:
    """Spec field names for a document type, in spec order."""
    if doc_type not in FIELD_SPECS:
        raise ValueError(f"unknown doc_type {doc_type!r}")
    return list(FIELD_SPECS[doc_type])


def field_kind(doc_type: str, field_name: str) -> str:
    if doc_type not in FIELD_SPECS or field_name not in FIELD_SPECS[doc_type]:
        raise ValueError(f"unknown field {field_name!r} for doc_type {doc_type!r}")
    return FIELD_SPECS[doc_type][field_name][0]


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

class ExtractedField:
    """One extracted field with full provenance."""

    def __init__(self, value: str, value_cents: Optional[int], confidence: Decimal,
                 rule_id: str, source_line: int, raw_text: str):
        self.value = value
        self.value_cents = value_cents
        self.confidence = confidence
        self.rule_id = rule_id
        self.source_line = source_line
        self.raw_text = raw_text

    def as_dict(self) -> dict:
        return {
            "value": self.value,
            "value_cents": self.value_cents,
            "confidence": str(self.confidence),
            "rule_id": self.rule_id,
            "source_line": self.source_line,
            "raw_text": self.raw_text,
        }


def _line_no(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _first_nonempty_line(text: str) -> tuple[str, int] | None:
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            return line.strip(), lineno
    return None


def _apply_rule(rule: tuple, text: str) -> tuple[str, Optional[int], int, str] | None:
    """Try one rule. Returns (value_text, value_cents, source_line, raw_text)
    or None when the rule does not fire (or its candidate fails to parse)."""
    rule_id, matcher, _confidence, transform_name = rule
    transform = _TRANSFORMS[transform_name]
    try:
        if matcher == "FIRST_LINE_NAME":
            found = _first_nonempty_line(text)
            if not found:
                return None
            line, lineno = found
            if not _NAME_LINE_RE.fullmatch(line):
                return None
            value, cents = transform(line)
            return value, cents, lineno, line
        if matcher == "FIRST_LINE_CONTAINS":
            for lineno, line in enumerate(text.splitlines(), start=1):
                if line.strip() and re.search(r"agreement|contract", line, re.IGNORECASE):
                    value, cents = transform(line.strip())
                    return value, cents, lineno, line.strip()
            return None
        if matcher == "LARGEST_AMOUNT":
            amounts = [
                (Decimal(m.group(1).replace(",", "")), m)
                for m in re.finditer(r"\$([\d,]+\.\d{2})", text)
            ]
            if not amounts:
                return None
            _amount, m = max(amounts, key=lambda pair: pair[0])
            value, cents = transform(m.group(1))
            return value, cents, _line_no(text, m.start()), m.group(0)
        m = matcher.search(text)
        if not m:
            return None
        value, cents = transform(m.group(1))
        return value, cents, _line_no(text, m.start()), m.group(0)
    except ValueError:
        # Candidate failed to parse (bad date, bad amount): the rule did
        # not fire; the extractor tries the next rule for this field.
        return None


def extract_fields(doc_type: str, text: str) -> dict[str, Optional[ExtractedField]]:
    """Extract every spec field for a document. Returns {field_name:
    ExtractedField | None} — None means no rule fired (field missing)."""
    if doc_type not in FIELD_SPECS:
        raise ValueError(f"unknown doc_type {doc_type!r}")
    result: dict[str, Optional[ExtractedField]] = {}
    for field_name, (_kind, rules) in FIELD_SPECS[doc_type].items():
        extracted: Optional[ExtractedField] = None
        for rule in rules:
            applied = _apply_rule(rule, text)
            if applied is None:
                continue
            value, cents, lineno, raw = applied
            extracted = ExtractedField(
                value=value,
                value_cents=cents,
                confidence=rule[2],
                rule_id=rule[0],
                source_line=lineno,
                raw_text=raw,
            )
            break
        result[field_name] = extracted
    return result


def document_confidence(extracted: dict[str, Optional[ExtractedField]]) -> Optional[Decimal]:
    """Weakest-link document confidence: the minimum field confidence over
    extracted fields. None when nothing was extracted."""
    confidences = [f.confidence for f in extracted.values() if f is not None]
    if not confidences:
        return None
    return min(confidences)


# ---------------------------------------------------------------------------
# Validation (deterministic rules over extracted fields)
# ---------------------------------------------------------------------------

def _as_date(value: Optional[str]) -> Optional[date]:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def validate_document(
    doc_type: str,
    extracted: dict[str, Optional[ExtractedField]],
    *,
    today: Optional[date] = None,
) -> list[dict]:
    """Run the per-type validation rules over extracted fields. Returns a
    list of {rule_id, field, message} failures. A rule that cannot be
    evaluated because its field is missing is skipped — the missing field
    already has its own exception."""
    failures: list[dict] = []

    def fail(rule_id: str, field: str, message: str) -> None:
        failures.append({"rule_id": rule_id, "field": field, "message": message})

    def money(field: str) -> Optional[Decimal]:
        f = extracted.get(field)
        if f is None or f.value_cents is None:
            return None
        return Decimal(f.value_cents) / 100

    def text(field: str) -> Optional[str]:
        f = extracted.get(field)
        return f.value if f is not None else None

    if doc_type == "invoice":
        total = money("total_amount")
        if total is not None and total <= 0:
            fail("amount_positive", "total_amount", "total_amount must be greater than zero.")
        issued = _as_date(text("invoice_date"))
        due = _as_date(text("due_date"))
        if issued and due and due < issued:
            fail("due_not_before_issued", "due_date",
                 "due_date must not be before invoice_date.")
        number = text("invoice_number")
        if number is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-]{2,}", number):
            fail("invoice_number_format", "invoice_number",
                 "invoice_number must be at least 3 alphanumeric/dash characters.")
    elif doc_type == "receipt":
        total = money("total_amount")
        if total is not None and total <= 0:
            fail("amount_positive", "total_amount", "total_amount must be greater than zero.")
        received = _as_date(text("receipt_date"))
        if received and today and received > today:
            fail("receipt_date_not_future", "receipt_date",
                 "receipt_date must not be in the future.")
        method = text("payment_method")
        if method is not None and method not in PAYMENT_METHODS:
            fail("payment_method_known", "payment_method",
                 f"payment_method must be one of {', '.join(PAYMENT_METHODS)}.")
    elif doc_type == "contract":
        term = text("term_months")
        if term is not None:
            try:
                if int(term) <= 0:
                    fail("term_positive", "term_months", "term_months must be greater than zero.")
            except ValueError:
                fail("term_positive", "term_months", "term_months must be a whole number.")
        value = money("total_value")
        if value is not None and value < 0:
            fail("value_non_negative", "total_value", "total_value must not be negative.")
    return failures


# ---------------------------------------------------------------------------
# Human corrections: validate a corrected value the way the extractor would
# have canonicalized it. Returns (value_text, value_cents) or raises
# ValueError. Money amounts go through Decimal; dates must be ISO.
# ---------------------------------------------------------------------------

def validate_corrected_value(
    doc_type: str, field_name: str, raw_value: Any
) -> tuple[str, Optional[int]]:
    kind = field_kind(doc_type, field_name)
    if raw_value is None or str(raw_value).strip() == "":
        raise ValueError(f"{field_name} must not be empty.")
    candidate = str(raw_value).strip()
    if kind == "money":
        cents = parse_amount_cents(candidate)
        return str(cents_to_decimal(cents)), cents
    if kind == "date":
        return date.fromisoformat(candidate).isoformat(), None
    if kind == "int":
        value = int(candidate)
        if value <= 0:
            raise ValueError(f"{field_name} must be a positive whole number.")
        return str(value), None
    if kind == "enum":
        value = candidate.lower()
        if value not in PAYMENT_METHODS:
            raise ValueError(
                f"{field_name} must be one of {', '.join(PAYMENT_METHODS)}.")
        return value, None
    return candidate, None
