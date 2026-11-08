# V9 — reproducible replay quick reference

Development Architecture V4, page 42: **V9 Document setup, demo steps and exclusions. PROOF: Independent reviewer replay.**

The V9 automated companion establishes a fresh local-socket synthetic demonstration; this is not an independent human reviewer approval.

    git clone https://github.com/cbenn1-alt/mavenu-automation-portfolio.git
    cd mavenu-automation-portfolio
    git fetch origin feature/reliability-intelligence-v9
    git switch --detach origin/feature/reliability-intelligence-v9
    cd projects/reliability-intelligence
    python -m pip install -r requirements-dev.txt
    PYTHONPATH=src python scripts/verify_v8.py
    PYTHONPATH=src python scripts/replay_v9.py

Expected technical effects: legacy V8 140-test floor plus V9 new tests, minimum 84.5% combined coverage, local-socket verification of five pages and five APIs, 12 synthetic cases and four scripted decisions, deterministic replay hash, no actual operator approvals, successful HTTP GET/HEAD, rejected POST and unknown v2 API namespace.

Evidence: evidence/V8/verification.json, evidence/V8/coverage.json, evidence/V9/replay.json and exact-commit GitHub Actions artifact. These files are generated from the checked-out source and are not production audit records.

Human reviewer must separately inspect page behavior, appearance, keyboard focus, and exclusions, then sign a private copy of V9_REVIEWER_RECORD_TEMPLATE.json. Until then independent_human_reviewer=false and formal_review_accepted=false.

See SETUP_V9.md, REVIEWER_REPLAY_V9.md and EXCLUSIONS_V9.md for the full protocol. No customer or industrial connections are involved.
