# Project 02 — Evidence Matrix

Every public claim in `README.md` mapped to a test, artifact, or labeled
estimate. Status vocabulary: `Implemented`, `Tested`, `Simulated`, `Demo`
(per portfolio conventions §5.1).

| README claim | Status | Evidence |
|---|---|---|
| HTML intake form + JSON API (`POST /api/requests`) | Implemented, Tested | `src/mavenu/web.py` (`p02_form_page`, `api_create_request`); `tests/test_requests_api.py` (intake + HTML tests) |
| Server-side validation (type, amount, cost center, justification, requester identity) | Implemented, Tested | `requests_approval.validate_request_payload`; `tests/test_request_validation.py` (19 tests) |
| Idempotency-key duplicate protection; replays return original response | Implemented, Tested | `request_idempotency_keys` table; `submit_request()`; `test_idempotency_key_replays_without_duplicate`, API replay test |
| Approval routing: manager always; finance above threshold | Implemented, Tested | `approval_chain_for()`; threshold/env `MAVENU_FINANCE_THRESHOLD_CENTS`; routing tests |
| Role enforcement on decisions | Implemented, Tested | `record_decision()` raises `ApprovalRoleError`; `test_wrong_role_cannot_decide`, API 409 test |
| State machine enforced in code; illegal transitions raise | Implemented, Tested | `workflow.REQUEST_WORKFLOW`; `tests/test_approval_workflow.py` (33 tests) |
| Deterministic SLA-breach escalation to director | Implemented, Tested | `sweep_sla()` with injectable clock; 5 escalation tests incl. `test_sla_breach_escalates_to_director`; `POST /api/requests/sla-sweep` |
| Actor-stamped audit trail (DB row + JSON log line per transition) | Implemented, Tested | `request_events` table; `record_request_event()`; `test_every_transition_is_actor_stamped`, `test_escalation_is_in_the_audit_trail` |
| SQLite persistence | Implemented | `migrations/002_approvals.sql`; `db.get_connection`/`run_migrations` |
| DB-computed dashboard; totals reconcile | Implemented, Tested | `request_stats()`; `/project02/dashboard`; `test_dashboard_stats_reconcile_with_source_rows` (independent SQL re-computation) |
| Migration rollback tested | Implemented, Tested | `002_approvals.down.sql`; `db.rollback_migration()`; `test_migration_down_step_rolls_back_002` (run 2026-10-23) |
| Intake → approval → store → SQL chain | Simulated | REQUIREMENTS.md §6 simulation mapping; custom Python stack, not Power Platform/SharePoint/UiPath |
| Approver identity | Simulated (asserted, not authenticated) | SECURITY.md gap #1; actor labels in tests |
| All data synthetic | Demo | Fixtures use `example.com`, invented names/cost centers; SYNTHETIC DEMO DATA banner |
| No production deployment; no bank/platform endorsement | — (not claimed) | Honest-status banner in README; no such claim anywhere in code or docs |
| P01 regression-free (51/51) | Tested | Full suite `152 passed` 2026-10-23 (TEST_RESULTS.md) |

## Claim-grade summary

- **Verified on the custom stack:** workflow automation (state machine,
  approval routing, SLA escalation), SQL (schema, migrations, parameterized
  queries, reconciliation), testing & documentation discipline.
- **Transferable, not platform proof:** the approval-flow concepts map to
  Power Automate / SharePoint patterns, but no Microsoft platform was used
  — graded accordingly and never claimed otherwise.
- **Not demonstrated:** authenticated approver identity, scheduled sweep
  execution, notifications, delegation.
