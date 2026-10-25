# Q06 — Evidence Matrix

Every public claim in `README.md` mapped to a test, artifact, or labeled
estimate. Status vocabulary: `Implemented`, `Tested`, `Simulated`, `Demo`
(per portfolio conventions).

| README claim | Status | Evidence |
|---|---|---|
| Multi-source CSV ingest | Implemented, Tested | `entity_resolution.ingest_source`; `tests/test_entity_resolution.py` (ingest block, 6 tests); `POST /api/entity-resolution/sources/upload` |
| Header validation, row-level errors | Implemented, Tested | `test_ingest_missing_columns_is_fatal`, `test_ingest_row_errors_do_not_abort_batch` (1-based row numbers) |
| CSV-formula sanitization | Implemented, Tested | `normalize.sanitize_cell`; `test_ingest_sanitizes_formula_cells`; SECURITY.md |
| Idempotent inserts on (source, row) | Implemented, Tested | `test_ingest_reingest_is_idempotent` |
| Deterministic idempotent normalizers | Implemented, Tested | `normalize.py`; 9 case tests + 63 parametrized idempotency tests (`f(f(x)) == f(x)`) |
| Blocking on phone/email/ZIP+surname | Implemented, Tested | `entity_resolution.build_blocks`, `block_keys_for`; `test_block_keys_for_shapes` |
| No O(n²) scan | Implemented, Tested | `generate_pairs` (block co-occurrence only, no all-pairs fallback); `test_pair_count_bounded_no_o2_fallback` (24 vs 1,431 possible); `test_every_pair_shares_a_block` |
| Block coverage on fixtures | Tested | `test_block_coverage_on_planted_duplicates` — 20/20 |
| Weighted scorer, documented weights | Implemented, Tested | `DeterministicDemoScorer`, `WEIGHTS` (sum 1.00); `test_scorer_weights_documented_and_sum_to_one` |
| Scorer behind replaceable protocol | Implemented, Tested | `PairScorer` protocol; `test_scorer_is_replaceable_protocol` (custom scorer drives `run_resolution`) |
| Documented thresholds, three bands | Implemented, Tested | `MATCH_THRESHOLD` 0.85 / `REVIEW_THRESHOLD` 0.60; `test_decide_boundaries` |
| Suffix-conflict penalty | Implemented, Tested | `SUFFIX_CONFLICT_PENALTY` −0.20; `test_suffix_conflict_penalty_applies` (0.90→0.70, match→review) |
| Match → proposal, never auto-confirm | Implemented, Tested | `run_resolution` creates only `proposed`; `test_run_never_confirms_merges` (0 non-proposed + signature-introspection guard) |
| Human confirmation required | Implemented, Tested | `confirm_merge` rejects blank/`system`/cased variants; `test_confirm_merge_requires_human_actor`; API test asserts 409 for `system` |
| Per-field provenance | Implemented, Tested | `field_plan_json`/`field_provenance_json`; `test_field_plan_provenance_shape`, `test_confirm_merge_applies_field_plan_with_provenance` |
| Full before/after audit | Implemented, Tested | `er_merge_audit` pre-images; `test_confirm_merge_applies_field_plan_with_provenance`; `GET /api/entity-resolution/proposals/<id>/audit` |
| Exact merge reversibility | Tested | `test_reverse_merge_restores_exact_preimage` (full row-dict equality, both records); reverse guards tested |
| Reject changes nothing | Tested | `test_reject_proposal_changes_nothing` (row-dicts byte-identical, no audit row) |
| No-match pairs never proposed | Implemented, Tested | `_create_proposal` raises on no-match; `test_propose_merge_no_match_pair_rejected` |
| Human propose path for review pairs | Implemented, Tested | `propose_merge`; `test_propose_merge_human_path_for_review_pair` (+ API test) |
| Recall 1.000 / precision 1.000 at 0.85 | Tested (measured) | `test_precision_recall_on_fixtures` — 20/20 planted dups matched; 20/20 match-band pairs true; printed + recorded in TEST_RESULTS.md |
| Adversarial fixtures | Tested | twins→review (+no auto-proposal), Jr/Sr→review, shared phone→no-match, household→review, similar names→no-match; `test_no_automatic_proposals_outside_match_band` |
| Append-only audit trail | Implemented, Tested | `er_events`; `test_proposal_events_audit_trail` (proposed/confirmed/reversed all present after reversal) |
| Pipeline idempotency | Tested | `test_run_resolution_idempotent` (0/0/0 on re-run); `test_normalize_all_idempotent` |
| Web UI + JSON API | Implemented, Tested | `/project_q06*` pages, `/api/entity-resolution*`; `tests/test_entity_resolution_api.py` (12 tests) |
| Migration rollback tested | Implemented, Tested | `009_entity_resolution.down.sql`; `test_migration_009_down_step_rolls_back_for_real` (run 2026-10-23) |
| All contact data synthetic | Demo | invented fixtures; SYNTHETIC DEMO DATA banner; honest-status table |
| Scorer is a formula, not a model | Simulated (labeled) | README "What is simulated"; `entity_resolution.py` module docstring |
| No production deployment / no real users | — (not claimed) | Honest-status banner; no such claim anywhere |
| Never auto-merges below high-confidence threshold | Implemented (structural), Tested | no auto-confirm code path; human-actor gate; threshold-independent gate (ARCHITECTURE.md) |
| Baseline regression-free | Tested | Full suite `827 passed` 2026-10-23 (TEST_RESULTS.md) |

## Fixture band ledger (measured 2026-10-23, verifiable by re-running)

- Match (20, scores 0.85–1.00): all 20 planted duplicates.
- Review (3): twins 0.75, Jr/Sr 0.70, household 0.72.
- No-match (1): shared phone 0.49.
- Pairs: 24 candidate vs 1,431 possible (98.3% reduction).
- Block coverage: 20/20 planted pairs share ≥1 block.

## Claim-grade summary

- **Verified on the custom stack:** ingest + validation + formula
  sanitization, idempotent natural keys, idempotent normalizers,
  blocking correctness + coverage, bounded pair generation, weighted
  scoring with documented thresholds, banding, the human merge gate
  (propose/confirm/reject/reverse), per-field provenance, exact merge
  reversibility, append-only audit, migration rollback, API + pages.
- **Simulated, labeled:** the fixture contact lists, the scoring weights
  (a formula, not a model), the reviewer actor (form field, not auth).
- **Not demonstrated:** real-PII handling (hashing documented, not
  implemented), phonetic/learned matchers, load at scale, concurrent
  writers, authenticated multi-user access.
