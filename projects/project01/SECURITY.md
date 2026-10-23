# Project 01 — Security Notes

Scope: a local demonstration application. This is a security-conscious
design for its scope — it is **not** a claim of compliance, certification,
or production readiness.

## Threat model (demo scope)

| Threat | Control in place |
|---|---|
| Malformed / malicious input | All validation server-side (`validation.py`); client input never trusted; length caps on all fields |
| Double-submit / replay abuse | Idempotency keys; TTL expiry; keys are opaque client values, never executed |
| Information leakage via errors | Consistent error envelopes; generic 500 message; no tracebacks to clients |
| SQL injection | Parameterized queries everywhere; no string-interpolated SQL |
| Secret leakage | No secrets exist; config via env vars; `.env.example` documents the pattern with no values |
| Fake data mistaken for real | "SYNTHETIC DEMO DATA" banner on every page; fixtures use `example.com` |
| Silent data loss | Audit events committed immediately; booking failures recorded, lead preserved |

## Deliberate demo-scope gaps (do not ship as-is)

1. **No authentication.** Reviewer transitions are actor-labeled
   (`reviewer:<name>`) but not authenticated. A production system needs
   real identity and role-based access before exposing state changes.
2. **Demo server.** `wsgiref` is single-process and for demonstration only.
3. **No rate limiting** on the public intake form (abuse control would be
   needed before public deployment).
4. **SQLite file permissions** rely on the host; WAL mode is enabled.
5. **No PII handling story** — fine here because all data is synthetic by
   construction, but any real deployment needs retention, access-control,
   and deletion policies.

## Dependency review

Runtime dependencies: **none** (Python 3.12 stdlib only). Dev dependency:
`pytest` in `.venv`. Nothing to audit, nothing to patch, nothing billed.
