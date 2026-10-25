# Q08 — Test Plan

**Status:** Implemented · Tested (2026-10-23). All synthetic data.

## Fixture design

`tests/q08_review_fixtures.py` builds **200 fabricated reviews**, labeled
by construction (each entry was written to carry its labels):

| Segment | n | Construction |
|---|---|---|
| Confident positive | 60 | 2 positive sentences, one topic each (15/topic × 4 topics) |
| Confident negative | 60 | 2 negative sentences, one topic each |
| Neutral / weak-evidence | 40 | Factual sentences, no sentiment lexicon hits → uncertain |
| Sarcasm | 20 | Positive-sounding text with 1★ (e.g. "Oh fantastic — they never showed up") |
| Mixed sentiment | 20 | Balanced positive/negative evidence → uncertain |

`pr_fixture()` = the 120 confident rows (sentiment P/R). Topic P/R is
measured over all 200 rows. `adversarial_fixture()` = the 40 sarcasm +
mixed rows (routing-to-human tests).

## Test files

| File | Tests | Covers |
|---|---|---|
| `tests/test_tagger.py` | 19 | Fixture size; sentiment P/R per category (floors 0.95); topic P/R per topic (floors 0.70); uncertainty flag 60/60, 0/120 false flags; determinism; negation scope; empty text; explanation; lexicon version on result; honest labeling (not-ML); lexicon seed/inspect idempotency; from_db rebuild equality; unknown version raises; protocol replaceability |
| `tests/test_reviews.py` | 32 | Normalization validation; ingest stores+tags; idempotency on natural key; CSV stats/skips; empty CSV rejected; audit events; protocol-driven ingest (stub tagger → human_review); **critical routing recall 100% (52/52 1★ rows)**; 200/200 fixture routing; default-to-alert on adversarial; sarcasm → owner_alert/critical; positive → no queue; pure route_decision; SLA hours; SLA due UTC math; breach escalation on frozen clock; escalation idempotency; queue resolve + double-resolve rejection; queue summary/SLA status; template sanity (no digits/$/promise-words); all tones present; draft generate + validation; approve gate + double-decide rejection; reject path; **sent-state unreachable (4 assertions)**; DB CHECK rejects 'sent'; approve nonexistent; lexicon idempotency; **real migration rollback** |
| `tests/test_reviews_api.py` | 14 | Ingest endpoint + idempotency; bad-event skipping; non-list events → 400; list with tags + queue/severity; sentiment filter; queues + SLA endpoints; draft generate/approve/reject lifecycle; double-approve → 422; bad tone → 422; **no send endpoint (3 methods × 404)**; lexicon inspection + 404; page rendering (4 pages); CSV form ingest; queue resolve redirect |

## How to run

```bash
cd ~/workspace/mavenu-portfolio
.venv/bin/python -m pytest tests/test_tagger.py tests/test_reviews.py tests/test_reviews_api.py -q
# full suite (regression):
rm -rf /tmp/pytest-of-root   # recurring 512M tmpfs pressure (see AGENTS.md)
.venv/bin/python -m pytest tests/ -q
```

Note: on this host the full suite's per-test `tmp_path` DBs can fill the
512 MB /tmp tmpfs mid-run (unrelated to the code). The reliable full-suite
invocation uses a disk-backed tmp dir:
`TMPDIR=~/workspace/.pytest-tmp .venv/bin/python -m pytest tests/ -q`.

## Pass criteria

- All 65 Q08 tests pass; full suite passes with zero regressions.
- Sentiment P/R floors (0.95) and topic P/R floors (0.70) hold.
- Critical routing recall is exactly 100% — any miss fails the suite.
- Rollback test passes against a real SQLite database.
- `template_sanity()` reports `ok: True`.
