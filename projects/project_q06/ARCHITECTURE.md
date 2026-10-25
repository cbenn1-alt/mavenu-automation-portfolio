# Q06 — Architecture

## Pipeline

```
CSV sources ──► ingest ──► normalize ──► block ──► score ──► propose ──► HUMAN ──► merge
   (A/B/C)      er_*       normalize.py   er_blocks  PairScorer  proposal   confirm/   audited,
                tables     (idempotent)    (cheap     (weighted   queue      reject     reversible
                                          keys)      formula)    proposed
```

Each stage is a pure, re-runnable step. `run_resolution()` executes
normalize → block → score → propose in one idempotent pass; re-running
with no new data creates zero new pairs, zero new scores, zero new
proposals.

## Modules (new)

| Module | Owns |
|---|---|
| `src/mavenu/normalize.py` | Deterministic cleaners: `normalize_name`, `name_key` (token-sorted blocking key), `normalize_phone`, `phone_digits` (NANP `+1`-aware blocking key), `normalize_email`, `normalize_address` (suffix canonicalization), `normalize_zip`, `sanitize_cell` (CSV-formula guard). All pure functions, all idempotent. |
| `src/mavenu/entity_resolution.py` | Service layer: ingest, normalize-all, blocking, pair generation, scoring (`PairScorer` protocol + `DeterministicDemoScorer`), banding (`decide`), the merge gate (`propose_merge` / `confirm_merge` / `reject_proposal` / `reverse_merge`), audit views, run stats. No web code; fully testable without WSGI. |

Two modules, per the project brief. Web/API surface lives in `web.py`
(`/project_q06*` pages, `/api/entity-resolution*` endpoints), following
the Q05 page/API split.

## Why this shape

- **Blocking before scoring** is the honest, defensible shape of entity
  resolution at small scale: cheap equality keys prune the candidate
  space from O(n²) to the union of block co-occurrences (98.3% reduction
  on fixtures: 24 candidate pairs vs 1,431 possible). Over-blocking is the
  known failure mode, so block *coverage* is measured on fixtures (20/20).
- **Weighted scoring behind a protocol** keeps the demo formula
  replaceable without redesign — the same seam as P01's `LeadClassifier`.
  Weights and thresholds are module-level constants, not magic numbers,
  and the score breakdown (components + reasons) is stored per pair: the
  decision is explainable, not a black box.
- **The merge gate is a state machine, not a threshold.** Scoring only
  *proposes*; confirmation is a separate, human-only transition with an
  explicit actor check. This is what makes "never auto-merge below the
  high-confidence threshold" a structural property rather than a policy
  note: above the threshold the system still only proposes.
- **Reversibility by pre-image.** The merge audit row stores both records'
  full pre-merge images, so reversal is a restore, not an inverse
  computation — exact by construction, verified by full row-dict equality
  in tests.

## Schema (migration 009)

```
er_sources          id, label UNIQUE, source_kind, ingested_at
er_contacts         id, source_id, source_row UNIQUE(source_id, source_row),
                    raw_name/phone/email/address/zip/notes,
                    name_norm, name_key, phone_digits, email_norm,
                    address_norm, zip_norm,
                    status (active|merged), merged_into, created_at
er_blocks           id, block_key, contact_id, UNIQUE(block_key, contact_id)
er_pairs            id, contact_a_id < contact_b_id UNIQUE(a,b),
                    block_key, score, band, score_detail_json, scored_at
er_merge_proposals  id, pair_id UNIQUE, winner_id, loser_id,
                    state (proposed|confirmed|rejected|reversed),
                    proposed_by/at, decided_by/at, field_plan_json, decision_note
er_merge_audit      id, proposal_id, winner_id, loser_id,
                    winner_pre_image_json, loser_pre_image_json,
                    field_provenance_json, merged_by/at, reversed_at/by
er_events           id, entity_type, entity_id, event_type, actor,
                    from_state, to_state, detail_json, created_at  (append-only)
er_runs             id, kind (ingest|resolve), stats_json, actor, created_at
                    (append-only)
```

Key constraints:
- `er_pairs`: `CHECK (contact_a_id < contact_b_id)` + `UNIQUE (a, b)` —
  each unordered pair scored once.
- `er_merge_proposals`: `UNIQUE (pair_id)` — one proposal per pair, ever.
- `er_contacts`: `UNIQUE (source_id, source_row)` — idempotent re-ingest.
- `er_blocks`: rebuilt from *active* contacts each run; merged-away
  records leave the candidate space.
- Append-only tables (`er_events`, `er_runs`, pre-image columns) are never
  UPDATEd or DELETEd by application code; reversal stamps `reversed_at/by`
  once and keeps the row.

## Merge-gate state machine

```
proposed ──confirm (human actor)──► confirmed ──reverse (human actor)──► reversed
   │
   └──reject (human actor)──► rejected
```

Illegal transitions raise `MergeError`. `confirm_merge` additionally
requires both records `active` and a non-blank, non-`"system"` actor.

## Winner selection & field plan

- **Winner:** the more complete record (count of non-empty raw fields);
  ties go to the lower id. Reason recorded on the proposal event.
- **Field plan:** per field (`name, phone, email, address, zip`), the
  winning raw value with provenance: `from_contact_id` + reason
  (`identical in both records` / `only present in …` / `longer value kept`).
- On confirm, the plan is applied to the winner and normalized columns are
  re-derived; the loser is marked `merged` with `merged_into` pointing at
  the winner.

## Scoring policy (documented, not magic)

```
total = 0.45·name_ratio(name_key) + 0.25·phone_exact + 0.15·email_exact
      + 0.10·address_ratio(address_norm) + 0.05·zip_exact
      − 0.20·suffix_conflict
```

- `name_ratio` / `address_ratio`: `difflib.SequenceMatcher.ratio()`,
  0.0 when either side is empty.
- `phone_exact` / `email_exact` / `zip_exact`: 1.0 iff both sides
  non-empty and equal, else 0.0.
- `suffix_conflict`: 1.0 when the generational-suffix sets
  ({jr, sr, ii, iii, iv, v} over `name_key` tokens) differ.
- Bands: `match` ≥ 0.85 · `review` ≥ 0.60 · else `no_match` (inclusive,
  boundary-tested).

## Failure modes & mitigations (spec §2)

| Failure | Mitigation (implemented) |
|---|---|
| False merge destroys data | Merges are reversible — full pre-images stored; `reverse_merge` restores both rows exactly (tested with row-dict equality) |
| Over-blocking misses real duplicates | Block coverage reported on fixtures (20/20); three redundant key families (phone, email, ZIP+surname) |
| Under-blocking explodes pair count | Pairs only from shared blocks; pair count asserted < n·(n−1)/2; 98.3% reduction measured |
| Silent auto-merge | No auto-confirm code path exists; `confirm_merge` rejects blank/`"system"` actors; proposals always start `proposed` (tested) |
| PII mishandling | Synthetic only in this build; hashing strategy documented in SECURITY.md for real deployments |
| Stale normalized columns | `normalize_all` re-derives them from raw columns every run; normalized columns are never trusted blindly |

## What this is not

Not a learned model, not a production MDM system, not a real-PII
pipeline. The scorer is a labeled deterministic demo formula; the
fixtures are invented; the "reviewer" is a form field. The architecture's
claim is narrower and real: blocking + explainable scoring + a
human-gated, fully reversible merge.
