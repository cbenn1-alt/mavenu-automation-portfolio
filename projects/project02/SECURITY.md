# Project 02 — Security Notes

Scope: a local demonstration application. This is a security-conscious
design for its scope — it is **not** a claim of compliance, certification,
or production readiness.

## Threat model (demo scope)

| Threat | Control in place |
|---|---|
| Malformed / malicious input | All validation server-side (`validate_request_payload`); client input never trusted; length caps on all fields; amount parsed defensively (NaN/inf rejected, $10M cap) |
| Double-submit / replay abuse | Idempotency keys with TTL; keys are opaque client values, never executed |
| Unauthorized state changes | Role enforcement in code (`ApprovalRoleError`); state machine rejects illegal transitions (`InvalidTransition`) |
| Information leakage via errors | Consistent error envelopes; generic 500 message; no tracebacks to clients |
| SQL injection | Parameterized queries everywhere; no string-interpolated SQL |
| Fake data mistaken for real | "SYNTHETIC DEMO DATA" banner on every page; fixtures use `example.com` and invented cost centers |
| Silent data loss | Audit events committed immediately; every transition is a DB row + log line |
| Stuck approvals / silent SLA slip | `sla_due_at` on every pending step; `sweep_sla()` escalates; `sla_breached` surfaced on the dashboard |
| Secret leakage | No secrets exist; config via env vars; `.env.example` documents the pattern with no values |

## Deliberate demo-scope gaps (do not ship as-is)

1. **No authentication.** Approver actions are actor-labeled
   (`reviewer:mara` asserting role `manager`) but not authenticated. A
   production system needs real identity (e.g. SSO) and role-based access
   before exposing decisions. Role *enforcement* is tested; role
   *identity* is asserted.
2. **Demo server.** `wsgiref` is single-process and for demonstration only.
3. **No rate limiting** on the public intake form or API.
4. **SQLite file permissions** rely on the host; WAL mode is enabled.
5. **No PII handling story** — fine here because all data is synthetic by
   construction, but any real deployment needs retention, access-control,
   and deletion policies.
6. **Sweep is triggerable, not scheduled.** Until a scheduler calls
   `POST /api/requests/sla-sweep`, escalation depends on an operator or
   cron. A missed sweep means a missed escalation — monitor it.
7. **No approver notifications.** Escalation reroutes the request, but
   nobody is paged. A real deployment needs the notification step.

## Dependency review

Runtime dependencies: **none** (Python 3.12 stdlib only). Dev dependency:
`pytest` in `.venv`. Nothing to audit, nothing to patch, nothing billed.

## Abuse scenarios considered

- **Approver impersonation:** mitigated in the demo by the audit trail
  (actor labels make impersonation visible, not impossible) — real
  deployments must authenticate.
- **Amount tampering after submission:** amounts are immutable after
  creation in this slice; resubmission re-derives the chain from the stored
  amount.
- **Idempotency-key fixation:** keys are client-chosen; a colliding key
  replays the *original* response (safe) rather than overwriting.
- **SLA clock tampering:** the sweep compares stored ISO deadlines; the
  HTTP sweep uses server time, not client time.
