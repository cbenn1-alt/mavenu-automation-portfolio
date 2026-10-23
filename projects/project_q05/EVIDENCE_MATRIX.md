# Q05 — Evidence Matrix

Every public claim in `README.md` mapped to a test, artifact, or labeled
estimate. Status vocabulary: `Implemented`, `Tested`, `Simulated`, `Demo`
(per portfolio conventions).

| README claim | Status | Evidence |
|---|---|---|
| Invoice + payment CSV ingest | Implemented, Tested | `reconcile.ingest_invoices` / `ingest_payments`; `tests/test_reconciliation.py` (ingest block, 7 tests); `POST /api/reconciliation/upload` |
| Schema validation with row-level errors | Implemented, Tested | `test_ingest_invoices_row_level_errors_do_not_abort_batch`, `test_ingest_missing_columns_is_fatal`; row numbers in error dicts |
| CSV-formula sanitization | Implemented, Tested | `reconcile.sanitize_cell`; `test_formula_cells_neutralized_in_db`, `test_formula_amount_rejected_as_row_error`, `test_payment_note_formula_sanitized`; SECURITY.md |
| Idempotent inserts on natural keys | Implemented, Tested | `test_ingest_reingest_is_idempotent`, `test_payments_reingest_idempotent` |
| Deterministic two-pass matching, every match explained | Implemented, Tested | `matching.run_match`; `recon_matches.explanation_json`; `test_fixture_known_pairs` (explanations asserted), `test_fixture_match_counts` |
| 100% precision on exact-pass fixtures | Tested | `test_exact_pass_precision_against_deceptive_fixture` (INV-01/INV-1 collision, nonexistent ref, case/whitespace normalization) |
| Fuzzy pass with documented threshold | Implemented, Tested | `MatchConfig` (0.75); `score_candidate` component breakdown; `test_score_candidate_components`, `test_decide_boundary` |
| Below-threshold candidates never silently auto-matched | Tested | `test_below_threshold_never_silently_automatched`, `test_all_below_threshold_candidates_routed_to_review` (5/5 → review, 0 match rows) |
| Exception queue (6 kinds) with suggested next action each | Implemented, Tested | `rebuild_exceptions` / `run_match`; `test_fixture_exception_queue_contents` (all 9 asserted + action non-empty) |
| Exception lifecycle `open → investigating → resolved \| written_off` | Implemented, Tested | `workflow.EXCEPTION_WORKFLOW`; 8-case parametrized illegal-transition matrix; `test_exception_legal_transitions`, `test_exception_written_off_path` |
| Actor-stamped history | Implemented, Tested | `recon_exception_events`; `test_exception_legal_transitions` (history asserted) |
| Partial-payment handling with balances | Implemented, Tested | `test_partial_payment_balance_and_action` (balance_cents 150000, action names $1,500.00) |
| Duplicate-payment protection, no double-counting | Implemented, Tested | `test_ingest_payments_happy_path` (exception raised), `test_within_batch_duplicate_not_double_counted` (coverage == single payment) |
| Re-ingest produces zero duplicate matches | Tested | `test_reingest_and_rematch_produces_zero_new_matches` |
| Reconciliation summary reconciles to source rows | Tested | `test_summary_matches_hand_computed_expectations`, `test_summary_reconciles_to_independent_raw_sql` (no service code), identity holds |
| Aging buckets sum to outstanding | Tested | `test_aging_buckets_match_hand_computed` (buckets + total == outstanding); `aging_report(now=)` |
| Exception aging | Implemented, Tested | `test_exception_aging_buckets`, `test_exception_aging_with_old_exceptions` (83-day-old exceptions) |
| Decimal-only money math | Tested | `test_amounts_parse_via_decimal` (`0.29`→29c), `test_cents_to_decimal_never_float`, `test_summary_money_values_are_decimal` |
| Web UI + JSON API | Implemented, Tested | `/project_q05*` pages, `/api/reconciliation*`; `tests/test_reconciliation_api.py` (11 tests) |
| Migration rollback tested | Implemented, Tested | `008_reconciliation.down.sql`; `test_migration_008_down_step_rolls_back_for_real` (run 2026-10-23) |
| All financial data synthetic | Demo | fictional fixtures; SYNTHETIC DEMO DATA banner; honest-status table |
| Fuzzy weights are a formula, not a model | Simulated (labeled) | README "What is simulated"; `matching.py` module docstring |
| No production deployment / no real users | — (not claimed) | Honest-status banner; no such claim anywhere |
| Not a substitute for accounting controls or an audit | — (explicitly not claimed) | README banner; SECURITY.md "Accounting integrity" section |
| Write-offs need human authorization; system proposes, never posts | Implemented (policy), Tested (mechanism) | `written_off` reachable only via explicit transition; suggested actions are text only |
| Baseline regression-free | Tested | Full suite `693 passed` 2026-10-23 (TEST_RESULTS.md) |

## Hand-computed fixture arithmetic (verifiable by hand)

- Invoiced: 1200.00+850.00+2500.00+400.00+975.50+1100.00+600.00+300.00 = **7925.50**
- Paid: 1200.00+850.00+1000.00+975.50+400.00+300.00+612.34+1200.00+250.00+500.00 = **7287.84**
  (11th CSV row is the skipped PAY-0010 duplicate)
- Matched payments: 1200.00+850.00+1000.00+975.50+400.00+1200.00+500.00 = **6125.50**
- Identity: 3000.00 − 1200.00 = 7925.50 − 6125.50 = **1800.00** ✓

## Claim-grade summary

- **Verified on the custom stack:** ingest + validation + CSV sanitization, idempotent natural keys, exact-pass precision, fuzzy threshold with zero silent auto-matches, duplicate protection, partial/overpaid handling, state-machine exceptions with actor history, summary/aging/exception-aging reconciliation, migration rollback, Decimal-only money.
- **Simulated, labeled:** the fixture datasets, the fuzzy scoring weights (a formula, not a model), the operator actor (form field, not auth).
- **Not demonstrated:** real accounting integration, GL posting, multi-currency/tax, authenticated multi-user access, concurrent ingest.
