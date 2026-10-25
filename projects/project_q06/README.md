# Q06 — Data Quality & Entity Resolution Service

**Status: Implemented · Tested** — 134 automated tests, all passing
(827/827 full suite: 693 baseline + 134 Q06; zero regressions).

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | Multi-source CSV ingest with header validation, row-level error reporting, CSV-formula sanitization, and idempotent inserts on (source label, source row); deterministic idempotent normalizers (name/phone/email/address/ZIP) in `normalize.py`, each unit-tested; blocking on cheap equality keys (phone digits, lowercased email, ZIP+surname) — candidate pairs come only from block co-occurrence, never an O(n²) scan; weighted pairwise scorer behind the replaceable `PairScorer` protocol with documented weights and documented match/review/no-match thresholds; merge proposals that a named human confirms (blank and `"system"` actors are rejected in code); full before/after audit of every merge with per-field provenance; **exact merge reversibility** (pre-merge row images of both records restored byte-for-byte); migration `009_entity_resolution.sql` + real rollback test |
| What is SIMULATED | **Simulated** | The fixture contact lists (invented names, phones, emails, addresses across three fake sources). The scoring weights are a documented, deterministic formula — not a trained model and never described as one. The "reviewer" actor in demos is a form field, not authenticated users |
| What is SYNTHETIC | **Demo** | **All contact data is synthetic.** Every name, phone number, email, and address is fabricated for demonstration. The UI carries the "SYNTHETIC DEMO DATA" banner |
| What is NOT claimed | — | No production deployment. No real users, no real customer records. **Never auto-merges below the high-confidence threshold — the human stays in the loop by design.** No platform or employer endorsement |

## Business problem

Customer records live in three spreadsheets, a form tool, and someone's
phone. Duplicates pile up; mailings and follow-ups hit the same household
twice.

This project is a working entity-resolution service: contact CSVs from
multiple sources are ingested and normalized by deterministic cleaners,
candidate duplicates are found through blocking (not brute-force
comparison), scored by a transparent weighted formula, and sorted into
**match / review / no-match** bands. Match-band pairs get merge
*proposals* — a named human confirms or rejects each one. Every confirmed
merge stores full pre-merge images of both records with per-field
provenance, and any merge can be reversed exactly.

## Implemented capabilities

- **Ingest** (`entity_resolution.ingest_source`): header validation (fatal
  on missing columns), row-level errors with 1-based row numbers (bad rows
  never abort the batch), CSV-formula sanitization, idempotent inserts on
  (source label, source row)
- **Normalize** (`normalize.normalize_*`): case/whitespace/phone-format/
  address-casing cleaners; every cleaner is idempotent
  (`normalize(normalize(x)) == normalize(x)`, tested) and unit-tested
- **Block** (`entity_resolution.build_blocks`): phone digits, lowercased
  email, ZIP+surname keys; blocks rebuilt from active contacts each run;
  block coverage on fixtures: 20/20 planted duplicate pairs share a block
- **Score** (`entity_resolution.DeterministicDemoScorer` behind the
  `PairScorer` protocol): weights name 0.45 / phone 0.25 / email 0.15 /
  address 0.10 / ZIP 0.05 (sum 1.00); thresholds match ≥ 0.85,
  review ≥ 0.60; generational-suffix conflict penalty −0.20 (Jr/Sr records
  land in review, never auto-merge territory)
- **Bands**: match → merge *proposal* (never auto-confirmed); review →
  human queue (a human may propose); no-match → recorded, never proposed
- **Merge gate** (`propose_merge` / `confirm_merge` / `reject_proposal` /
  `reverse_merge`): proposals are created only as `proposed`;
  `confirm_merge` requires a non-blank, non-`"system"` human actor;
  per-field winning values with provenance (which record each value came
  from and why); full pre-merge row images of winner and loser;
  `reverse_merge` restores both rows exactly; append-only `er_events`
  audit trail
- **Measured**: recall 1.000 (20/20 planted duplicates at threshold 0.85),
  precision 1.000 (20/20 match-band pairs are true duplicates) —
  reported honestly from the fixture run; block coverage 1.000;
  O(n²) reduction 98.3% (24 candidate pairs vs 1,431 possible)
- **Web**: `/project_q06` (upload + run pipeline + snapshot),
  `/project_q06/pairs` (band filter, pair detail with score breakdown),
  `/project_q06/merges` (proposal queue, confirm/reject/reverse),
  and `/api/entity-resolution/*` (upload, run, stats, pairs, proposals,
  propose/confirm/reject/reverse, audit)
- **Rollback**: `009_entity_resolution.down.sql` +
  `db.rollback_migration()`, tested for real (apply → use → roll back →
  re-apply)

## What is simulated (labeled, not hidden)

- **The data**: every contact, phone number, email, and address is
  invented. Demo contacts are not real people and must never be presented
  as such.
- **The scorer**: a transparent, deterministic weighted formula with
  documented weights — not a learned model, not "AI matching".
- **The reviewer**: actor stamps are form/API fields, not authenticated
  identities.

## What is not claimed

- No production deployment, no real users, no real customer records.
- **Merges below the high-confidence threshold never happen automatically.**
  Below 0.85 the system proposes at most; a human confirms or the pair
  waits. There is no auto-confirm code path (asserted by tests, including
  an introspection guard on `run_resolution`'s signature).
- **Not a substitute for real data-governance controls.** Real deployments
  need consent/retention review and hashed blocking keys (see SECURITY.md).
