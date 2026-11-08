"""V15 reversible-reference normalization for synthetic timestamp, unit and locale inputs.

Architecture V4 p.42: V15 Normalize timestamps, units and locales.
Proof: Conversion reference tests.

This standalone test utility has no production integration or runtime effects.
No browser locale, system timezone, named-zone DST guess, currency exchange,
silent unit rounding, or mutation of V9-frozen fixture files is permitted.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

SUPPORTED_LOCALES = ("en-US", "en-GB", "de-DE", "fr-FR")
SUPPORTED_UNITS = ("hours", "minutes", "seconds")
ISO_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})$"
)
OFFSET_PATTERN = re.compile(r"^([+-])(\d{2}):(\d{2})$")
LOCAL_FORMATS = {
    "en-US": "%m/%d/%Y %H:%M:%S",
    "en-GB": "%d/%m/%Y %H:%M:%S",
    "de-DE": "%d.%m.%Y %H:%M:%S",
    "fr-FR": "%d/%m/%Y %H:%M:%S",
}
NUMERIC_PATTERNS = {
    "en-US": re.compile(r"^-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?$"),
    "en-GB": re.compile(r"^-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?$"),
    "de-DE": re.compile(r"^-?(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,\d+)?$"),
    "fr-FR": re.compile(r"^-?(?:\d+|\d{1,3}(?:[ \u00a0]\d{3})+)(?:,\d+)?$"),
}


class NormalizationRejected(ValueError):
    """A stable diagnostic category; no raw customer/source input is logged."""


def need(ok: Any, code: str) -> None:
    if not ok:
        raise NormalizationRejected(code)


def locale_check(locale: Any) -> str:
    need(type(locale) is str and locale in SUPPORTED_LOCALES, "unsupported_locale")
    return locale


def _fixed_offset(value: str) -> timezone:
    match = OFFSET_PATTERN.fullmatch(value)
    need(match is not None, "invalid_timezone_offset")
    sign, hh, mm = match.groups()
    hours, minutes = int(hh), int(mm)
    need(hours <= 14 and minutes <= 59 and
         not (hours == 14 and minutes != 0), "invalid_timezone_offset")
    offset = timedelta(hours=hours, minutes=minutes)
    if sign == "-":
        offset = -offset
    return timezone(offset)


def normalize_timestamp(value: Any, locale: Any, utc_offset: Any = None) -> str:
    """Convert explicit ISO offset or locale + numeric offset to canonical UTC."""
    loc = locale_check(locale)
    need(type(value) is str, "invalid_timestamp")
    match = ISO_PATTERN.fullmatch(value)
    if match is not None:
        need(utc_offset is None, "conflicting_timezone_offset")
        suffix = match.group(1)
        tz = timezone.utc if suffix == "Z" else _fixed_offset(suffix)
        raw_time = value[:-len(suffix)]
        try:
            naive = datetime.strptime(raw_time, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            raise NormalizationRejected("invalid_timestamp") from None
    else:
        need(utc_offset is not None, "missing_timezone_offset")
        need(type(utc_offset) is str, "invalid_timezone_offset")
        tz = _fixed_offset(utc_offset)
        try:
            naive = datetime.strptime(value, LOCAL_FORMATS[loc])
        except ValueError:
            raise NormalizationRejected("invalid_timestamp") from None
        need(naive.strftime(LOCAL_FORMATS[loc]) == value, "invalid_timestamp")
    try:
        normalized = naive.replace(tzinfo=tz).astimezone(timezone.utc)
    except (OverflowError, ValueError):
        raise NormalizationRejected("invalid_timestamp") from None
    return normalized.strftime("%Y-%m-%dT%H:%M:%SZ")


def _decimal(value: Any, locale: Any) -> Decimal:
    loc = locale_check(locale)
    need(type(value) is str and
         NUMERIC_PATTERNS[loc].fullmatch(value) is not None,
         "invalid_numeric_format")
    normalized = value
    if loc in ("en-US", "en-GB"):
        normalized = normalized.replace(",", "")
    elif loc == "de-DE":
        normalized = normalized.replace(".", "").replace(",", ".")
    else:
        normalized = normalized.replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        number = Decimal(normalized)
    except InvalidOperation:
        raise NormalizationRejected("invalid_numeric_format") from None
    need(number.is_finite(), "invalid_numeric_format")
    return number


def _decimal_plain(number: Decimal) -> str:
    normalized = format(number, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    if normalized == "-0":
        normalized = "0"
    return normalized


def normalize_duration(value: Any, unit: Any, locale: Any) -> str:
    """Normalize supported durations to up to six EXACT decimal hour places."""
    loc = locale_check(locale)
    need(type(unit) is str and unit in SUPPORTED_UNITS, "unsupported_unit")
    number = _decimal(value, loc)
    divisor = {"hours": Decimal(1), "minutes": Decimal(60),
               "seconds": Decimal(3600)}[unit]
    hours = number / divisor
    need(Decimal(0) <= hours <= Decimal(240), "duration_out_of_range")
    quantized = hours.quantize(Decimal("0.000001"))
    need(quantized == hours, "duration_precision_loss")
    return _decimal_plain(quantized)


def normalize_money(value: Any, currency: Any, locale: Any) -> str:
    """Format a supported USD amount with 2 exact decimal places; NO FX."""
    loc = locale_check(locale)
    need(currency == "USD" and type(currency) is str, "unsupported_currency")
    number = _decimal(value, loc)
    need(Decimal(0) <= number <= Decimal(1000000), "money_out_of_range")
    quantized = number.quantize(Decimal("0.01"))
    need(quantized == number, "money_precision_loss")
    return format(quantized, ".2f")


def convert_reference(item: dict[str, Any]) -> str:
    """Dispatch exact, fixed conversion types; no dynamic timezone guesses."""
    need(type(item) is dict, "invalid_reference_shape")
    kind = item.get("kind")
    if kind == "timestamp":
        return normalize_timestamp(item.get("value"), item.get("locale"),
                                   item.get("utc_offset"))
    if kind == "duration":
        return normalize_duration(item.get("value"), item.get("unit"),
                                  item.get("locale"))
    if kind == "money":
        return normalize_money(item.get("value"), item.get("currency"),
                               item.get("locale"))
    raise NormalizationRejected("unsupported_conversion_kind")
