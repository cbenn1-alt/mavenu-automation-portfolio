# Project P05 — Security

> **Status: Implemented + tested (Gate E ✓)** — synthetic/demo data only. No production deployment, no real clients, no bank approval.

## 1. Threat model

P05 is a local demo with no network exposure beyond the dev server, no real business data, and no real PII. Its realistic threats: SQL injection through the queue-depth probe's table/value parameters; a hostile check/runbook/rule payload smuggling code or oversized data; a caller forging state changes (ack an alert they did not own, resolve an incident with no note, replay a dead letter twice); silent or forged state changes with no audit trail; and — the sharpest one for an alerting demo — implying a notification was sent when nothing was ever sent. All are addressed below.

## 2. Controls

| Threat | Control | Evidence |
|---|---|---|
| SQL injection via queue-depth table / value | **Allow-list + parameterized SQL only.** The probe's table and column come only from `_QUEUE_TABLES`; the state value is bound as a `?` parameter. Unknown tables/values are rejected at check creation (validated eagerly, not at first run). There is no code path that interpolates caller-supplied text into SQL. | `test_check_validation_rejects_bad_inputs` (unknown table, unknown value), `test_create_check_api_and_validation` (API 422); live smoke test: table `"missed_calls; DROP TABLE leads"` → 422, tables intact |
| Second-statement smuggling | Same allow-list: `;` and whitespace tricks cannot survive the exact-match lookup. SQLite's `execute` also rejects multiple statements. | Same tests as above |
| Hostile payloads (oversized / wrong-shaped) | Names limited to 1–64 chars `[A-Za-z0-9 _-]`; subsystems/kinds/probes/severities/operators from fixed enums; policy fields range-checked (max attempts 1–10, base > 0, cap ≥ base, jitter ≥ 0, dead-letter ≥ 1); runbook steps limited to 1–20, each with a positive integer time box; payloads must be JSON objects; silence timestamps must be ISO and in the future | `test_check_validation_rejects_bad_inputs`, `test_policy_validation_and_supersede`, `test_rule_skips_missing_metric_and_rejects_bad_inputs`, `test_runbook_create_supersede_lookup` (empty steps, zero time box), `test_rule_validation_and_silence_api` (past silence) |
| Forged state changes | Every transition is enforced by a state machine: alerts via `ALERT_WORKFLOW` (resolved is terminal), incidents via `INCIDENT_WORKFLOW` (open → closed illegal, self-transitions illegal). Resolving an incident requires a resolution note. Terminal jobs cannot be attempted; replayed dead letters cannot be replayed again. | `test_alert_ack_and_resolve_transitions`, `test_incident_full_lifecycle`, `test_job_success_path` (attempt after success), `test_due_jobs_and_replay` (double replay), `test_incident_lifecycle_api` (resolve without note → 422, open → closed → 422) |
| Silent or forged state changes | Every create/supersede/run/fire/dedup/suppress/transition/note writes an audit row to `gov_events` with actor + timestamp; suppressed rule firings are logged too; incidents carry their own actor-stamped timeline in `gov_incident_events` | `test_seed_demo_data_is_idempotent` (events exist), `test_silenced_rule_does_not_fire_but_is_logged`, `test_incident_full_lifecycle` (timeline count) |
| Implied notification (alert "sent" when it was not) | **No send path exists in the module.** The `channel` column is always `log`; there is no email/webhook/SMS/pager call anywhere in `governance.py`. The docs, the module docstring, and the P05 pages all state alerts are recorded only. | Code review of `src/mavenu/governance.py` (no network, no `smtplib`, no `urllib`); `grep` shows no `send` function in the module |
| Secrets in code | None. No credentials, tokens, or keys anywhere in P05. The demo server binds localhost only. | Grep: no `password`, `token`, `secret`, `api_key` in `src/mavenu/governance.py` |

## 3. What P05 does NOT do (by design)

- No alert delivery — there is no endpoint, form, or parameter that sends a notification.
- No job execution — `attempt_job` records caller-reported outcomes; it runs no code, makes no HTTP call, and touches no external system.
- No writes to the operational tables — P05 reads `leads`, `missed_calls`, `estimates`, `docintel_documents` (queue probe only); it writes only its own eleven tables.
- No authentication/authorisation — the dev server is a single-user demo; do not expose it.
- No deletion of audit rows — events are append-only; the migration down-step drops whole tables, which is a rollback, not a redaction tool.
- No `SELECT *`, no dynamic table names, no string-built `WHERE` clauses — the one probe that builds SQL uses only allow-listed identifiers inside a fixed template.
