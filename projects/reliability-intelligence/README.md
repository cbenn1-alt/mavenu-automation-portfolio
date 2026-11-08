# Mavenu Reliability Intelligence — V7

**Engineering state:** Local-only, read-only, synthetic maintenance workflow prototype with *structured failure diagnostics and verified negative paths*. No Minn-Dak access, customer authorization, operating system integration, real human approval, real risk prediction, or realized financial benefit is represented.

## Controlled V1–V7 increments

| Increment | Exact objective | Evidence / dependency |
|---|---|---|
| V1 | Initialize repo, CI, environment and architecture log | Local package and Git history separate from this portfolio repository |
| V2 | Define user, pain point and measurable outcome | Unapproved candidate product charter; owner approval required |
| V3 | Minimal UI/navigation | Five-page prototype; owner acceptance pending |
| V4 | Versioned API/service boundaries | Read-only v1 contract tests; owner acceptance pending |
| V5 | Representative synthetic fixtures | 6 invented assets/12 fabricated records and provenance; owner acceptance pending |
| V6 | End-to-end business workflow | Deterministic scripted review rehearsal and in-memory trace; owner acceptance pending |
| **V7** | **Structured failures and diagnostic logs** | **Allowlisted JSON-line logs, sanitized HTTP/CLI failure handling and negative-path verification** |

Source: Mavenu AI SaaS Platform Development Architecture V4, p.42.
V8: initial unit and smoke regression baseline. G1/V30 and G2/V60 are not passed.

## Python 3.11+ local quick start (stdlib only)

~~~~bash
cd projects/reliability-intelligence
PYTHONPATH=src python -m reliability_intelligence validate --json
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m reliability_intelligence diagnose --json
PYTHONPATH=src python -m reliability_intelligence demo --json
PYTHONPATH=src python -m reliability_intelligence serve --port 8765
~~~~

Open http://127.0.0.1:8765/ on the same computer. Binding is 127.0.0.1 only; do not expose the prototype to the internet.

UI routes remain /, /workbench, /workflow, /evaluation and /governance. API GET/HEAD paths remain /api/v1/status, /api/v1/scope, /api/v1/cases, /api/v1/demo and /api/v1/contract. The additive API schema version is **1.3.0**; no write routes exist.

## V7 diagnostic boundary

- A fixed catalog of error codes covers missing routes, unsupported methods, malformed charter, invalid fixture, contract faults, stylesheet failures and unexpected runtime failures.
- A failure produces one allowlist-only JSON diagnostic through Python logging (normally process stderr). It includes code, severity, stage, response/exit status, synthetic-only markers and a **stable diagnostic category fingerprint**.
- The fingerprint is deterministic **for error category**, not unique per occurrence, not a trace ID, and not a cryptographic signature.
- HTTP errors carry X-Diagnostic-Code and X-Diagnostic-ID response headers; existing safe API error envelopes/status codes remain compatible. Unexpected failures return sanitized 500, never raw exception details.
- Request URLs/queries/headers, payload contents, stack traces, exception messages, customer information, and secrets are **not logged by the V7 diagnostic module**. The WSGI server's existing access-log behavior is not covered by this module and requires separate security review before any broader deployment.
- No log file, database, queue, external observability service, incident dashboard, alert routing or durable audit history is implemented.
- The diagnose CLI emits six fixed **simulated failure examples**, not genuine incidents and not a recorded test-run audit.

See docs/DIAGNOSTICS_V7.md and docs/DEMO_V7.md for the event schema, redaction boundary, failure reproduction and acceptance procedure.

## Test coverage and readiness

Tests cover prior V2–V6 requirements, UI, API, fixtures and workflow, plus V7 negative paths, sanitization and diagnostic schemas. Check the exact GitHub Actions log before asserting successful CI.

V7 remains an engineering candidate until a named reviewer completes the negative-path reproduction and a responsible product/technical owner signs its decision. Original V1 Git history remains separate and V2–V6 human approvals are unresolved. No customer data, CMMS/ERP/PLC/SCADA/OT writes, trained AI, real approvals, actual operational outcomes or ROI are present.
