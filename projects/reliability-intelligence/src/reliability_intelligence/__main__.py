"""Local V8 regression-verified synthetic prototype with safe diagnostics."""

import argparse
import json

from . import __version__
from .charter import InvalidCharter, load_charter
from .web import serve_local
from .workflow import run_demo
from .fixtures import InvalidFixture
from . import diagnostics


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mavenu-reliability")
    parser.add_argument("command", nargs="?", choices=("status", "charter", "validate", "serve", "demo", "diagnose"), default="status")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--port", type=int, default=8765, help="loopback UI port (1024-65535)")
    args = parser.parse_args(argv)
    try:
        charter = load_charter()
    except InvalidCharter:
        diagnostics.emit("cli_charter_invalid", stage="charter", surface="cli")
        parser.exit(2, "CHARTER INVALID: requirements contract unavailable.\n")
    if args.command == "diagnose":
        examples = diagnostics.diagnostic_demo()
        if args.json:
            print(json.dumps(examples, indent=2, sort_keys=True))
        else:
            print(f"V7 simulated negative-path catalog: {examples['sample_count']} categories")
            print("No customer data, real incidents, or persistent logs.")
        return 0
    if args.command == "serve":
        if not 1024 <= args.port <= 65535:
            parser.error("--port must be 1024-65535")
        serve_local(args.port)
        return 0
    if args.command == "demo":
        try:
            report = run_demo(charter)
        except InvalidFixture:
            diagnostics.emit("cli_demo_invalid", stage="cli", surface="cli")
            parser.exit(2, "Synthetic demo inputs invalid; replay stopped.\n")
        if args.json:
            print(json.dumps(report, sort_keys=True, indent=2))
        else:
            print(f"V6 synthetic replay: {report['case_count']} fabricated cases; {report['scripted_disposition_count']} scripted dispositions")
            print(f"Trace SHA256: {report['trace_sha256']}")
            print("In-memory only; no real human approval or external work orders.")
        return 0
    if args.command == "validate":
        payload = {"valid_contract": True, "business_approved": False, "external_connections": False}
    elif args.command == "charter":
        payload = charter
    else:
        payload = {
            "product": charter["product"], "version": __version__, "increment": "V8",
            "charter_increment": charter["increment"], "state": charter["state"],
            "business_approved": False, "production_ready": False,
            "customer_data_authorized": False,
            "external_integrations_enabled": False, "ot_writes_enabled": False,
            "measured_effectiveness": False,
            "ui_routes": ["/", "/workbench", "/workflow", "/evaluation", "/governance"],
            "ui_mode": "loopback_only",
            "api_version": "v1",
            "api_schema_version": "1.3.0",
            "diagnostic_schema_version": "1.0.0",
            "diagnostic_logs": "allowlisted_json_to_process_stderr_only",
            "diagnostic_logs_persistent": False,
            "fixtures_mode": "versioned_local_synthetic_only",
            "workflow_mode": "scripted_synthetic_replay_only",
            "api_routes": ["/api/v1/status", "/api/v1/scope", "/api/v1/cases", "/api/v1/demo", "/api/v1/contract"],
        }
    if args.json or args.command == "charter":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{charter['product']} / V8 / {charter['state']}")
        print("Local synthetic-only navigation shell; NOT customer-approved.")
        print("No OT writes, customer data, AI model, deployment, or ROI proof.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
