# V6 reproducible demo trace — reviewer instructions

**Purpose:** independently replay V6's synthetic intake/evidence/rule/scripted disposition/export path. Not a customer pilot.

From projects/reliability-intelligence on branch feature/reliability-intelligence-v6:

~~~~bash
PYTHONPATH=src python -m reliability_intelligence validate --json
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m reliability_intelligence demo --json
PYTHONPATH=src python -m reliability_intelligence demo --json
~~~~

Compare event sequences and trace_sha256 across runs. Expect 12 synthetic cases, 4 simulated dispositions, 8 without disposition, and the same checksum. The demonstration uses no true human review and writes no export file. Expected full suite = 98 tests; check the actual GitHub log.

Start local-only service:

~~~~bash
PYTHONPATH=src python -m reliability_intelligence serve --port 8765
~~~~

Open http://127.0.0.1:8765/workflow and verify the fictional reviewer disclosure and checksum. Then:

~~~~bash
curl -i http://127.0.0.1:8765/api/v1/demo
curl -I http://127.0.0.1:8765/api/v1/demo
curl -i -X POST http://127.0.0.1:8765/api/v1/demo
curl -i http://127.0.0.1:8765/api/v2/demo
~~~~

Expected: API v1, schema 1.2.0, GET 200, HEAD 200 with no body, POST 405, v2 404; invalid scripted fixture triggers sanitized 503. Authored reference labels are excluded from UI/API. Record exact commit, CI URL, matching trace hash, reviewer name and human release decision.

No real customer, system of record, industrial-control system, operational recommendation, paid benefit or safety authorization is involved.
