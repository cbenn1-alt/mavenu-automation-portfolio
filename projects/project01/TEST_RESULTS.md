# Project 01 — Test Results

Recorded from actual runs. Nothing below is fabricated; re-run with
`.venv/bin/python -m pytest tests/ -q` from the repo root.

## Latest full run — 2026-10-22 (UTC 2026-10-23T02:2x)

```
51 passed in 0.14s
```

| Module | Tests | Result |
|---|---|---|
| `tests/test_workflow.py` | 6 | 6 passed |
| `tests/test_validation.py` | 16 | 16 passed |
| `tests/test_classifier.py` | 5 | 5 passed |
| `tests/test_leads.py` | 10 | 10 passed |
| `tests/test_web.py` | 14 | 14 passed |
| **Total** | **51** | **51 passed, 0 failed** |

Environment: Python 3.12.3, pytest 9.1.1, SQLite 3.45.1, stdlib-only app.

## Live smoke test — 2026-10-22 (real server, `python run.py --port 8123`)

| Check | Result |
|---|---|
| `GET /` hub | 200 |
| `POST /api/leads` strong lead | 201 → `{"public_id":"LD-000001","state":"booked","booking_ref":"BK-LD-000001-001"}` |
| `POST /api/leads` thin lead | 201 → `{"public_id":"LD-000002","state":"needs_review","booking_ref":null}` |
| `GET /api/stats` | 200 → `{"total":2,"by_state":{"booked":1,"needs_review":1}}` (reconciles) |
| `GET /project01/dashboard` | 200 |

## Acceptance criteria verdict (spec §8)

| Criterion | Verdict |
|---|---|
| Valid submissions create one lead record | ✅ PASS |
| Invalid submissions rejected / flagged | ✅ PASS |
| Duplicates do not create duplicate records | ✅ PASS |
| Uncertain AI outputs enter review | ✅ PASS |
| Failed integrations do not silently lose leads | ✅ PASS |
| Retries do not duplicate business effect | ✅ PASS |
| Dashboard totals reconcile with DB | ✅ PASS |

**Gate A verdict: MET.** A synthetic lead can be submitted, validated,
stored, retrieved, and tracked through a documented workflow — demonstrated
by tests and by the live server above.

## Known defects

None open. One defect was found and fixed during development (missing commit
in `record_event()`; see TEST_PLAN.md).
