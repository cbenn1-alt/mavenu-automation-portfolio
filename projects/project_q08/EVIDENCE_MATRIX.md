# Q08 — Evidence Matrix

Every public claim about this project, mapped to the test or artifact
that backs it. Labels: **Implemented** (code exists), **Tested**
(automated test passes), **Simulated** (stubbed/fixture behavior),
**Demo** (illustrative only). "Labeled estimate" marks numbers that
describe the fixture, not the real world.

| # | Claim | Label | Evidence |
|---|---|---|---|
| 1 | Ingests review events (JSON + CSV) with validation | Implemented, Tested | `tests/test_reviews.py::test_ingest_event_stores_and_tags`, `test_ingest_csv_stats_and_skips`, `test_normalize_event_*` (3 tests) |
| 2 | Idempotent on natural key `(source, external_id)` | Implemented, Tested | `test_ingest_idempotent_on_natural_key`; `tests/test_reviews_api.py::test_api_ingest` (duplicate re-post) |
| 3 | Lexicon-based sentiment + topic tagging (service, price, punctuality, workmanship) — NOT an ML model | Implemented, Tested | `tests/test_tagger.py` (19 tests); `LexiconTagger` docstring states not-a-model; `test_tagger_is_honestly_labeled_not_ml` |
| 4 | Sentiment P=1.000/R=1.000 (pos & neg); topics P 0.791–0.935 / R 0.829–1.000 | Tested (labeled estimate) | `test_sentiment_precision_recall_positive/negative`, `test_topic_precision_recall[4]`; numbers describe the 200-row synthetic fixture only |
| 5 | Lexicons versioned and inspectable | Implemented, Tested | `test_lexicon_seeding_and_inspection`, `test_tagger_rebuilt_from_db_matches_code_tagger`, `GET /api/reviews/lexicons/1.0` (`test_api_lexicon_inspectable`) |
| 6 | Tagger is deterministic | Implemented, Tested | `test_deterministic` |
| 7 | Negation scope handled ("not fair" → negative) | Implemented, Tested | `test_negation_flips_polarity` |
| 8 | Severity routing: 1★ critical / 2★ high / negative text → owner queue | Implemented, Tested | `test_route_decision_pure_function`, `test_critical_routing_recall_100_percent_on_fixture` (52/52) |
| 9 | Severity-routing recall 100% on critical fixtures | Tested | `test_critical_routing_recall_100_percent_on_fixture`; 200/200 fixture routing (`test_fixture_routing_matches_expectations`) |
| 10 | Default-to-alert: ambiguous/adversarial reviews reach a human queue, never auto-resolved | Implemented, Tested | `test_default_to_alert_on_uncertainty`, `test_sarcasm_reaches_owner_not_silenced`, `test_uncertain_flagged_on_weak_evidence` (60/60) |
| 11 | SLA timers UTC; breach → escalation recorded; frozen-clock tested | Implemented, Tested | `test_sla_due_is_utc_and_correct`, `test_sla_breach_escalates_on_frozen_clock`, `test_sla_check_idempotent` |
| 12 | Response drafts from templates; tones professional/warm/brief | Implemented, Tested | `test_generate_draft`, `test_templates_have_all_tones` |
| 13 | Templates contain no factual claims | Implemented, Tested | `test_templates_contain_no_factual_claims` (`template_sanity()`: no digits, no `$`, no promise-words) |
| 14 | Human-approval gate; **no send path exists** (no sent state, no send function, no send endpoint) | Implemented, Tested | `test_human_approval_gate`, `test_sent_state_is_unreachable`, `test_db_check_constraint_rejects_sent`, `test_api_has_no_send_path` |
| 15 | Audit trail of every state change | Implemented, Tested | `test_ingest_records_audit_events`, `review_events` table |
| 16 | Migration `011_reviews.sql` + tested rollback | Implemented, Tested | `test_migration_011_down_step_rolls_back_for_real` (2026-10-23) |
| 17 | Web pages + JSON API | Implemented, Tested | `tests/test_reviews_api.py` (14 tests): ingest/list/queues/SLA/drafts/approve/reject/lexicon + 4 pages |
| 18 | Tagger replaceable behind `ReviewTagger` protocol | Implemented, Tested | `test_protocol_replaceable`, `test_replaceable_tagger_protocol_drives_ingest` |
| 19 | All reviews synthetic; no real business identities; no platform scraping | Demo | Fixture header + migration header + README banner; `BANNER` on every page |

## What is NOT claimed (and where that is enforced)

- No production deployment, no real users, no real reviews — README
  honest-status banner; `not claimed` row in the matrix.
- No platform integrations — REQUIREMENTS.md out-of-scope; no platform
  code exists.
- No ML model — `tagger.py` module + class docstrings; claim #3.
- Responses never auto-post — claim #14 (four independent assertions).
- Performance numbers are fixture-labeled estimates, never real-world
  measurements — README + TEST_RESULTS.md disclaimers.
