# V17 — Golden/reference calculations over fabricated maintenance records

**Controlled source:** Mavenu AI SaaS Platform Development Architecture V4, page 42.
**Increment objective:** Define golden/reference calculations.
**Required proof:** Expected-output fixtures.

**Status:** Technical reference candidate built only from authored synthetic V5 maintenance fixtures and V16 validated source lineage. V10's formal phase promotion remains BLOCKED/PENDING human sign-off; V11/V12 source approvals and independent domain adjudication are outstanding.

## Independent expected outputs and contract

The fixed fixture in fixtures/expected_outputs_v17.json supplies **25 expected output objects/values**: seven summary metrics, six per-asset aggregate objects and twelve case-history objects. It was precomputed and stored separately from the V17 Python computation; this supplies a reproducible regression oracle **but not independently verified industrial ground truth**.

| Synthetic summary metric | Expected |
|---|---:|
| Maintenance case examples | 12 |
| Invented equipment assets | 6 |
| Sum of fabricated downtime | 45.5 hours |
| Sum of illustrative repair cost | USD 12,735.00 |
| Median fictional case downtime | 3 hours |
| Cases without a SYN-EV reference ID | 1 |
| Later occurrences of existing synthetic asset IDs | 6 |

None of the above is an estimate of actual Minn-Dak operations, plant costs, unplanned outages, financial savings or expected reliability. Later synthetic asset occurrences are not modeled failure recurrence or prognostic equipment risk. A nonempty evidence_refs list does not authenticate underlying documentation.

## Calculation rules

scripts/calculations_v17.py computes all results using exact Decimal arithmetic from **V16 validated synthetic canonical case views**. Event ordering is canonical UTC timestamp ascending with a case-ID tie breaker. For each case it computes previous occurrences of the same fictional asset ID and whether fabricated evidence-reference identifiers are present. Per-asset summaries include case count, sum downtime, illustrative cost sum and missing-reference count. Median case duration uses the two middle values of the twelve-item sorted cohort.

Durations are ASCII decimal hours, and money is ASCII USD with two decimal places. There is no FX, money allocation, binary floating-point summation, rounding, uptime denominator, ROI, statistical significance, model validation, classification accuracy, or real industrial benchmark.

A successful comparator requires **exact matching values and record ordering** across all three expected-output sections. Changed definitions, added predictive/savings fields, incorrect record identities, extra asset records, or false approval fields fail closed.

## Verification and evidence

scripts/verify_v17.py rechecks the V10 frozen 18-file source, V11–V13 data constraints, V15 conversions and V16 lineage; recomputes synthetic golden arithmetic twice, checks V16 source fingerprints and original-file immutability, and writes:
- evidence/V17/golden_reference_report.json — provenance, result counts, digests, unsigned decision status.
- evidence/V17/expected_output_comparison.json — all computed synthetic values and exact comparison results.

tests/test_golden_v17.py adds **59 regression tests**, including seven metric-specific checks, six per-asset checks, twelve case-history checks and 34 integrity/negative/governance checks. Expected complete suite is **603** (544 inherited plus 59), subject to actual GitHub CI. Coverage floor stays at 84.5% combined source/branch percentage.

The expected-output fixture is authored for testing, not produced or signed by a customer reliability engineer. An independent reviewer must verify source meanings, appropriate cohort definitions, monetary accounting, downtime denominators and true event provenance before any use beyond fictional demonstrations. Formal V10/V11 approval dependencies are not bypassed.
