# Q06 — Test Results

Recorded from actual runs. Nothing below is fabricated; re-run with
`.venv/bin/python -m pytest tests/ -q` from the repo root.

## Latest full run — 2026-10-23

```
827 passed in 23.17s
```

| Module | Tests | Result |
|---|---|---|
| `tests/test_entity_resolution.py` | 122 | 122 passed |
| `tests/test_entity_resolution_api.py` | 12 | 12 passed |
| **Q06 total** | **134** | **134 passed, 0 failed** |
| Baseline regression (all prior projects) | 693 | 693 passed |
| **Full suite** | **827** | **827 passed, 0 failed** |

Environment: Python 3.12.3, pytest 9.1.1, SQLite 3.45.1, stdlib-only app,
Linux. Run date: 2026-10-23.

## Rollback test — 2026-10-23 (real, recorded in-suite)

`tests/test_entity_resolution.py::test_migration_009_down_step_rolls_back_for_real`
ran against a real SQLite database in this environment:

1. `009_entity_resolution.sql` applied (in the migrations table); fixture
   ingested (54 contacts) and resolved (24 pairs, 20 proposals).
2. `rollback_migration(conn, "009_entity_resolution.sql")` → returned True;
   all eight `er_*` tables dropped; migration record removed.
3. Verified other projects' tables still present (`leads`,
   `recon_invoices`, …).
4. `run_migrations(conn)` re-applied `009_entity_resolution.sql` cleanly.

## Measured performance criteria (spec §2)

| Criterion | Target | Measured | Verdict |
|---|---|---|---|
| Recall ≥ 95% on planted duplicates at 0.85 | ≥ 0.95 | **1.000 (20/20)** — every planted duplicate in the match band | PASS |
| Precision reported honestly | report | **1.000 (20/20)** — all match-band pairs are true duplicates; adversarial fixtures land in review/no-match | PASS |
| 100% merge reversibility | exact pre-image restore | winner and loser rows restored with full row-dict equality after `reverse_merge` | PASS |
| Normalization idempotent | f(f(x)) == f(x) | 7 cleaners × 10 inputs, all idempotent | PASS |
| Block coverage on fixtures | report | **1.000 (20/20)** planted pairs share ≥1 block | PASS |
| No O(n²) fallback | pairs < n(n−1)/2, every pair shares a block | 24 candidate pairs vs 1,431 possible (98.3% reduction); 0 orphan pairs; 4 unique contacts generate 0 pairs | PASS |
| Never auto-merge below high-confidence threshold | no auto-confirm path | after `run_resolution`: 0 proposals outside `proposed`; `confirm_merge` rejects blank/`system` actors; signature-introspection guard on `run_resolution` | PASS |
| Threshold boundaries | 0.85 match / 0.60 review inclusive | `decide()` boundary tests pass (0.85→match, 0.849→review, 0.60→review, 0.599→no-match) | PASS |
| Suffix-conflict guard | Jr/Sr must not auto-merge | Jr/Sr pair scores 0.70 (review); without the −0.20 penalty it would score 0.90 (match) — the penalty is load-bearing and tested | PASS |
| Adversarial non-duplicates | no false auto-merges | twins → review, Jr/Sr → review, shared phone → no-match, household → review, similar names → no-match; 0 automatic proposals outside match band | PASS |
| Human gate on review pairs | explicit propose → confirm | twins pair proposed by human actor, then confirmed through the same gate; no-match pair proposal rejected in code | PASS |
| CSV-formula sanitization | no live formula cells | `=HYPERLINK…` name stored with leading `'` | PASS |
| Idempotent pipeline | re-run changes nothing | 2nd `run_resolution`: 0 new pairs, 0 scored, 0 proposals; `normalize_all` re-run: rows byte-identical | PASS |
| Scorer replaceability | protocol seam works | custom `PairScorer` drives `run_resolution`; its scorer id recorded on pairs | PASS |
| Migration rollback | real down-step | apply → use → roll back → re-apply (see above) | PASS |

## Fixture band ledger (measured, 2026-10-23)

- Match (20): all 20 planted duplicates, scores 0.85–1.00
  (dup05 `Grace Adeyemi` and dup10 `Nina Kowalski` sit exactly on the 0.85
  boundary — missing-field variants, correctly at the threshold edge).
- Review (3): twins 0.75, Jr/Sr 0.70 (penalty applied), household 0.72.
- No-match (1): shared phone 0.49.

Precision and recall above are measured on this fixture; they describe the
fixture, not real-world performance — the docs never claim otherwise.
