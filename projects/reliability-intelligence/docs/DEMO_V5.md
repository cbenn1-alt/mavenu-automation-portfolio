# V5 smoke demonstration — synthetic fixtures

Development Architecture V4 page 42: **V5 load representative synthetic fixtures; proof is documented fixture provenance**.

1. Inspect fixtures/manifest.json, cases.json, reference_labels.json and fixtures/README.md. Confirm six fictional assets, 12 fabricated cases, distinct authored labels and no customer data or external source systems.
2. Run unit and negative-path tests:

~~~~bash
cd projects/reliability-intelligence
PYTHONPATH=src python -m reliability_intelligence validate --json
PYTHONPATH=src python -m unittest discover -s tests -v
~~~~

Expected suite: 71 tests. Verify the actual GitHub Actions logs before recording pass.

3. Start the local-only service and browse the case workbench:

~~~~bash
PYTHONPATH=src python -m reliability_intelligence serve --port 8765
~~~~

Open http://127.0.0.1:8765/workbench. Expect a 12-row synthetic table, no human dispositions, no real plant readings, and no seeded reference labels.

4. Verify v1 API and negative methods:

~~~~bash
curl -i http://127.0.0.1:8765/api/v1/status
curl -i http://127.0.0.1:8765/api/v1/cases
curl -i http://127.0.0.1:8765/api/v1/contract
curl -I http://127.0.0.1:8765/api/v1/cases
curl -i -X POST http://127.0.0.1:8765/api/v1/cases
curl -i http://127.0.0.1:8765/api/v2/cases
~~~~

Expected: schema_version 1.1.0; count=12; population_status=synthetic_fixtures_loaded; status operational_data_loaded=false; HEAD no body; POST 405; unknown version 404; corrupted fixture 503 without internal path leakage. All actual steps require reviewer reproduction and release evidence.

5. Record decision in docs/releases/V5.md. Business/product, prior V2–V4 approvals and domain validations remain pending.

Not an industrial safety, predictive-maintenance or financial-performance test.
