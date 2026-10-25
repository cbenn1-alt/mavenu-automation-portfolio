# Q07 — Security

## Threat model (demo scope)

This is a local demo app: stdlib-only WSGI, SQLite file, no auth, no
network calls. The realistic threats are data-integrity and
misrepresentation threats, not network attacks.

## Controls

| Threat | Control |
|---|---|
| **Silent data loss** (bad rows dropped, drift ignored) | quarantine-with-reason is the only path for non-staged data; column-level drift entries (`source_row` NULL); `schema_drift` alerts; zero-silent-drop tests |
| **Double counting** (same CSV ingested twice; job IDs colliding across locations) | batch dedup key (location, period, label); UNIQUE(ingest_id, source_row); location-scoped job IDs; re-ingest tests |
| **History rewriting** (a definition change silently altering past KPIs) | definitions versioned, never edited in place; restatement log with reason + actor; old values superseded, never deleted; old lineage preserved |
| **Formula confusion** (money as float) | Decimal everywhere; stored as text; no `float` in `kpi_defs.py` or `kpi_pipeline.py` |
| **Misrepresentation as real financials** | SYNTHETIC DEMO DATA banner on every page; README states not a substitute for audited financials; every figure labeled synthetic in docs and fixtures |
| **Unvalidated input crashing the pipeline** | period format enforced (`YYYY-MM`); schema-map validated at registration; per-row validation quarantines instead of aborting the batch |
| **Actor spoofing** | actor stamps are form/API fields, honestly labeled as such (same convention as Q06) — no authenticated identity is claimed |

## Explicitly out of scope / not claimed

- No authentication, authorization, or encryption at rest (local demo).
- No PII handling: fixtures contain no real personal data; real
  deployments must review retention and access control.
- The `gross_margin` v2 $50 callback rework cost is a disclosed placeholder
  assumption, not a measured cost — real deployments must replace it with
  actual rework accounting before using it for decisions.

## Code review notes

- All SQL is parameterized; no string-interpolated queries.
- `ON CONFLICT ... DO UPDATE` targets the expression unique index
  `uq_kpi_values` with matching expressions.
- Down-step drops indexes before tables; verified by the real rollback test.
