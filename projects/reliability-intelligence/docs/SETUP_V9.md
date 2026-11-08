# V9 — clean setup and first execution (synthetic-only)

**Scope:** Mavenu Reliability Intelligence, V9, prototype foundation. Python 3.11+ on Linux, macOS, or Windows with a supported terminal. The exact V9 evidence environment is GitHub Actions Ubuntu + Python 3.11.

**Product runtime:** Python standard library only. A test-only coverage.py dependency is pinned in requirements-dev.txt. No accounts, API keys, deployment credentials, customer data or external endpoints are needed.

## 1. Obtain and check out source

The GitHub project currently lives under projects/reliability-intelligence in the existing portfolio repository, NOT in a dedicated Reliability Intelligence repository.

    git clone https://github.com/cbenn1-alt/mavenu-automation-portfolio.git
    cd mavenu-automation-portfolio
    git fetch origin feature/reliability-intelligence-v9
    git switch --detach origin/feature/reliability-intelligence-v9
    cd projects/reliability-intelligence

If a reviewer is provided a precise V9 commit SHA, use that SHA instead of a moving branch name. These instructions fetch source over GitHub. The application runtime and replay themselves access local loopback only.

## 2. Install test-only tool

On POSIX shells:

    python -m pip install -r requirements-dev.txt

The product has no third-party runtime dependencies. Never enter customer credentials into the prototype.

## 3. Full V8 regression and coverage baseline

    PYTHONPATH=src python scripts/verify_v8.py

Expected checks: 153 or more distinct automated tests (140 inherited V8, plus 13 V9 document/replay tests), at least 84.5% source statement-and-branch coverage, all required source modules and V8 historical test-module minima. Treat these numbers as policy targets; verify actual CI and output. The V8 baseline was measured on an earlier commit; a V9 coverage increase or unchanged result is expected but not guaranteed.

Generated ignored files: evidence/V8/verification.json and evidence/V8/coverage.json. They are technical evidence, not customer data or a release approval.

## 4. Local server and synthetic demonstration

    PYTHONPATH=src python -m reliability_intelligence status --json
    PYTHONPATH=src python -m reliability_intelligence demo --json
    PYTHONPATH=src python -m reliability_intelligence diagnose --json
    PYTHONPATH=src python -m reliability_intelligence serve --port 8765

Open http://127.0.0.1:8765/ on the SAME computer. The server binds to 127.0.0.1 only. Open /workbench, /workflow, /evaluation and /governance. The case records and review decisions are invented and do not represent Minn-Dak or any other plant.

Stop the application with Ctrl+C.

## 5. Reproducible automated local-socket replay

    PYTHONPATH=src python scripts/replay_v9.py

This starts a temporary loopback-only server, probes the five pages, five versioned read-only API endpoints, synthetic fixture content and error paths, verifies the same deterministic V6 demo digest between CLI and HTTP, terminates the temporary server, and writes evidence/V9/replay.json only on success. This is an AUTOMATED test, not an independent human reviewer acceptance.

## 6. Human reviewer evidence

Complete docs/REVIEWER_REPLAY_V9.md and docs/V9_REVIEWER_RECORD_TEMPLATE.json outside the checked-in repository if confidential reviewer names are used. Review source exclusions in docs/EXCLUSIONS_V9.md. Record the exact source commit, independent reviewer identity, date, environment, terminal replay outcomes, actual visual/browser observations, exceptions, evidence digest, and human sign-off. Do not change the unsigned template in this PR to imply a real reviewer has approved it.

**Stop conditions:** Any failed test, unexpected network binding, data provenance mismatch, new write route, unexpected credential request, mislabeled real customer data, or missing documented exclusion blocks acceptance.

See docs/releases/V9.md. V2–V8 formal human decisions remain unresolved; the separate V1 Git history is not integrated. No production or industry-safety claims are made.
