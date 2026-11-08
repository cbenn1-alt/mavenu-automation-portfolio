"""V9 clean-checkout, local-socket replay and unsigned technical evidence.

Standard-library only. The tool exercises a fresh checkout's existing V8
application and its synthetic demo; it does NOT replace independent HUMAN
review, a browser accessibility audit or business approval.

Only approved local output: evidence/V9/replay.json. No customer data,
external hosts, credentials, real decisions or OT connections.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT = Path(__file__).resolve().parents[1]
EVIDENCE = PROJECT / "evidence" / "V9"
REPORT_PATH = EVIDENCE / "replay.json"
UI_PATHS = ("/", "/workbench", "/workflow", "/evaluation", "/governance")
API_PATHS = (
    "/api/v1/status", "/api/v1/scope", "/api/v1/cases",
    "/api/v1/demo", "/api/v1/contract",
)
MAX_BODY_BYTES = 150000
EXPECTED_CASES = 12
EXPECTED_SCRIPTED = 4


def require(ok: bool, check: str) -> None:
    """Fail closed on an explicitly named, non-sensitive invariant."""
    if not ok:
        raise ValueError("Failed V9 replay invariant: " + check)


def _environment() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _cli_json(command: str, env: dict[str, str]) -> dict:
    child = subprocess.run(
        [sys.executable, "-m", "reliability_intelligence", command, "--json"],
        cwd=PROJECT,
        env=env,
        capture_output=True,
        timeout=15,
        check=False,
    )
    require(child.returncode == 0, "local_cli_" + command)
    try:
        result = json.loads(child.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Invalid JSON from local CLI") from None
    require(isinstance(result, dict), "cli_json_object_" + command)
    return result


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _http(port: int, path: str, method: str = "GET") -> tuple[int, dict[str, str], bytes]:
    """Fixed local routes only; never follow redirects to an external host."""
    require(path in UI_PATHS + API_PATHS +
            ("/assets/style.css", "/api/v2/status", "/unlisted-page"), "allowlisted_http_path")
    require(method in ("GET", "HEAD", "POST"), "allowlisted_http_method")
    request = Request(f"http://127.0.0.1:{port}{path}", method=method)
    try:
        with urlopen(request, timeout=3) as response:
            return response.status, dict(response.headers.items()), response.read(MAX_BODY_BYTES + 1)
    except HTTPError as error:
        try:
            return error.code, dict(error.headers.items()), error.read(MAX_BODY_BYTES + 1)
        finally:
            error.close()


def _json_document(status: int, data: bytes, expected_resource: str) -> dict:
    require(status == 200, "api_" + expected_resource + "_200")
    require(len(data) <= MAX_BODY_BYTES, "bounded_api_body")
    try:
        document = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Invalid JSON API response") from None
    require(document.get("api_version") == "v1", "api_v1")
    require(document.get("schema_version") == "1.3.0", "api_schema_1_3_0")
    require(document.get("resource") == expected_resource, "api_resource_" + expected_resource)
    require(isinstance(document.get("data"), dict), "api_payload_" + expected_resource)
    return document["data"]


def _wait_for_server(proc: subprocess.Popen, port: int) -> None:
    deadline = time.monotonic() + 7
    while time.monotonic() < deadline:
        require(proc.poll() is None, "server_process_running")
        try:
            status, _, _ = _http(port, "/")
            if status == 200:
                return
        except (URLError, ConnectionError, OSError):
            pass
        time.sleep(0.07)
    raise ValueError("Loopback server did not become ready")


def main() -> int:
    env = _environment()
    checks: list[str] = []
    require((PROJECT / "fixtures" / "manifest.json").is_file(), "fixture_manifest_present")
    require((PROJECT / "product_charter.json").is_file(), "candidate_charter_present")
    require((PROJECT / "docs" / "releases" / "V8_BASELINE.json").is_file(), "v8_coverage_baseline_present")
    checks.append("clean_checkout_inputs_present")

    validated = _cli_json("validate", env)
    require(validated["valid_contract"] is True, "candidate_charter_valid")
    require(validated["business_approved"] is False, "business_approval_pending")
    checks.append("charter_cli")

    status = _cli_json("status", env)
    require(status["increment"] == "V9", "runtime_increment_v9")
    for name in ("business_approved", "production_ready", "customer_data_authorized",
                 "external_integrations_enabled", "ot_writes_enabled", "measured_effectiveness"):
        require(status[name] is False, "status_" + name)
    require(status["ui_mode"] == "loopback_only", "loopback_scope")
    checks.append("safe_runtime_status")

    cli_demo_a = _cli_json("demo", env)
    cli_demo_b = _cli_json("demo", env)
    require(cli_demo_a == cli_demo_b, "deterministic_cli_replay")
    require(cli_demo_a["case_count"] == EXPECTED_CASES, "synthetic_case_count")
    require(cli_demo_a["scripted_disposition_count"] == EXPECTED_SCRIPTED, "scripted_case_count")
    require(cli_demo_a["not_dispositioned_count"] == 8, "no_unapproved_real_reviews")
    require(cli_demo_a["real_human_review_performed"] is False, "no_human_review_claim")
    require(cli_demo_a["real_work_orders_written"] is False, "no_work_orders_created")
    require(cli_demo_a["measured_business_outcome"] is False, "no_business_outcome_claim")
    require(len(cli_demo_a["trace_sha256"]) == 64, "sha256_digest_format")
    checks.append("reproducible_cli_trace")

    diagnostic_demo = _cli_json("diagnose", env)
    require(diagnostic_demo["simulated"] is True, "diagnostics_simulated")
    require(diagnostic_demo["actual_incidents_observed"] is False, "no_real_incidents")
    require(diagnostic_demo["persistent_log_created"] is False, "no_persistent_logs")
    checks.append("diagnostic_cli")

    port = _free_loopback_port()
    # Rehearsal is local-only. Suppress the WSGI access logger to avoid
    # including transient URLs or environment context in the evidence file.
    server = subprocess.Popen(
        [sys.executable, "-m", "reliability_intelligence", "serve", "--port", str(port)],
        cwd=PROJECT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_server(server, port)
        checks.append("fresh_loopback_server")
        for path in UI_PATHS:
            code, headers, body = _http(port, path)
            require(code == 200, "ui_" + path)
            require(b"<main " in body, "ui_semantic_main_" + path)
            require(headers.get("Cache-Control") == "no-store", "ui_no_store_" + path)
            require(len(body) <= MAX_BODY_BYTES, "bounded_html_" + path)
        checks.append("five_navigable_ui_pages")

        code, headers, css = _http(port, "/assets/style.css")
        require(code == 200 and b".nav-item" in css, "local_stylesheet")
        require(headers.get("Content-Type", "").startswith("text/css"), "stylesheet_mime")
        checks.append("local_stylesheet")

        resources = ("status", "scope", "cases", "demo", "contract")
        received: dict[str, dict] = {}
        for path, resource in zip(API_PATHS, resources):
            code, headers, body = _http(port, path)
            require(headers.get("Content-Type", "").startswith("application/json"), "json_mime_" + resource)
            received[resource] = _json_document(code, body, resource)
            require(b"expected_review_label" not in body, "no_seeded_label_leak_" + resource)
        require(received["cases"]["count"] == EXPECTED_CASES, "api_synthetic_case_count")
        require(all(x["synthetic"] is True for x in received["cases"]["items"]), "api_synthetic_markers")
        require(received["demo"]["trace_sha256"] == cli_demo_a["trace_sha256"], "api_cli_trace_match")
        require(received["demo"]["real_human_review_performed"] is False, "api_no_real_reviewer")
        require(received["status"]["operational_data_loaded"] is False, "api_no_operational_data")
        require(received["contract"]["limits"]["write_endpoints"] is False, "api_no_write_methods")
        checks.append("five_versioned_api_resources")

        for path in ("/", "/api/v1/status", "/api/v1/demo"):
            get_code, get_headers, get_body = _http(port, path)
            head_code, head_headers, head_body = _http(port, path, "HEAD")
            require(head_code == get_code, "head_status_" + path)
            require(head_body == b"", "head_empty_" + path)
            require(head_headers["Content-Length"] == str(len(get_body)), "head_length_" + path)
        checks.append("http_head_semantics")

        post, post_headers, _ = _http(port, "/api/v1/demo", "POST")
        require(post == 405, "http_post_rejected")
        require(post_headers.get("Allow") == "GET, HEAD", "http_allow_header")
        require(post_headers.get("X-Diagnostic-Code") == "method_not_allowed", "http_error_code")
        bad_version, _, _ = _http(port, "/api/v2/status")
        require(bad_version == 404, "unsupported_version_404")
        unknown_page, _, _ = _http(port, "/unlisted-page")
        require(unknown_page == 404, "unknown_ui_404")
        checks.append("read_only_negative_http")

        code, _, rendered = _http(port, "/workflow")
        require(code == 200 and cli_demo_a["trace_sha256"].encode("ascii") in rendered,
                "browser_cli_trace_consistency")
        require(b"Fictional reviewer role only" in rendered, "reviewer_role_disclosure")
        checks.append("workflow_review_disclosure")
    finally:
        server.terminate()
        try:
            server.wait(timeout=4)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=4)

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    record = {
        "increment": "V9",
        "evidence_type": "automated_clean_checkout_replay",
        "result": "pass",
        "checks_passed": checks,
        "check_count": len(checks),
        "test_environment": "clean_checkout_local_loopback",
        "python_version": platform.python_version(),
        "git_sha": os.environ.get("GITHUB_SHA", "not_provided"),
        "source_fixture_count": EXPECTED_CASES,
        "scripted_reviewer_dispositions": EXPECTED_SCRIPTED,
        "reproducible_demo_trace_sha256": cli_demo_a["trace_sha256"],
        "replay_evidence_sha256": hashlib.sha256(
            json.dumps(checks, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "independent_human_reviewer": False,
        "formal_review_accepted": False,
        "customer_data_used": False,
        "production_approved": False,
        "external_customer_or_ot_connections": False,
        "business_impact_measured": False,
        "notes": (
            "Automated independent-runner rehearsal is not an independent HUMAN review. "
            "Human reviewer checklist and signed record are required for V9 acceptance."
        ),
    }
    REPORT_PATH.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("V9_REPLAY: " + json.dumps({
        "result": "pass",
        "checks": record["check_count"],
        "case_count": EXPECTED_CASES,
        "trace_sha256": record["reproducible_demo_trace_sha256"],
        "independent_human_reviewer": False,
        "formal_review_accepted": False,
    }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, TypeError, OSError, URLError,
            subprocess.SubprocessError, json.JSONDecodeError) as error:
        # Never expose any raw child diagnostics or credentials to the CI log.
        print("V9_REPLAY_FAILED: " + type(error).__name__, file=sys.stderr)
        raise SystemExit(1) from None
