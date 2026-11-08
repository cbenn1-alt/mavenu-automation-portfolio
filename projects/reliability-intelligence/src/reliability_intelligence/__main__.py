"""Local V2 charter/status CLI: zero customer connections and zero write path."""

import argparse
import json

from . import __version__
from .charter import InvalidCharter, load_charter


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mavenu-reliability-v2")
    parser.add_argument("command", nargs="?", choices=("status", "charter", "validate"), default="status")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        charter = load_charter()
    except InvalidCharter as error:
        parser.exit(2, f"CHARTER INVALID: {error}\n")
    if args.command == "validate":
        payload = {"valid_contract": True, "business_approved": False, "external_connections": False}
    elif args.command == "charter":
        payload = charter
    else:
        payload = {
            "product": charter["product"], "version": __version__, "increment": "V2",
            "state": charter["state"], "business_approved": False,
            "production_ready": False, "customer_data_authorized": False,
            "external_integrations_enabled": False, "ot_writes_enabled": False,
            "measured_effectiveness": False,
        }
    if args.json or args.command == "charter":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{charter['product']} / V2 / {charter['state']}")
        print("Synthetic-only problem and outcome charter; NOT customer-approved.")
        print("No OT writes, customer data, AI model, deployment, or ROI proof.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
