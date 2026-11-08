"""V8 clean regression/coverage evidence runner, with no runtime app dependencies.

A temporary initial CI run writes a candidate coverage snapshot. After the
observed baseline is committed, subsequent runs enforce the explicit floor.
No customer data, secrets, external endpoints or plant systems are accessed.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
EVIDENCE = PROJECT / "evidence" / "V8"
BASELINE = PROJECT / "docs" / "releases" / "V8_BASELINE.json"
COVERAGE = EVIDENCE / "coverage.json"
REPORT = EVIDENCE / "verification.json"
PYTHON_PACKAGE = "reliability_intelligence"
MINIMUM_TESTS = 140
MINIMUM_SOURCE_MODULES = 7


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def _call(*args):
    command = [sys.executable, *args]
    result = subprocess.run(command, cwd=PROJECT, check=False)
    if result.returncode:
        raise RuntimeError("Regression command failed with exit code " + str(result.returncode))


def main() -> int:
    os.chdir(PROJECT)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    tests = sorted(test.id() for test in flatten(unittest.defaultTestLoader.discover("tests")))
    if len(set(tests)) != len(tests):
        raise ValueError("Duplicate test identifiers detected")
    if len(tests) < MINIMUM_TESTS:
        raise ValueError(f"Test baseline regression: {len(tests)} < {MINIMUM_TESTS}")
    by_module = {}
    for test_id in tests:
        module = test_id.split(".", 1)[0]
        by_module[module] = by_module.get(module, 0) + 1
    required = {
        "test_charter", "test_ui", "test_api_contract",
        "test_fixtures", "test_workflow", "test_diagnostics",
        "test_regression_v8",
    }
    if not required.issubset(by_module):
        raise ValueError("One or more historical increment test modules are absent")

    _call("-m", "reliability_intelligence", "validate", "--json")
    _call("-m", "coverage", "run", "--rcfile=.coveragerc",
          "-m", "unittest", "discover", "-s", "tests", "-v")
    _call("-m", "coverage", "json", "--rcfile=.coveragerc", "-o", str(COVERAGE))
    _call("-m", "coverage", "report", "--rcfile=.coveragerc")

    coverage = json.loads(COVERAGE.read_text(encoding="utf-8"))
    totals = coverage["totals"]
    modules = coverage["files"]
    percent = float(totals["percent_covered"])
    if len(modules) < MINIMUM_SOURCE_MODULES:
        raise ValueError("Source coverage incomplete: fewer than seven source modules")
    if not (0 <= percent <= 100):
        raise ValueError("Coverage percentage is invalid")
    if int(totals["num_statements"]) <= 0:
        raise ValueError("Coverage contained no source statements")

    snapshot = {
        "increment": "V8",
        "proof": "CI result and baseline coverage",
        "test_count": len(tests),
        "test_inventory_sha256": hashlib.sha256(("\n".join(tests) + "\n").encode("utf-8")).hexdigest(),
        "tests_by_module": by_module,
        "coverage_total_percent": round(percent, 3),
        "covered_lines": int(totals["covered_lines"]),
        "num_statements": int(totals["num_statements"]),
        "covered_branches": int(totals.get("covered_branches", 0)),
        "num_branches": int(totals.get("num_branches", 0)),
        "source_module_count": len(modules),
        "source_files": sorted(modules),
        "python_version": platform.python_version(),
        "tool": "coverage.py",
        "scope": "synthetic-only test execution; not customer or operational verification",
        "production_approved": False,
        "human_owner_approved": False,
    }
    if BASELINE.is_file():
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        if baseline.get("increment") != "V8" or baseline.get("status") != "measured_baseline_pending_human_signoff":
            raise ValueError("Unexpected baseline structure or state")
        floor = baseline["minimum_total_percent"]
        minimum_count = baseline["minimum_test_count"]
        if type(floor) not in (int, float) or not 0 < floor <= 100:
            raise ValueError("Invalid coverage policy floor")
        if int(minimum_count) < MINIMUM_TESTS:
            raise ValueError("Insufficient regression test floor")
        if len(tests) < minimum_count:
            raise ValueError("Regression inventory shrank below frozen baseline")
        if percent + 1e-8 < floor:
            raise ValueError(f"Coverage regression: {percent:.2f}% < {floor:.2f}%")
        snapshot["baseline_state"] = "frozen_measured_pending_human_signoff"
        snapshot["coverage_policy_floor_percent"] = floor
        snapshot["test_count_policy_floor"] = minimum_count
        snapshot["coverage_floor_passed"] = True
        snapshot["test_count_floor_passed"] = True
    else:
        snapshot["baseline_state"] = "candidate_unfrozen"
        snapshot["coverage_policy_floor_percent"] = None
        snapshot["test_count_policy_floor"] = MINIMUM_TESTS
        snapshot["coverage_floor_passed"] = None
        snapshot["test_count_floor_passed"] = True
        (EVIDENCE / "baseline_candidate.json").write_text(
            json.dumps(snapshot, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
    snapshot["git_sha"] = os.environ.get("GITHUB_SHA", "not_provided")
    REPORT.write_text(json.dumps(snapshot, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("V8_VERIFICATION: " + json.dumps({
        "baseline_state": snapshot["baseline_state"],
        "tests": snapshot["test_count"],
        "coverage_percent": snapshot["coverage_total_percent"],
        "source_modules": snapshot["source_module_count"],
        "coverage_floor_passed": snapshot["coverage_floor_passed"],
        "test_inventory_sha256": snapshot["test_inventory_sha256"],
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as exc:
        print(f"V8_VERIFICATION_FAILED: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
