# Q01 — Security Notes

Scope: a local demonstration application. This is a security-conscious
design for its scope — it is **not** a claim of compliance, certification,
or production readiness.

## Caller-ID sensitivity (the core of this project's threat model)

Caller IDs are personal data. The design treats them as toxic by default:

| Control | Implementation |
|---|---|
| Raw numbers never persisted | `mask_caller_id()` + `hash_caller_id()` run **before** the INSERT; no code path writes raw digits |
| Masked display | `••••••0142` — last 4 digits only, for the agent's callback list |
| Hash for dedup/repeat detection | SHA-256 of normalized digits; used only for the dedup key and repeat-caller counting |
| Verified by test | `test_raw_caller_id_never_stored` scans every text column of `missed_calls` and `call_events` for a fixture number and fails if found |
| No resale / no sharing | There is no export, webhook-out, or analytics path in v1; the data leaves the SQLite file only through the operator's own UI/API |
| Synthetic by construction | Every number in fixtures, tests, and demos is invented (fictional 555 range); the UI carries the "SYNTHETIC DEMO DATA" banner |

## Retention policy (recommended for real deployments)

v1 keeps call records indefinitely in the local SQLite file — acceptable
for a demo. A real deployment should define and enforce retention, e.g.:

- Missed-call records: 90 days, then purge (the recovery value decays fast).
- Audit events: 1 year for dispute handling, then purge.
- Provide a deletion path per caller on request.

These are **recommendations, not implemented features** — document the gap
before any real deployment.

## Other controls (shared with P01/P02)

| Threat | Control in place |
|---|---|
| Malformed / malicious input | Server-side validation (`normalize_event`); length caps; row-level CSV errors |
| Duplicate / replay abuse | Natural dedup key + idempotency keys with TTL |
| Information leakage via errors | Consistent error envelopes; generic 500; no tracebacks |
| SQL injection | Parameterized queries everywhere; CHECK constraint on `state` |
| Spoofed caller IDs gaming the queue | `repeat-id-anomaly` flag is informational only — never auto-trusts, never auto-drops |
| Fake data mistaken for real | "SYNTHETIC DEMO DATA" banner; 555 fixtures |

## TCPA and callback law — read before any real deployment

**No TCPA-compliance review has been performed on this project.**
Placing callbacks — especially automated ones — to missed callers is
regulated in the United States (Telephone Consumer Protection Act and
state analogues). Consent, calling-hour, do-not-call, and disclosure rules
apply and vary by situation. **Any real deployment must be reviewed by
telecom counsel before it places a single call.** This project
demonstrates record-keeping and prioritization, not a compliant dialing
system, and must never be presented as one.

## Deliberate demo-scope gaps (do not ship as-is)

1. **No authentication.** Claim/outcome actions are actor-labeled, not
   authenticated.
2. **Demo server.** `wsgiref` is single-process, demonstration only.
3. **No rate limiting** on the ingest endpoints.
4. **SQLite file permissions** rely on the host; WAL mode is enabled.
5. **No retention enforcement** (see policy note above).

## Dependency review

Runtime dependencies: **none** (Python 3.12 stdlib only). Dev dependency:
`pytest` in `.venv`. Nothing to audit, nothing to patch, nothing billed.
