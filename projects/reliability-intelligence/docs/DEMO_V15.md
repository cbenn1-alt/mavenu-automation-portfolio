# V15 — Conversion reference replay and acceptance checklist

**Exact standard:** V15 Normalize timestamps, units and locales.
**Proof:** Conversion reference tests (Mavenu Architecture V4, page 42).

Checkout the exact V15 GitHub commit; from projects/reliability-intelligence on Python 3.11+:

    python -m pip install -r requirements-dev.txt
    PYTHONPATH=src python scripts/verify_v8.py
    PYTHONPATH=src python scripts/replay_v9.py
    PYTHONPATH=src python scripts/verify_v10.py
    PYTHONPATH=src python scripts/verify_v11.py
    PYTHONPATH=src python scripts/verify_v12.py
    PYTHONPATH=src python scripts/verify_v13.py
    PYTHONPATH=src python scripts/verify_v14.py
    PYTHONPATH=src python scripts/verify_v15.py

Inspect evidence/V15/conversion_reference_report.json and the exact CI artifact. Confirm:
- 27 accepted expected conversions; 24 invalid conversions rejected with the stipulated error categories;
- 12 original fabricated source cases normalize without any source data change;
- each accepted canonical conversion can be replayed with no change;
- no inferred named timezone, default server offset, silent rounding, FX conversion or unapproved locale;
- V10 18-file frozen source, V11 unsigned dictionary, and V8 84.5% coverage floor remain intact;
- no customer data or human sign-off is claimed.

Expected total is 429 tests (348 previous plus 81 V15), subject to GitHub Actions logs. The clean-snapshot workflow preserves temporary V8–V15 JSON evidence for 30 days.

The reference fixtures are deliberately illustrative. Data/time and accounting stewards must approve real source clock semantics, precision, money formats, currencies and locale policy separately. Passing these tests is not approval to access Minn-Dak/customer data or deploy in any industrial setting.
