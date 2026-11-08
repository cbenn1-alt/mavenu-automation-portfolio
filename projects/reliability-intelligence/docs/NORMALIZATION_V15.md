# V15 — Normalize timestamps, units and locales

**Controlled source:** Mavenu AI SaaS Platform Development Architecture V4, page 42.
**Objective:** Normalize timestamps, units and locales.
**Required proof:** Conversion reference tests.

**Scope:** A synthetic-only engineering normalization utility. V10's formal Phase 02 promotion remains BLOCKED/PENDING human decision; V11 dictionary and V12 schema owner approvals are unsigned. The application runtime remains V9 / version 0.9.0 and API v1/schema 1.3.0.

## Normalization rules

| Field | Accepted sources | Canonical output | Explicit constraints |
|---|---|---|---|
| occurred_at_utc | ISO timestamps with Z or numeric offsets; locale-specific calendar timestamps with explicit numeric offset | YYYY-MM-DDTHH:MM:SSZ | UTC converted, seconds precision, no implicit server timezone or inferred DST |
| downtime_hours | numeric strings in hours, minutes, seconds; explicit locale | ASCII decimal hours, no more than six fractional digits | Exact conversion only; synthetic interval 0–240 hours |
| repair_cost_usd | USD numeric strings in en-US, en-GB, de-DE, fr-FR | ASCII USD string with exactly two decimal digits | Exact cents only; synthetic interval $0–$1,000,000; no FX |

Supported locale formatting is deliberately narrow: en-US uses month/day/year with comma group and decimal dot; en-GB uses day/month/year with comma group and decimal dot; de-DE uses day.month.year and dot group/decimal comma; fr-FR uses day/month/year and space/NBSP group/decimal comma. This is a fixed test vocabulary, not a complete internationalization service.

UTC offsets are mandatory unless the input ends in Z. The converter does NOT use the local computer's timezone, parse named timezones, infer DST rules, or guess a missing offset. A timestamp with a fixed numeric offset is not independently verified against a plant's historical timezone. Invalid calendar dates and offsets are rejected.

Conversion uses Python's standard-library Decimal type rather than binary floating-point arithmetic for money and units. Fractional seconds that cannot be represented to the documented six decimal *hour* places are rejected instead of being silently rounded. USD fractional cents are likewise rejected. This decision is a candidate test rule, not an approved accounting treatment. For production, consider storing integer elapsed microseconds and Decimal amounts with domain-approved precision.

## Reference evidence

The controlled fixture at fixtures/conversion_reference_v15.json defines **27 accepted references and 24 rejected references**. Each expected accepted canonical string is explicit; each rejected reference carries an expected fixed diagnostic category. Cases cover UTC offsets and date rollovers; US/UK/German/French date parsing; seconds/minutes/hours; decimal grouping and currency; invalid dates, ambiguous zones, precision loss, out-of-range values, malformed grouping and unsupported currencies.

scripts/normalize_v15.py implements pure in-memory conversion. scripts/verify_v15.py validates the fixture metadata, executes all 51 references, proves accepted canonical representations remain identical on replay, and checks **12 previously fabricated cases** without changing the original source. It writes ignored evidence/V15/conversion_reference_report.json.

tests/test_conversion_v15.py adds **81 tests** (51 reference-specific plus 30 governance/correctness controls), bringing the expected suite to **429 tests** from 348 V14 tests. Hosted GitHub CI is the authority for the observed result.

## Reviewer controls

A reviewer should inspect reference formats, rejected ambiguities, 12-case source immutability, and exact precision behavior. Human review must not assert true Minn-Dak field types, site timezone, actual downtime semantics, billing currency, exchange rates, production source rights, maintenance cost accounting or achieved ROI without separate verified evidence.

**No deployed conversion, live data ingestion, customer API, third-party I18N dependency, OT/CMMS write, or customer financial action.** Formal V10 and V11 approvals remain unfulfilled.
