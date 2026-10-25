# Q08 — Security

**Status:** Implemented · Tested (2026-10-23).

## Threat model (v1 demo scope)

Q08 is a local demo with no network ingress beyond the WSGI app, no
credentials, and no real data. The realistic threats are: injection via
review text, broken access assumptions if ever deployed, and accidental
exposure of anything that looks like PII.

## Controls in place

- **Parameterized SQL everywhere.** No string-interpolated SQL in
  `reviews.py`, `tagger.py`, or the Q08 web handlers. (Verified by
  inspection; the codebase convention is tested suite-wide.)
- **Validation at every boundary.** `normalize_event` rejects missing /
  overlong / mistyped fields with field-level errors; CSV ingest skips
  bad rows with row numbers; API handlers return 400/422 envelopes, never
  tracebacks.
- **No secrets.** There are no API keys, tokens, or credentials anywhere
  in Q08 — there is nothing to leak, because v1 integrates with no real
  platform.
- **Author names masked at rest.** `author_mask` stores "First L." form
  only; the full submitted name never reaches the database. (All fixture
  authors are fictional.)
- **HTML escaping.** All review text, titles, and author masks are
  `html.escape`d in page rendering.
- **Error handling.** The WSGI app catches `ValidationError` → 422 and
  unexpected exceptions → generic 500 (no internals leaked); Q08 service
  errors (`ReviewError`) → 422 JSON envelopes.
- **Audit trail.** Every state change (ingest, tag, route, resolve,
  draft, decision, SLA breach) writes an actor-stamped row to
  `review_events` plus a JSON stdout log line.

## The human-approval gate as a security property

The most consequential action in a reputation system is publishing a
response under a business's name. In v1 this is **architecturally
impossible**: no `sent` state, no send function, no send endpoint
(asserted by `test_sent_state_is_unreachable`,
`test_db_check_constraint_rejects_sent`, `test_api_has_no_send_path`).
A response can only leave the system when a human copies an approved
draft and posts it themselves, outside this system.

## Residual risks / real-deployment notes

- **No authentication.** The demo app has no login; do not expose it to
  the internet as-is. A real deployment needs auth on every mutating
  route (ingest, resolve, draft decide).
- **Real platform integrations** (Google/Facebook/Yelp) would introduce
  API credentials (→ Secure Vault / env vars, never code), webhook
  signature verification, and platform ToS compliance (reviews must be
  responded to per each platform's policies; never fabricate reviews —
  the fixture generator is demo-only and must not ship).
- **Rate limiting** on ingest endpoints before any public exposure.
- **Retention policy** for review text is not yet defined; define one
  before storing real customer words.
