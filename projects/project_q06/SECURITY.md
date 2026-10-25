# Q06 — Security

## Data classification: synthetic only

Every contact in this project is invented. Names (`Marcus Bell`,
`Emma Carter`, …), phone numbers (`(701) 555-01xx`), emails
(`…@example.com`), and addresses are fictional fixtures. No real personal
data exists in code, tests, fixtures, or docs. The web UI carries the
`SYNTHETIC DEMO DATA` banner on every page.

**Rule: never load real contact lists into this demo.** The service is
built to demonstrate the *method* (normalize → block → score → human-gated
merge), not to process real PII.

## What's stored, and why it's safe here

- Raw CSV text is stored as ingested (formula-sanitized), plus derived
  normalized columns (`name_key`, `phone_digits`, …) in the clear.
- This is acceptable **only** because the data is synthetic. Storing
  normalized PII in the clear is exactly what a real deployment must not
  do (see below).

## Hashing strategy for real deployments (documented, not implemented)

If this design were ever pointed at real contact data, the blocking keys
must be keyed hashes, not plaintext:

1. **Blocking keys → HMAC-SHA256** with a server-side secret (`hmac`,
   stdlib): `phone:<hmac(digits)>`, `email:<hmac(lower)>`,
   `zipname:<zip>:<hmac(surname)>`. Equality blocking works identically on
   deterministic hashes; raw digits/emails never become index keys.
2. **Raw values → encrypted at rest** (or tokenized); the demo's plaintext
   `raw_*` columns are the first thing to change.
3. **Score explanations** must not echo full PII into logs — log pair ids
   and component names, not values. (This demo's stdout logs already
   avoid contact details.)
4. **Secret management:** the HMAC secret lives in the environment /
   secret store, never in code, never in the repo. Rotation procedure and
   re-keying of blocks must be documented before any real ingest.
5. **Retention & consent:** real deployments need a documented retention
   policy, a deletion path (right-to-erasure must cascade through
   contacts, blocks, pairs, proposals, and audit rows — with legal-hold
   exceptions reviewed by counsel), and a consent basis for matching.

None of the above is implemented in this build — implementing it against
real data without those controls would be the actual security failure.

## Merge reversibility as a safety property

A false merge is a data-destruction event. This project treats
reversibility as a safety control, not a convenience:

- Every confirmed merge stores **full pre-merge row images** of winner
  and loser (`er_merge_audit`), immutable once written.
- `reverse_merge` restores both rows exactly (tested with full row-dict
  equality) and stamps — never deletes — the audit row.
- The proposal state machine (`proposed → confirmed | rejected`,
  `confirmed → reversed`) is enforced in code; illegal transitions raise.
- There is **no auto-confirm code path**: the highest-risk action in the
  system (destructive merge) cannot be triggered by the pipeline, only by
  a named human actor. Blank and `"system"` actors are rejected.

## Input handling

- Parameterized SQL everywhere; no string-interpolated queries.
- CSV-formula sanitization on ingest (`=`, `+`, `-`, `@` leading cells get
  a leading quote) — same convention as Q05.
- Header validation is strict; row errors are collected, never executed.
- All web output is HTML-escaped (`html.escape`); JSON API uses
  `_error_envelope` shapes, never stack traces.

## What this document does not claim

This is not a security audit, not a compliance certification, and not
authorization to process real personal data. It is a design record of
what is safe about the *demo* (synthetic data, no network, stdlib only)
and what must change before any real deployment (hashed blocking keys,
encryption at rest, secret management, retention/consent review).
