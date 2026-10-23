# Q02 — Security Notes

Scope: a local demonstration application. This is a security-conscious
design for its scope — it is **not** a claim of compliance, certification,
or production readiness.

## The core design decision: v1 cannot send anything

The outbox is a database table, not a mail queue. The only `MessageAdapter`
implementation is `StubMessageAdapter`, whose `send()` builds a dict and
touches no network. There is deliberately **no code path** from an outbox
row to any socket, SMTP library, or HTTP client. A future real adapter
would be a new, reviewed module — and before it sends a single message,
the deployment needs the legal review below.

| Threat | Control in place |
|---|---|
| Malformed / malicious input | Server-side validation (`normalize_estimate`, `create_template`, `replace_rules`); length caps; closed decline-reason and service-type sets |
| Duplicate / replay abuse | Client idempotency keys (TTL 72h) on estimate creation; UNIQUE natural idempotency keys on outbox rows |
| Information leakage via errors | Consistent error envelopes; generic 500; no tracebacks |
| SQL injection | Parameterized queries everywhere; CHECK constraints on `state` and outbox `status` |
| Double-sending follow-ups | UNIQUE `idempotency_key` + `ON CONFLICT DO NOTHING`; one `send_log` row per outbox row |
| Template with wrong variables | Render-time validation; `test_send` fixture gate; fail-closed scheduler skip |
| Fake data mistaken for real | "SYNTHETIC DEMO DATA" banner; fictional customer names; "(demo message; nothing was sent)" template footers |
| Estimate tampering via ad-hoc SQL | CHECK constraint on `state` mirrors the code state machine |

## CAN-SPAM / TCPA — read before any real deployment

**No CAN-SPAM/TCPA-compliance review has been performed on this project.**
Sending follow-up messages — by email or SMS — to estimate recipients is
regulated in the United States (CAN-SPAM Act, Telephone Consumer
Protection Act, and state analogues). Consent, opt-out handling,
sender identification, and calling/texting-hour rules apply and vary by
channel and situation. The `unsubscribed` flag and stop rules in this
project are *data-model* support for opt-out handling, not a compliance
program. **Any real deployment must be reviewed by counsel before it
sends a single message.** This project must never be described as
compliant.

## Template honesty

Templates must never misrepresent pricing or availability. The seeded
templates render the estimate's actual stored amount and carry an honest
demo footer. The version-pinning on outbox rows (`template_version`)
means any message can be traced to the exact copy that produced it —
useful in a dispute, not a substitute for legal review.

## Data sensitivity

v1 stores no real personal data by construction: customer names are
invented fixtures, recipient labels are synthetic
(`synthetic-customer:EST-000001`), and there is no email/phone column at
all. A real deployment adding contact details would need to treat them
as personal data (encryption at rest, access control, retention policy,
deletion path) — none of which exists here, by design, for a demo.

## Retention policy (recommended for real deployments)

v1 keeps estimate records indefinitely in the local SQLite file —
acceptable for a demo. A real deployment should define and enforce
retention, e.g.:

- Estimates and outbox rows: 2 years, then purge (or per contract).
- Audit events: per legal hold / dispute needs, then purge.
- Provide a deletion path per customer on request.

These are **recommendations, not implemented features** — document the
gap before any real deployment.

## Other controls (shared with P01/P02/Q01)

Parameterized SQL, validation at every boundary, actor-stamped audit
trail, idempotency keys with TTL, no secrets in code (there are no
secrets in this project; config arrives via environment variables per
`config.py`).
