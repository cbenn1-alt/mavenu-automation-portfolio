#!/usr/bin/env python3
"""Run the Mavenu automation portfolio web app (stdlib only).

Usage:
    python run.py [--port 8080] [--db ./data/mavenu.db]

Environment variables (see .env.example) take precedence over nothing —
flags override env vars.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from wsgiref.simple_server import make_server

from mavenu.config import load_settings
from mavenu.events import log_system_event
from mavenu.web import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Mavenu automation portfolio")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--db", default=None)
    args = parser.parse_args()

    if args.port:
        os.environ["MAVENU_PORT"] = str(args.port)
    if args.db:
        os.environ["MAVENU_DB_PATH"] = args.db

    settings = load_settings()
    app = create_app(settings)
    log_system_event("app.started", {"port": settings.port, "db": settings.db_path})
    print(f"Mavenu portfolio on http://localhost:{settings.port}/  (Ctrl-C to stop)")
    make_server("", settings.port, app).serve_forever()


if __name__ == "__main__":
    main()
