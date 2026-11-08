"""Local V3 charter/status CLI and loopback-only UI shell."""

import argparse
import json

from . import __version__
from .charter import InvalidCharter, load_charter
from .web import serve_local


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mavenu-reliability")
    parser.add_argument("command", nargs="?", choices=("status", "charter", "validate", "serve"), default="status")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--port", type=int, default=8765, help="loopback UI port (1024-65535)")
    args = parser.parse_args(argv)
    try:
        charter = load_charter()
    except InvalidCharter as error:
        parser.exit(2, f"CHARTER INVALID: {error}\n")
    if args.command == "serve":
        if not 1024 <= args.port <= 65535:
            parser.error("--port must be 1024-65535")
        serve_local(args.port)
        return 0
    if args.command == "validate":
        payload = {"valid_contract": True, "business_approved": False, "external_connections": False}
    elif args.command == "charter":
        payload = charter
    else:
        payload = {
            "product": charter["product"], "version": __version__, "increment": "V3",
            "charter_increment": charter["increment"], "state": charter["state"],
            "business_approved": False, "production_ready": False,
            "customer_data_authorized": False,
            "external_integrations_enabled": False, "ot_writes_enabled": False,
            "measured_effectiveness": False,
            "ui_routes": ["/", "/workbench", "/evaluation", "/governance"],
            "ui_mode": "loopback_only",
        }
    if args.json or args.command == "charter":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{charter['product']} / V3 / {charter['state']}")
        print("Local synthetic-only navigation shell; NOT customer-approved.")
        print("No OT writes, customer data, AI model, deployment, or ROI proof.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
