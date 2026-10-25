"""WSGI web application: portfolio hub + Project 01 pages and JSON API.

Standard library only (wsgiref-style callable). No framework, no assets,
no external requests — the whole UI is rendered server-side.
"""
from __future__ import annotations

import html
import json
import os
import re
import sqlite3
import uuid
from decimal import Decimal
from typing import Any, Callable, Optional
from urllib.parse import parse_qsl

from . import leads as lead_service
from . import missed_calls as mc_service
from . import requests_approval as request_service
from . import cadence as cadence_service
from . import estimates as estimate_service
from . import reports as report_service
from . import templates as template_service
from . import reactivation as rx_service
from . import attribution as attr_service
from . import booking_agent as ba_service
from . import webhooks as wh_service
from . import router as wh_router
from . import delivery as wh_delivery
from . import reconcile as recon_service
from . import matching as match_service
from . import entity_resolution as er_service
from . import firewall as fw_service
from . import netsec as ns_service
from . import ossec as os_service
from . import crypto_demo as crypto_service
from . import forensics as for_service
from . import custody as custody_service
from . import kpi_pipeline as kpi_service
from . import netforensics as nf_service
from . import risk as risk_service
from . import safeguard as sg_service
from . import kpi_defs as kpi_definitions
from . import reviews as review_service
from . import tagger as review_tagger
from . import dispatch as dispatch_service
from . import dispatch_model as dispatch_model
from .booking_agent import BookingError, DemoBookingAdapter
from .classifier import DeterministicDemoClassifier
from .dialogue import ScriptedDemoPolicy
from .config import Settings
from .db import get_connection, run_migrations
from .events import log_system_event
from .leads import BookingError, FakeBookingAdapter  # noqa: F401 (re-exported for tests)
from .requests_approval import (
    ApprovalRoleError,
    InvalidDecision,
    REQUEST_TYPES,
)
from .templates import TemplateRenderError
from .urgency import DeterministicDemoScorer
from .validation import SERVICES, ValidationError
from .workflow import (
    CALL_WORKFLOW, ESTIMATE_WORKFLOW, InvalidTransition, LEAD_WORKFLOW,
    REQUEST_WORKFLOW, EXCEPTION_WORKFLOW,
)

STATUS_TEXT = {
    200: "200 OK", 201: "201 Created", 303: "303 See Other",
    400: "400 Bad Request", 401: "401 Unauthorized", 404: "404 Not Found",
    409: "409 Conflict", 422: "422 Unprocessable Entity",
    500: "500 Internal Server Error",
}

# S03: synthetic forensic fixtures ("disk images") live here. Override with
# MAVENU_SYNTHETIC_CASES. Every file under this directory is generated
# synthetic fixture material — never a real device image.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYNTHETIC_CASES_DIR = os.environ.get(
    "MAVENU_SYNTHETIC_CASES", os.path.join(_REPO_ROOT, "synthetic_cases"))

BANNER = (
    '<div class="banner">SYNTHETIC DEMO DATA — no real people, no real businesses. '
    'All names, numbers and addresses on this site are fictional.</div>'
)

CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:900px;
margin:0 auto;padding:24px;color:#1a1a1a;line-height:1.5}
.banner{background:#fff3cd;border:1px solid #e6c200;padding:10px 14px;border-radius:6px;
margin-bottom:20px;font-size:14px}
.card{border:1px solid #ddd;border-radius:8px;padding:16px;margin:12px 0}
table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:8px;text-align:left}
th{background:#f5f5f5}.state{font-weight:bold;text-transform:uppercase;font-size:12px;
padding:2px 8px;border-radius:10px;background:#eef;display:inline-block}
form label{display:block;margin:10px 0 4px}input,select,textarea{width:100%;padding:8px;
border:1px solid #bbb;border-radius:4px;box-sizing:border-box}
button{background:#0b5fff;color:#fff;border:0;padding:10px 18px;border-radius:6px;cursor:pointer}
.errors{color:#a00}.error-list{background:#fdecea;border:1px solid #e0a3a3;padding:10px;
border-radius:6px;margin-bottom:12px}
nav a{margin-right:16px}.timeline{font-size:14px}.timeline li{margin-bottom:6px}
code{background:#f4f4f4;padding:2px 6px;border-radius:4px}
"""


def _page(title: str, body: str) -> bytes:
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Mavenu Portfolio</title><style>{CSS}</style></head>
<body>{BANNER}<nav><a href="/">Hub</a><a href="/project01">Project 01</a>
<a href="/project01/dashboard">P01 Dashboard</a><a href="/project02">Project 02</a>
<a href="/project02/dashboard">P02 Dashboard</a><a href="/project_q01">Q01</a>
<a href="/project_q01/queue">Q01 Queue</a><a href="/project_q01/dashboard">Q01 Dashboard</a>
<a href="/project_q02">Q02</a><a href="/project_q02/outbox">Q02 Outbox</a>
<a href="/project_q02/reports">Q02 Reports</a><a href="/project_q03">Q03</a>
<a href="/project_q03/outbox">Q03 Outbox</a><a href="/project_q03/attribution">Q03 Attribution</a>
<a href="/project_q04">Q04</a><a href="/project_q04/handoffs">Q04 Handoffs</a>
<a href="/project_q04/bookings">Q04 Bookings</a><a href="/project_q05">Q05</a>
<a href="/project_q05/exceptions">Q05 Exceptions</a>
<a href="/project_q05/reports">Q05 Reports</a><a href="/project_q06">Q06</a>
<a href="/project_q06/pairs">Q06 Pairs</a><a href="/project_q06/merges">Q06 Merges</a><a href="/project_q07">Q07</a><a href="/project_q07/locations">Q07 Locations</a><a href="/project_q07/quarantine">Q07 Quarantine</a><a href="/project_q07/kpi">Q07 KPIs</a><a href="/project_q07/restatements">Q07 Restatements</a><a href="/project_q08">Q08</a>
<a href="/project_q08/reviews">Q08 Reviews</a><a href="/project_q08/queues">Q08 Queues</a>
<a href="/project_q08/drafts">Q08 Drafts</a><a href="/project_q09">Q09</a>
<a href="/project_q09/overrides">Q09 Overrides</a><a href="/project_q10">Q10</a>
<a href="/project_q10/dead-letters">Q10 Dead-letters</a><a href="/project_s01">S01</a>
<a href="/project_s01/ruleset">S01 Rules</a><a href="/project_s01/runbook">S01 Runbook</a>
<a href="/project_s01/incidents">S01 Incidents</a>
<a href="/project_s02">S02</a><a href="/project_s02/concepts">S02 Concepts</a>
<a href="/project_s02/lab">S02 Lab</a><a href="/project_s02/findings">S02 Findings</a>
<a href="/project_s02/baselines">S02 Baselines</a><a href="/project_s03">S03</a><a href="/project_s04">S04</a><a href="/project_s04/register">S04 Register</a><a href="/project_s04/incidents">S04 Incidents</a><a href="/project_s05">S05</a>
<a href="/project_s05/primitives">S05 Primitives</a><a href="/project_s05/pitfalls">S05 Pitfalls</a>
<a href="/project_s05/keymgmt">S05 Key Mgmt</a><a href="/project_n01">N01</a>
<a href="/project_n01/sessions">N01 Sessions</a><a href="/project_n01/timeline">N01 Timeline</a>
<a href="/project_n01/anomalies">N01 Anomalies</a><a href="/project_n01/scoping">N01 Scoping</a>
<a href="/project_n01/report">N01 Report</a><a href="/project_n02">N02</a>
<a href="/project_n02/scales">N02 Scales</a><a href="/project_n02/register">N02 Register</a>
<a href="/project_n02/remediation">N02 Remediation</a><a href="/project_n02/residual">N02 Residual</a><a href="/project_n03">N03</a>
<a href="/project_n03/playbooks">N03 Playbooks</a><a href="/project_n03/cases">N03 Cases</a>
<a href="/project_n03/preservation">N03 Preservation</a><a href="/project_n03/reporting">N03 Reporting</a>
<a href="/project_n03/referrals">N03 Referrals</a></nav>
<h1>{title}</h1>{body}</body></html>"""
    return html.encode("utf-8")


def _json(status: int, payload: Any) -> tuple[int, list, bytes]:
    return status, [("Content-Type", "application/json")], json.dumps(payload).encode()


def _html(status: int, title: str, body: str) -> tuple[int, list, bytes]:
    return status, [("Content-Type", "text/html; charset=utf-8")], _page(title, body)


def _error_envelope(code: str, message: str, fields: Optional[dict] = None) -> dict:
    env: dict[str, Any] = {"error": {"code": code, "message": message}}
    if fields:
        env["error"]["fields"] = fields
    return env


def _stub_webhook_sink(name: str):
    """Always-success in-process stub endpoint for the Q10 demo.

    No network, no credentials — the honest stand-in for a real SaaS
    integration. Tests inject their own failing/succeeding callables.
    """
    def sink(delivery, envelope):
        return {"sink": name, "event_id": envelope.get("event_id"), "ok": True}
    sink.__name__ = "stub_sink_" + name.replace(":", "_").replace("-", "_")
    return sink


class App:
    def __init__(self, settings: Settings):
        self.settings = settings
        # Fresh connection per request keeps the demo simple and thread-safe enough.
        conn = get_connection(settings.db_path)
        applied = run_migrations(conn)
        review_service.ensure_lexicons(conn)
        conn.close()
        if applied:
            log_system_event("db.migrated", {"applied": applied})
        self.classifier = DeterministicDemoClassifier(
            threshold=settings.review_confidence_threshold
        )
        self.booking_adapter = FakeBookingAdapter()
        self.urgency_scorer = DeterministicDemoScorer()
        self.dialogue_policy = ScriptedDemoPolicy()
        self.q04_booking_adapter = DemoBookingAdapter()
        # Q10: stub endpoints are in-process callables — never real HTTP,
        # never real SaaS credentials. Always-success demo sinks.
        self.webhook_endpoints = {
            "stub:crm-sink": _stub_webhook_sink("stub:crm-sink"),
            "stub:calendar-sink": _stub_webhook_sink("stub:calendar-sink"),
            "stub:sheet-sink": _stub_webhook_sink("stub:sheet-sink"),
        }

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.settings.db_path)

    # -- WSGI entry -----------------------------------------------------
    def __call__(self, environ: dict, start_response: Callable) -> Any:
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/") or "/"
        try:
            status, headers, body = self.route(method, path, environ)
        except ValidationError as exc:
            status, headers, body = self._handle_validation_error(exc, environ)
        except KeyError as exc:
            status, headers, body = _json(404, _error_envelope("not_found", str(exc)))
        except Exception as exc:  # never leak internals to the client
            log_system_event("http.internal_error", {"path": path, "error": type(exc).__name__})
            status, headers, body = _json(
                500, _error_envelope("internal_error", "Something went wrong.")
            )
        start_response(STATUS_TEXT[status], headers)
        return [body]

    # -- routing ----------------------------------------------------------
    def route(self, method: str, path: str, environ: dict):
        if method == "GET" and path == "/":
            return self.hub()
        if method == "GET" and path == "/project01":
            return self.project_page()
        if method == "POST" and path == "/project01/leads":
            return self.form_submit(environ)
        if method == "GET" and path == "/project01/dashboard":
            return self.dashboard()
        m = re.fullmatch(r"/project01/leads/([A-Za-z0-9-]+)", path or "")
        if m and method == "GET":
            return self.lead_detail(m.group(1))
        if m and method == "POST":
            return self.lead_transition_form(m.group(1), environ)
        if method == "GET" and path == "/api/health":
            return _json(200, {"ok": True})
        if method == "GET" and path == "/api/stats":
            conn = self._conn()
            try:
                return _json(200, lead_service.stats(conn))
            finally:
                conn.close()
        if method == "POST" and path == "/api/leads":
            return self.api_create_lead(environ)
        m = re.fullmatch(r"/api/leads/([A-Za-z0-9-]+)", path or "")
        if m and method == "GET":
            return self.api_get_lead(m.group(1))
        mt = re.fullmatch(r"/api/leads/([A-Za-z0-9-]+)/transition", path or "")
        if mt and method == "POST":
            return self.api_transition(mt.group(1), environ)
        # ---- Project 02: request & approval automation ---------------------
        if method == "GET" and path == "/project02":
            return self.p02_form_page()
        if method == "POST" and path == "/project02/requests":
            return self.p02_form_submit(environ)
        if method == "GET" and path == "/project02/dashboard":
            return self.p02_dashboard()
        mr = re.fullmatch(r"/project02/requests/([A-Za-z0-9-]+)", path or "")
        if mr and method == "GET":
            return self.p02_detail(mr.group(1))
        if mr and method == "POST":
            return self.p02_decision_form(mr.group(1), environ)
        if method == "POST" and path == "/api/requests/sla-sweep":
            return self.api_sla_sweep()
        if method == "POST" and path == "/api/requests":
            return self.api_create_request(environ)
        mr = re.fullmatch(r"/api/requests/([A-Za-z0-9-]+)", path or "")
        if mr and method == "GET":
            return self.api_get_request(mr.group(1))
        msub = re.fullmatch(r"/api/requests/([A-Za-z0-9-]+)/submit", path or "")
        if msub and method == "POST":
            return self.api_submit_request(msub.group(1), environ)
        mdec = re.fullmatch(r"/api/requests/([A-Za-z0-9-]+)/decision", path or "")
        if mdec and method == "POST":
            return self.api_decide(mdec.group(1), environ)
        mcan = re.fullmatch(r"/api/requests/([A-Za-z0-9-]+)/cancel", path or "")
        if mcan and method == "POST":
            return self.api_cancel_request(mcan.group(1), environ)
        mful = re.fullmatch(r"/api/requests/([A-Za-z0-9-]+)/fulfill", path or "")
        if mful and method == "POST":
            return self.api_fulfill_request(mful.group(1), environ)
        mres = re.fullmatch(r"/api/requests/([A-Za-z0-9-]+)/resubmit", path or "")
        if mres and method == "POST":
            return self.api_resubmit_request(mres.group(1), environ)
        # ---- Q01: missed-call recovery --------------------------------------
        if method == "GET" and path == "/project_q01":
            return self.q01_form_page()
        if method == "POST" and path == "/project_q01/import":
            return self.q01_import_submit(environ)
        if method == "GET" and path == "/project_q01/queue":
            return self.q01_queue()
        if method == "GET" and path == "/project_q01/dashboard":
            return self.q01_dashboard()
        mc = re.fullmatch(r"/project_q01/calls/([A-Za-z0-9-]+)", path or "")
        if mc and method == "GET":
            return self.q01_detail(mc.group(1))
        if mc and method == "POST":
            return self.q01_action_form(mc.group(1), environ)
        if method == "POST" and path == "/api/missed-calls":
            return self.api_ingest_call(environ)
        if method == "POST" and path == "/api/missed-calls/import":
            return self.api_import_csv(environ)
        if method == "GET" and path == "/api/missed-calls/queue":
            return self.api_q01_queue()
        if method == "GET" and path == "/api/missed-calls/dashboard":
            return self.api_q01_dashboard()
        if method == "POST" and path == "/api/missed-calls/sla-sweep":
            return self.api_q01_sweep()
        mcc = re.fullmatch(r"/api/missed-calls/([A-Za-z0-9-]+)", path or "")
        if mcc and method == "GET":
            return self.api_get_call(mcc.group(1))
        mcl = re.fullmatch(r"/api/missed-calls/([A-Za-z0-9-]+)/claim", path or "")
        if mcl and method == "POST":
            return self.api_claim_call(mcl.group(1), environ)
        mco = re.fullmatch(r"/api/missed-calls/([A-Za-z0-9-]+)/outcome", path or "")
        if mco and method == "POST":
            return self.api_log_outcome(mco.group(1), environ)
        # ---- Q02: estimate follow-up automation -------------------------------
        if method == "GET" and path == "/project_q02":
            return self.q02_form_page()
        if method == "POST" and path == "/project_q02/estimates":
            return self.q02_create_submit(environ)
        if method == "GET" and path == "/project_q02/outbox":
            return self.q02_outbox()
        if method == "POST" and path == "/project_q02/outbox/flush":
            return self.q02_flush_submit()
        if method == "POST" and path == "/project_q02/cadence-run":
            return self.q02_cadence_run_submit()
        if method == "GET" and path == "/project_q02/reports":
            return self.q02_reports()
        if method == "GET" and path == "/project_q02/templates":
            return self.q02_templates()
        if method == "POST" and path == "/project_q02/templates":
            return self.q02_template_submit(environ)
        mq = re.fullmatch(r"/project_q02/estimates/([A-Za-z0-9-]+)", path or "")
        if mq and method == "GET":
            return self.q02_detail(mq.group(1))
        if mq and method == "POST":
            return self.q02_action_form(mq.group(1), environ)
        if method == "POST" and path == "/api/estimates":
            return self.api_create_estimate(environ)
        # Literal /api/estimates/* routes come before the parametrized one.
        if method == "GET" and path == "/api/estimates/outbox":
            return self.api_q02_outbox()
        if method == "GET" and path == "/api/estimates/reports/aging":
            return self.api_q02_aging()
        if method == "GET" and path == "/api/estimates/reports/win-loss":
            return self.api_q02_win_loss()
        if method == "GET" and path == "/api/estimates/reports/effectiveness":
            return self.api_q02_effectiveness()
        me = re.fullmatch(r"/api/estimates/([A-Za-z0-9-]+)", path or "")
        if me and method == "GET":
            return self.api_get_estimate(me.group(1))
        met = re.fullmatch(r"/api/estimates/([A-Za-z0-9-]+)/transition", path or "")
        if met and method == "POST":
            return self.api_transition_estimate(met.group(1), environ)
        meu = re.fullmatch(r"/api/estimates/([A-Za-z0-9-]+)/unsubscribe", path or "")
        if meu and method == "POST":
            return self.api_unsubscribe_estimate(meu.group(1), environ)
        if method == "GET" and path == "/api/estimate-templates":
            return self.api_list_templates()
        if method == "POST" and path == "/api/estimate-templates":
            return self.api_create_template(environ)
        mtt = re.fullmatch(r"/api/estimate-templates/([A-Za-z0-9_]+)/test-send", path or "")
        if mtt and method == "POST":
            return self.api_template_test_send(mtt.group(1), environ)
        if method == "GET" and path == "/api/cadence/rules":
            return self.api_list_rules()
        if method == "POST" and path == "/api/cadence/rules":
            return self.api_replace_rules(environ)
        if method == "POST" and path == "/api/cadence/run":
            return self.api_cadence_run()
        if method == "POST" and path == "/api/cadence/flush":
            return self.api_cadence_flush()
        # ---- Q03: customer reactivation engine -------------------------------
        if method == "GET" and path == "/project_q03":
            return self.q03_page()
        if method == "POST" and path == "/project_q03/score":
            return self.q03_score_submit()
        if method == "POST" and path == "/project_q03/winback-run":
            return self.q03_winback_submit()
        if method == "GET" and path == "/project_q03/segments":
            return self.q03_segments()
        if method == "GET" and path == "/project_q03/outbox":
            return self.q03_outbox()
        if method == "POST" and path == "/project_q03/outbox/flush":
            return self.q03_flush_submit()
        if method == "GET" and path == "/project_q03/attribution":
            return self.q03_attribution(environ)
        if method == "POST" and path == "/project_q03/holdout":
            return self.q03_holdout_submit(environ)
        if method == "GET" and path == "/project_q03/suppression":
            return self.q03_suppression()
        mrxc = re.fullmatch(r"/api/reactivation/customers/([A-Za-z0-9-]+)/jobs", path or "")
        if mrxc and method == "POST":
            return self.api_rx_add_job(mrxc.group(1), environ)
        mrxp = re.fullmatch(r"/api/reactivation/customers/([A-Za-z0-9-]+)", path or "")
        if mrxp and method == "GET":
            return self.api_rx_get_customer(mrxp.group(1))
        mrxs = re.fullmatch(r"/api/reactivation/customers/([A-Za-z0-9-]+)/suppression", path or "")
        if mrxs and method == "POST":
            return self.api_rx_suppression(mrxs.group(1), environ)
        mrxq = re.fullmatch(r"/api/reactivation/customers/([A-Za-z0-9-]+)/complaint", path or "")
        if mrxq and method == "POST":
            return self.api_rx_complaint(mrxq.group(1), environ)
        if method == "GET" and path == "/api/reactivation/customers":
            return self.api_rx_list_customers()
        if method == "POST" and path == "/api/reactivation/customers":
            return self.api_rx_create_customer(environ)
        if method == "POST" and path == "/api/reactivation/score":
            return self.api_rx_score()
        if method == "POST" and path == "/api/reactivation/winback-run":
            return self.api_rx_winback()
        if method == "GET" and path == "/api/reactivation/segments":
            return self.api_rx_segments()
        if method == "GET" and path == "/api/reactivation/outbox":
            return self.api_rx_outbox()
        if method == "POST" and path == "/api/reactivation/outbox/flush":
            return self.api_rx_flush()
        if method == "POST" and path == "/api/reactivation/holdout":
            return self.api_rx_holdout(environ)
        if method == "GET" and path == "/api/reactivation/attribution":
            return self.api_rx_attribution(environ)
        if method == "GET" and path == "/api/reactivation/suppression-audit":
            return self.api_rx_suppression_audit()
        if method == "GET" and path == "/api/reactivation/scoring-info":
            return self.api_rx_scoring_info()
        # ---- Q04: conversational booking agent --------------------------------
        if method == "GET" and path == "/project_q04":
            return self.q04_page()
        if method == "GET" and path == "/project_q04/handoffs":
            return self.q04_handoffs()
        if method == "GET" and path == "/project_q04/bookings":
            return self.q04_bookings()
        if method == "POST" and path == "/api/booking-agent/conversations":
            return self.api_ba_start()
        mba = re.fullmatch(r"/api/booking-agent/conversations/([A-Za-z0-9-]+)/turns", path or "")
        if mba and method == "POST":
            return self.api_ba_turn(mba.group(1), environ)
        mbag = re.fullmatch(r"/api/booking-agent/conversations/([A-Za-z0-9-]+)", path or "")
        if mbag and method == "GET":
            return self.api_ba_get(mbag.group(1))
        if method == "GET" and path == "/api/booking-agent/handoffs":
            return self.api_ba_handoffs()
        mbah = re.fullmatch(r"/api/booking-agent/handoffs/([0-9]+)", path or "")
        if mbah and method == "POST":
            return self.api_ba_handoff_status(mbah.group(1), environ)
        if method == "GET" and path == "/api/booking-agent/bookings":
            return self.api_ba_bookings()
        # ---- Q05: invoice reconciliation & exception reporter -----------------
        if method == "GET" and path == "/project_q05":
            return self.q05_upload_page()
        if method == "POST" and path == "/project_q05/upload":
            return self.q05_upload_submit(environ)
        if method == "POST" and path == "/project_q05/run-match":
            return self.q05_run_match_submit(environ)
        if method == "GET" and path == "/project_q05/exceptions":
            return self.q05_exceptions_page()
        mq = re.fullmatch(r"/project_q05/exceptions/([0-9]+)", path or "")
        if mq and method == "GET":
            return self.q05_exception_detail(mq.group(1))
        if mq and method == "POST":
            return self.q05_exception_form(mq.group(1), environ)
        if method == "GET" and path == "/project_q05/reports":
            return self.q05_reports_page()
        if method == "POST" and path == "/api/reconciliation/upload":
            return self.api_recon_upload(environ)
        if method == "POST" and path == "/api/reconciliation/run-match":
            return self.api_recon_run_match(environ)
        if method == "GET" and path == "/api/reconciliation/summary":
            return self.api_recon_summary()
        if method == "GET" and path == "/api/reconciliation/aging":
            return self.api_recon_aging()
        if method == "GET" and path == "/api/reconciliation/exceptions":
            return self.api_recon_exceptions(environ)
        mqe = re.fullmatch(r"/api/reconciliation/exceptions/([0-9]+)", path or "")
        if mqe and method == "GET":
            return self.api_recon_exception_get(mqe.group(1))
        mqet = re.fullmatch(r"/api/reconciliation/exceptions/([0-9]+)/transition", path or "")
        if mqet and method == "POST":
            return self.api_recon_exception_transition(mqet.group(1), environ)
        # ---- Q06: data quality & entity resolution ---------------------------
        if method == "GET" and path == "/project_q06":
            return self.q06_page()
        if method == "POST" and path == "/project_q06/upload":
            return self.q06_upload_submit(environ)
        if method == "POST" and path == "/project_q06/run":
            return self.q06_run_submit(environ)
        if method == "GET" and path == "/project_q06/pairs":
            return self.q06_pairs_page(environ)
        mq6p = re.fullmatch(r"/project_q06/pairs/([0-9]+)", path or "")
        if mq6p and method == "GET":
            return self.q06_pair_detail(mq6p.group(1))
        if method == "GET" and path == "/project_q06/merges":
            return self.q06_merges_page(environ)
        if method == "POST" and path == "/project_q06/merges":
            return self.q06_propose_submit(environ)
        mq6m = re.fullmatch(r"/project_q06/merges/([0-9]+)", path or "")
        if mq6m and method == "GET":
            return self.q06_merge_detail(mq6m.group(1))
        if mq6m and method == "POST":
            return self.q06_merge_action(mq6m.group(1), environ)
        if method == "POST" and path == "/api/entity-resolution/sources/upload":
            return self.api_er_upload(environ)
        if method == "POST" and path == "/api/entity-resolution/run":
            return self.api_er_run(environ)
        if method == "GET" and path == "/api/entity-resolution/stats":
            return self.api_er_stats()
        if method == "GET" and path == "/api/entity-resolution/pairs":
            return self.api_er_pairs(environ)
        mq6ap = re.fullmatch(r"/api/entity-resolution/pairs/([0-9]+)", path or "")
        if mq6ap and method == "GET":
            return self.api_er_pair_get(mq6ap.group(1))
        if method == "GET" and path == "/api/entity-resolution/proposals":
            return self.api_er_proposals(environ)
        if method == "POST" and path == "/api/entity-resolution/proposals":
            return self.api_er_propose(environ)
        mq6ag = re.fullmatch(r"/api/entity-resolution/proposals/([0-9]+)", path or "")
        if mq6ag and method == "GET":
            return self.api_er_proposal_get(mq6ag.group(1))
        mq6ac = re.fullmatch(r"/api/entity-resolution/proposals/([0-9]+)/confirm", path or "")
        if mq6ac and method == "POST":
            return self.api_er_proposal_confirm(mq6ac.group(1), environ)
        mq6ar = re.fullmatch(r"/api/entity-resolution/proposals/([0-9]+)/reject", path or "")
        if mq6ar and method == "POST":
            return self.api_er_proposal_reject(mq6ar.group(1), environ)
        mq6av = re.fullmatch(r"/api/entity-resolution/proposals/([0-9]+)/reverse", path or "")
        if mq6av and method == "POST":
            return self.api_er_proposal_reverse(mq6av.group(1), environ)
        mq6aa = re.fullmatch(r"/api/entity-resolution/proposals/([0-9]+)/audit", path or "")
        if mq6aa and method == "GET":
            return self.api_er_proposal_audit(mq6aa.group(1))
        # ---- Q07: multi-location KPI rollup pipeline ---------------------------
        if method == "GET" and path == "/project_q07":
            return self.q07_page(environ)
        if method == "GET" and path == "/project_q07/locations":
            return self.q07_locations_page()
        if method == "POST" and path == "/project_q07/locations":
            return self.q07_locations_submit(environ)
        if method == "POST" and path == "/project_q07/upload":
            return self.q07_upload_submit(environ)
        if method == "POST" and path == "/project_q07/compute":
            return self.q07_compute_submit(environ)
        if method == "GET" and path == "/project_q07/quarantine":
            return self.q07_quarantine_page(environ)
        if method == "GET" and path == "/project_q07/kpi":
            return self.q07_kpi_page(environ)
        mq7v = re.fullmatch(r"/project_q07/kpi/([0-9]+)", path or "")
        if mq7v and method == "GET":
            return self.q07_kpi_detail(mq7v.group(1))
        if method == "GET" and path == "/project_q07/restatements":
            return self.q07_restatements_page()
        if method == "POST" and path == "/api/kpi/locations":
            return self.api_kpi_location_create(environ)
        if method == "GET" and path == "/api/kpi/locations":
            return self.api_kpi_locations()
        if method == "POST" and path == "/api/kpi/upload":
            return self.api_kpi_upload(environ)
        if method == "POST" and path == "/api/kpi/compute":
            return self.api_kpi_compute(environ)
        if method == "GET" and path == "/api/kpi/dashboard":
            return self.api_kpi_dashboard(environ)
        mq7l = re.fullmatch(r"/api/kpi/values/([0-9]+)/lineage", path or "")
        if mq7l and method == "GET":
            return self.api_kpi_lineage(mq7l.group(1))
        if method == "GET" and path == "/api/kpi/quarantine":
            return self.api_kpi_quarantine(environ)
        if method == "GET" and path == "/api/kpi/alerts":
            return self.api_kpi_alerts()
        mq7a = re.fullmatch(r"/api/kpi/alerts/([0-9]+)/resolve", path or "")
        if mq7a and method == "POST":
            return self.api_kpi_alert_resolve(mq7a.group(1), environ)
        if method == "GET" and path == "/api/kpi/definitions":
            return self.api_kpi_definitions()
        if method == "POST" and path == "/api/kpi/definitions":
            return self.api_kpi_definition_update(environ)
        if method == "POST" and path == "/api/kpi/restate":
            return self.api_kpi_restate(environ)
        # ---- Q10: webhook integration hub ------------------------------------
        if method == "GET" and path == "/project_q10":
            return self.q10_page()
        if method == "GET" and path == "/project_q10/dead-letters":
            return self.q10_dead_letters_page()
        if method == "POST" and path == "/api/webhooks/events":
            return self.api_wh_receive(environ)
        if method == "GET" and path == "/api/webhooks/events":
            return self.api_wh_events(environ)
        if method == "GET" and path == "/api/webhooks/routes":
            return self.api_wh_routes_list()
        if method == "POST" and path == "/api/webhooks/routes":
            return self.api_wh_route_create(environ)
        if method == "POST" and path == "/api/webhooks/routes/dry-run":
            return self.api_wh_route_dryrun(environ)
        if method == "POST" and path == "/api/webhooks/routes/seed":
            return self.api_wh_routes_seed()
        if method == "GET" and path == "/api/webhooks/deliveries":
            return self.api_wh_deliveries(environ)
        if method == "POST" and path == "/api/webhooks/deliver/run":
            return self.api_wh_deliver_run()
        if method == "GET" and path == "/api/webhooks/dead-letters":
            return self.api_wh_dead_letters()
        if method == "GET" and path == "/api/webhooks/endpoints":
            return self.api_wh_endpoints()
        # ---- S01: network security (defensive lab) ---------------------------
        if method == "GET" and path == "/project_s01":
            return self.s01_page()
        if method == "GET" and path == "/project_s01/ruleset":
            return self.s01_ruleset_page()
        if method == "GET" and path == "/project_s01/runbook":
            return self.s01_runbook_page()
        if method == "GET" and path == "/project_s01/incidents":
            return self.s01_incidents_page()
        if method == "POST" and path == "/project_s01/seed":
            return self.s01_seed_submit(environ)
        if method == "GET" and path == "/api/netsec/topology":
            return self.api_ns_topology()
        if method == "GET" and path == "/api/netsec/rules":
            return self.api_ns_rules()
        if method == "POST" and path == "/api/netsec/evaluate":
            return self.api_ns_evaluate(environ)
        if method == "GET" and path == "/api/netsec/matrix":
            return self.api_ns_matrix()
        if method == "GET" and path == "/api/netsec/runbook":
            return self.api_ns_runbook()
        if method == "GET" and path == "/api/netsec/alerts":
            return self.api_ns_alerts()
        if method == "POST" and path == "/api/netsec/alerts":
            return self.api_ns_alert_ingest(environ)
        if method == "GET" and path == "/api/netsec/tuning":
            return self.api_ns_tuning()
        if method == "POST" and path == "/api/netsec/tuning":
            return self.api_ns_tuning_create(environ)
        if method == "GET" and path == "/api/netsec/incidents":
            return self.api_ns_incidents()
        if method == "POST" and path == "/api/netsec/incidents":
            return self.api_ns_incident_create(environ)
        if method == "POST" and path == "/api/netsec/seed":
            return self.api_ns_seed(environ)
        # ---- S02: OS architecture & vulnerabilities (simulated lab) ---------
        if method == "GET" and path == "/project_s02":
            return self.s02_page()
        if method == "GET" and path == "/project_s02/concepts":
            return self.s02_concepts_page()
        if method == "GET" and path == "/project_s02/lab":
            return self.s02_lab_page()
        if method == "GET" and path == "/project_s02/findings":
            return self.s02_findings_page()
        if method == "GET" and path == "/project_s02/baselines":
            return self.s02_baselines_page()
        if method == "POST" and path == "/project_s02/seed":
            return self.s02_seed_submit(environ)
        if method == "GET" and path == "/api/ossec/baselines":
            return self.api_os_baselines()
        if method == "GET" and path == "/api/ossec/findings":
            return self.api_os_findings()
        if method == "POST" and path == "/api/ossec/evaluate":
            return self.api_os_evaluate(environ)
        if method == "POST" and path == "/api/ossec/remediate":
            return self.api_os_remediate(environ)
        if method == "GET" and path == "/api/ossec/coverage":
            return self.api_os_coverage()
        if method == "POST" and path == "/api/ossec/seed":
            return self.api_os_seed(environ)
        # ---- S05: applied cryptography (educational demo surface) -------------
        if method == "GET" and path == "/project_s05":
            return self.s05_page()
        if method == "GET" and path == "/project_s05/primitives":
            return self.s05_primitives_page()
        if method == "GET" and path == "/project_s05/pitfalls":
            return self.s05_pitfalls_page()
        if method == "GET" and path == "/project_s05/keymgmt":
            return self.s05_keymgmt_page()
        if method == "POST" and path == "/project_s05/demo":
            return self.s05_demo_submit(environ)
        # ---- N01: network forensics (synthetic captures, lawful lab only) ---
        if method == "GET" and path == "/project_n01":
            return self.n01_page()
        if method == "POST" and path == "/project_n01/run":
            return self.n01_run_submit(environ)
        if method == "GET" and path == "/project_n01/sessions":
            return self.n01_sessions_page(environ)
        if method == "GET" and path == "/project_n01/timeline":
            return self.n01_timeline_page(environ)
        if method == "GET" and path == "/project_n01/anomalies":
            return self.n01_anomalies_page(environ)
        if method == "GET" and path == "/project_n01/scoping":
            return self.n01_scoping_page(environ)
        if method == "GET" and path == "/project_n01/report":
            return self.n01_report_page(environ)
        if method == "GET" and path == "/api/netforensics/captures":
            return self.api_nf_captures()
        if method == "POST" and path == "/api/netforensics/capture":
            return self.api_nf_capture(environ)
        if method == "GET" and path == "/api/netforensics/anomalies":
            return self.api_nf_anomalies(environ)
        if method == "GET" and path == "/api/netforensics/report":
            return self.api_nf_report(environ)
        # ---- N02: cyber risk assessment & management (synthetic workbook) --
        if method == "GET" and path == "/project_n02":
            return self.n02_page()
        if method == "GET" and path == "/project_n02/scales":
            return self.n02_scales_page()
        if method == "GET" and path == "/project_n02/register":
            return self.n02_register_page()
        if method == "GET" and path == "/project_n02/remediation":
            return self.n02_remediation_page()
        if method == "GET" and path == "/project_n02/residual":
            return self.n02_residual_page()
        if method == "POST" and path == "/project_n02/seed":
            return self.n02_seed_submit()
        # ---- N03: safeguard — victim-centered, lawful abuse-response framework --
        if method == "GET" and path == "/project_n03":
            return self.n03_page()
        if method == "GET" and path == "/project_n03/playbooks":
            return self.n03_playbooks_page()
        m = re.fullmatch(r"/project_n03/playbooks/([a-z0-9_]+)", path or "")
        if m and method == "GET":
            return self.n03_playbook_page(m.group(1))
        if method == "GET" and path == "/project_n03/cases":
            return self.n03_cases_page()
        m = re.fullmatch(r"/project_n03/cases/([0-9]+)", path or "")
        if m and method == "GET":
            return self.n03_case_page(m.group(1))
        if method == "GET" and path == "/project_n03/preservation":
            return self.n03_preservation_page(environ)
        if method == "GET" and path == "/project_n03/reporting":
            return self.n03_reporting_page()
        if method == "GET" and path == "/project_n03/referrals":
            return self.n03_referrals_page()
        if method == "POST" and path == "/project_n03/demo":
            return self.n03_demo_submit()
        if method == "GET" and path == "/api/safeguard/playbooks":
            return self.api_sg_playbooks()
        m = re.fullmatch(r"/api/safeguard/playbooks/([a-z0-9_]+)", path or "")
        if m and method == "GET":
            return self.api_sg_playbook(m.group(1))
        if method == "POST" and path == "/api/safeguard/cases":
            return self.api_sg_cases(environ)
        if method == "GET" and path == "/api/safeguard/cases":
            return self.api_sg_cases_list()
        m = re.fullmatch(r"/api/safeguard/cases/([0-9]+)", path or "")
        if m and method == "GET":
            return self.api_sg_case_detail(m.group(1))
        m = re.fullmatch(r"/api/safeguard/cases/([0-9]+)/checklist/([A-Za-z0-9\-_]+)",
                         path or "")
        if m and method == "POST":
            return self.api_sg_checklist_item(environ, m.group(1), m.group(2))
        m = re.fullmatch(r"/api/safeguard/cases/([0-9]+)/referrals", path or "")
        if m and method == "POST":
            return self.api_sg_referrals(environ, m.group(1))
        m = re.fullmatch(r"/api/safeguard/cases/([0-9]+)/findings", path or "")
        if m and method == "POST":
            return self.api_sg_findings(environ, m.group(1))
        if method == "GET" and path == "/api/safeguard/preservation":
            return self.api_sg_preservation(environ)
        if method == "GET" and path == "/api/safeguard/reporting-guide":
            return self.api_sg_reporting_guide()
        if method == "GET" and path == "/api/safeguard/referral-directory":
            return self.api_sg_referral_directory()
        if method == "POST" and path == "/api/safeguard/demo":
            return self.api_sg_demo()
        if method == "GET" and path == "/api/risk/assets":
            return self.api_risk_assets()
        if method == "GET" and path == "/api/risk/threats":
            return self.api_risk_threats()
        if method == "GET" and path == "/api/risk/scales":
            return self.api_risk_scales()
        if method == "GET" and path == "/api/risk/register":
            return self.api_risk_register()
        if method == "GET" and path == "/api/risk/controls":
            return self.api_risk_controls()
        if method == "GET" and path == "/api/risk/remediations":
            return self.api_risk_remediations()
        if method == "GET" and path == "/api/risk/residual":
            return self.api_risk_residual()
        if method == "POST" and path == "/api/risk/seed":
            return self.api_risk_seed()
        if method == "GET" and path == "/api/crypto/pitfalls":
            return self.api_crypto_pitfalls()
        if method == "POST" and path == "/api/crypto/hash":
            return self.api_crypto_hash(environ)
        if method == "POST" and path == "/api/crypto/hmac":
            return self.api_crypto_hmac(environ)
        if method == "POST" and path == "/api/crypto/password":
            return self.api_crypto_password(environ)
        if method == "POST" and path == "/api/crypto/encrypt":
            return self.api_crypto_encrypt(environ)
        if method == "POST" and path == "/api/crypto/decrypt":
            return self.api_crypto_decrypt(environ)
        if method == "GET" and path == "/api/crypto/keys":
            return self.api_crypto_keys()
        if method == "POST" and path == "/api/crypto/rotate":
            return self.api_crypto_rotate(environ)
        if method == "POST" and path == "/api/crypto/destroy":
            return self.api_crypto_destroy(environ)
        if method == "GET" and path == "/api/crypto/cert-design":
            return self.api_crypto_cert_design()
        # ---- S03: digital forensics (synthetic data only) -----------------------
        if method == "GET" and path == "/project_s03":
            return self.s03_page()
        if method == "GET" and path == "/project_s03/cases":
            return self.s03_cases_page()
        m = re.fullmatch(r"/project_s03/cases/([0-9]+)", path or "")
        if m and method == "GET":
            return self.s03_case_page(m.group(1))
        if method == "POST" and path == "/project_s03/demo":
            return self.s03_demo_submit(environ)
        if method == "POST" and path == "/api/forensics/cases":
            return self.api_for_cases(environ)
        if method == "GET" and path == "/api/forensics/cases":
            return self.api_for_cases_list()
        m = re.fullmatch(r"/api/forensics/cases/([0-9]+)", path or "")
        if m and method == "GET":
            return self.api_for_case_detail(m.group(1))
        if method == "POST" and path == "/api/forensics/demo":
            return self.api_for_demo(environ)
        m = re.fullmatch(r"/api/forensics/cases/([0-9]+)/acquire", path or "")
        if m and method == "POST":
            return self.api_for_acquire(environ, m.group(1))
        m = re.fullmatch(r"/api/forensics/cases/([0-9]+)/acquisitions/([0-9]+)/verify", path or "")
        if m and method == "GET":
            return self.api_for_verify(m.group(1), m.group(2))
        m = re.fullmatch(r"/api/forensics/cases/([0-9]+)/artifacts", path or "")
        if m and method == "GET":
            return self.api_for_artifacts(m.group(1))
        m = re.fullmatch(r"/api/forensics/cases/([0-9]+)/timeline", path or "")
        if m and method == "GET":
            return self.api_for_timeline(m.group(1))
        m = re.fullmatch(r"/api/forensics/cases/([0-9]+)/hypotheses", path or "")
        if m and method == "POST":
            return self.api_for_hypotheses(environ, m.group(1))
        m = re.fullmatch(r"/api/forensics/cases/([0-9]+)/report", path or "")
        if m and method in ("GET", "POST"):
            return self.api_for_report(environ, m.group(1))
        m = re.fullmatch(r"/api/forensics/cases/([0-9]+)/chain", path or "")
        if m and method == "GET":
            return self.api_for_chain(m.group(1))
        # ---- S04: forensic evidence management (synthetic case only) ----------
        if method == "GET" and path == "/project_s04":
            return self.s04_page()
        if method == "GET" and path == "/project_s04/register":
            return self.s04_register_page()
        m = re.fullmatch(r"/project_s04/items/([0-9]+)", path or "")
        if m and method == "GET":
            return self.s04_item_page(m.group(1))
        m = re.fullmatch(r"/project_s04/forms/([a-z_]+)", path or "")
        if m and method == "GET":
            return self.s04_form_page(m.group(1), environ)
        if method == "GET" and path == "/project_s04/incidents":
            return self.s04_incidents_page()
        if method == "POST" and path == "/project_s04/seed":
            return self.s04_seed_submit(environ)
        if method == "POST" and path == "/api/custody/items":
            return self.api_custody_intake(environ)
        if method == "GET" and path == "/api/custody/items":
            return self.api_custody_items_list()
        m = re.fullmatch(r"/api/custody/items/([0-9]+)", path or "")
        if m and method == "GET":
            return self.api_custody_item_detail(m.group(1))
        if method == "POST" and path == "/api/custody/transfers":
            return self.api_custody_transfer_initiate(environ)
        m = re.fullmatch(r"/api/custody/transfers/([0-9]+)/hash-out", path or "")
        if m and method == "POST":
            return self.api_custody_hash_out(environ, m.group(1))
        m = re.fullmatch(r"/api/custody/transfers/([0-9]+)/hash-in", path or "")
        if m and method == "POST":
            return self.api_custody_hash_in(environ, m.group(1))
        if method == "POST" and path == "/api/custody/access":
            return self.api_custody_access(environ)
        if method == "POST" and path == "/api/custody/dispositions":
            return self.api_custody_disposition(environ)
        if method == "GET" and path == "/api/custody/verify":
            return self.api_custody_verify()
        if method == "GET" and path == "/api/custody/incidents":
            return self.api_custody_incidents()
        if method == "POST" and path == "/api/custody/seed":
            return self.api_custody_seed(environ)
        mnsi = re.fullmatch(r"/api/netsec/incidents/([0-9]+)", path or "")
        if mnsi and method == "GET":
            return self.api_ns_incident_detail(mnsi.group(1))
        mnst = re.fullmatch(r"/api/netsec/incidents/([0-9]+)/transition",
                            path or "")
        if mnst and method == "POST":
            return self.api_ns_incident_transition(mnst.group(1), environ)
        mwe = re.fullmatch(r"/api/webhooks/events/([A-Za-z0-9-]+)", path or "")
        if mwe and method == "GET":
            return self.api_wh_event(mwe.group(1))
        mwr = re.fullmatch(r"/api/webhooks/routes/([0-9]+)", path or "")
        if mwr and method == "GET":
            return self.api_wh_route_get(mwr.group(1))
        if mwr and method == "PUT":
            return self.api_wh_route_update(mwr.group(1), environ)
        if mwr and method == "DELETE":
            return self.api_wh_route_delete(mwr.group(1))
        mwdl = re.fullmatch(r"/api/webhooks/dead-letters/([0-9]+)/replay", path or "")
        if mwdl and method == "POST":
            return self.api_wh_dead_letter_replay(mwdl.group(1))
        # ---- Q08: review & reputation monitor -------------------------------
        if method == "GET" and path == "/project_q08":
            return self.q08_page(environ)
        if method == "GET" and path == "/project_q08/reviews":
            return self.q08_reviews_page(environ)
        if method == "GET" and path == "/project_q08/queues":
            return self.q08_queues_page(environ)
        if method == "GET" and path == "/project_q08/drafts":
            return self.q08_drafts_page(environ)
        if method == "POST" and path == "/project_q08/ingest":
            return self.q08_ingest_submit(environ)
        if method == "POST" and path == "/project_q08/queues/resolve":
            return self.q08_queue_resolve_submit(environ)
        if method == "POST" and path == "/project_q08/drafts/generate":
            return self.q08_draft_generate_submit(environ)
        if method == "POST" and path == "/project_q08/drafts/decide":
            return self.q08_draft_decide_submit(environ)
        if method == "POST" and path == "/api/reviews/ingest":
            return self.api_reviews_ingest(environ)
        if method == "GET" and path == "/api/reviews":
            return self.api_reviews_list(environ)
        if method == "GET" and path == "/api/reviews/queues":
            return self.api_reviews_queues(environ)
        if method == "GET" and path == "/api/reviews/sla":
            return self.api_reviews_sla(environ)
        if method == "GET" and path == "/api/reviews/drafts":
            return self.api_reviews_drafts(environ)
        mrd = re.fullmatch(r"/api/reviews/([0-9]+)/draft", path or "")
        if mrd and method == "POST":
            return self.api_reviews_draft_generate(mrd.group(1), environ)
        mrda = re.fullmatch(r"/api/reviews/drafts/([0-9]+)/approve", path or "")
        if mrda and method == "POST":
            return self.api_reviews_draft_decide(mrda.group(1), True, environ)
        mrdr = re.fullmatch(r"/api/reviews/drafts/([0-9]+)/reject", path or "")
        if mrdr and method == "POST":
            return self.api_reviews_draft_decide(mrdr.group(1), False, environ)
        mrlx = re.fullmatch(r"/api/reviews/lexicons/([A-Za-z0-9._-]+)", path or "")
        if mrlx and method == "GET":
            return self.api_reviews_lexicon(mrlx.group(1))
        # ---- Q09: technician dispatch optimizer --------------------------
        if method == "GET" and path == "/project_q09":
            return self.q09_page(environ)
        if method == "POST" and path == "/project_q09/seed":
            return self.q09_seed_submit(environ)
        if method == "POST" and path == "/project_q09/run":
            return self.q09_run_submit(environ)
        if method == "GET" and path == "/project_q09/overrides":
            return self.q09_overrides_page(environ)
        if method == "POST" and path == "/project_q09/overrides":
            return self.q09_override_submit(environ)
        mq09r = re.fullmatch(r"/project_q09/runs/([0-9]+)", path or "")
        if mq09r and method == "GET":
            return self.q09_run_page(mq09r.group(1))
        if method == "POST" and path == "/api/dispatch/seed":
            return self.api_dispatch_seed(environ)
        if method == "GET" and path == "/api/dispatch/techs":
            return self.api_dispatch_techs()
        if method == "POST" and path == "/api/dispatch/techs":
            return self.api_dispatch_tech_create(environ)
        if method == "GET" and path == "/api/dispatch/jobs":
            return self.api_dispatch_jobs()
        if method == "POST" and path == "/api/dispatch/jobs":
            return self.api_dispatch_job_create(environ)
        if method == "POST" and path == "/api/dispatch/run":
            return self.api_dispatch_run(environ)
        if method == "GET" and path == "/api/dispatch/overrides":
            return self.api_dispatch_overrides()
        if method == "POST" and path == "/api/dispatch/overrides":
            return self.api_dispatch_override_create(environ)
        mq09ar = re.fullmatch(r"/api/dispatch/runs/([0-9]+)", path or "")
        if mq09ar and method == "GET":
            return self.api_dispatch_run_detail(mq09ar.group(1))
        return _json(404, _error_envelope("not_found", f"No route for {method} {path}"))

    # ---- Q08: review & reputation monitor ----------------------------------
    def _q08_error(self, exc: Exception):
        return _html(422, "Q08 — Review Monitor",
                     f"<p class='errors'>Error: {html.escape(str(exc))}</p>"
                     "<p><a href=\"/project_q08\">Back</a></p>")

    def _q08_query(self, environ: dict) -> dict:
        qs = environ.get("QUERY_STRING", "") or ""
        return dict(parse_qsl(qs, keep_blank_values=True))

    def q08_page(self, environ: dict):
        conn = self._conn()
        try:
            review_service.ensure_lexicons(conn)
            sla = review_service.sla_status(conn)
            summary = review_service.queue_summary(conn)
            n_reviews = conn.execute("SELECT COUNT(*) AS n FROM reviews").fetchone()["n"]
        finally:
            conn.close()
        rows = "".join(
            f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>"
            for k, v in sorted(summary["counts"].items()))
        sev = "".join(
            f"<tr><td>{html.escape(r['severity'])}</td>"
            f"<td>{html.escape(r['status'])}</td><td>{r['n']}</td></tr>"
            for r in sla["by_severity"])
        body = f"""
<div class="card"><h2>Q08 — Review &amp; Reputation Monitor</h2>
<p>Synthetic review events are tagged by a <strong>lexicon-based</strong>
sentiment/topic tagger (transparent word lists, not a learned model),
routed into triage queues with UTC SLA timers, and answered with
template-based response drafts that a human must approve. <strong>Nothing
posts itself</strong> — there is no send path in v1, by architecture.</p>
<ul>
<li>Reviews ingested: <strong>{n_reviews}</strong></li>
<li>Open queue entries: <strong>{sla['open']}</strong> ·
    overdue: <strong>{sla['overdue']}</strong> ·
    SLA escalations: <strong>{sla['escalations']}</strong></li>
</ul>
<p><a href="/project_q08/reviews">Reviews →</a> ·
<a href="/project_q08/queues">Triage queues →</a> ·
<a href="/project_q08/drafts">Response drafts →</a></p></div>
<div class="card"><h3>Queue counts</h3><table><tr><th>Queue / status</th><th>Count</th></tr>
{rows or '<tr><td colspan="2">No queue entries yet.</td></tr>'}</table></div>
<div class="card"><h3>By severity</h3><table>
<tr><th>Severity</th><th>Status</th><th>Count</th></tr>
{sev or '<tr><td colspan="3">—</td></tr>'}</table></div>
<div class="card"><h3>Ingest reviews (CSV)</h3>
<form method="post" action="/project_q08/ingest">
<label>CSV (columns: external_id,stars,title,body,reviewed_at,author)</label>
<textarea name="csv" rows="6" placeholder="r1,5,Great,Excellent work.,2026-10-23T10:00:00Z,Alice"></textarea>
<button type="submit">Ingest</button></form></div>
"""
        return _html(200, "Q08 — Review Monitor", body)

    def q08_reviews_page(self, environ: dict):
        q = self._q08_query(environ)
        sentiment = (q.get("sentiment") or "").strip() or None
        conn = self._conn()
        try:
            sql = """SELECT r.id, r.stars, r.title, r.author_mask, r.reviewed_at,
                            q.queue, q.severity, q.status AS qstatus
                     FROM reviews r LEFT JOIN review_queues q
                       ON q.review_id = r.id"""
            params: list = []
            if sentiment:
                sql += """ WHERE r.id IN (SELECT review_id FROM review_tags
                           WHERE kind = 'sentiment' AND label = ?)"""
                params.append(sentiment)
            sql += " ORDER BY r.id DESC LIMIT 200"
            rows = conn.execute(sql, params).fetchall()
            tag_rows = conn.execute(
                "SELECT review_id, kind, label, confidence FROM review_tags"
            ).fetchall()
        finally:
            conn.close()
        tags: dict[int, list] = {}
        for t in tag_rows:
            tags.setdefault(t["review_id"], []).append(
                f"{t['kind']}:{t['label']} ({t['confidence']:.2f})")
        tr = "".join(
            f"<tr><td>{r['id']}</td><td>{r['stars'] or '—'}</td>"
            f"<td>{html.escape(r['title'])}</td>"
            f"<td>{html.escape(r['author_mask'])}</td>"
            f"<td>{html.escape(', '.join(tags.get(r['id'], [])))}</td>"
            f"<td>{html.escape(r['queue'] or '—')}</td>"
            f"<td>{html.escape(r['severity'] or '—')}</td>"
            f"<td>{html.escape(r['qstatus'] or '—')}</td>"
            f"<td><form method='post' action='/project_q08/drafts/generate' "
            f"style='margin:0'><input type='hidden' name='review_id' value='{r['id']}'>"
            f"<select name='tone'><option>professional</option><option>warm</option>"
            f"<option>brief</option></select> "
            f"<button type='submit'>Draft reply</button></form></td></tr>"
            for r in rows)
        body = f"""
<div class="card"><h2>Q08 — Reviews</h2>
<p><a href="/project_q08">Dashboard</a> ·
<a href="/project_q08/queues">Queues</a> ·
<a href="/project_q08/drafts">Drafts</a></p>
<form method="get" action="/project_q08/reviews">
<label>Filter by sentiment</label>
<select name="sentiment"><option value="">(all)</option>
<option value="positive"{' selected' if sentiment == 'positive' else ''}>positive</option>
<option value="negative"{' selected' if sentiment == 'negative' else ''}>negative</option>
<option value="neutral"{' selected' if sentiment == 'neutral' else ''}>neutral</option>
</select> <button type="submit">Filter</button></form></div>
<div class="card"><table><tr><th>ID</th><th>★</th><th>Title</th><th>Author</th>
<th>Tags</th><th>Queue</th><th>Severity</th><th>Queue status</th><th></th></tr>
{tr or '<tr><td colspan="9">No reviews yet — ingest a CSV from the dashboard.</td></tr>'}
</table></div>
"""
        return _html(200, "Q08 — Reviews", body)

    def q08_queues_page(self, environ: dict):
        conn = self._conn()
        try:
            summary = review_service.queue_summary(conn)
        finally:
            conn.close()
        tr = "".join(
            f"<tr><td>{r['id']}</td><td>{html.escape(r['queue'])}</td>"
            f"<td>{html.escape(r['severity'])}</td>"
            f"<td>{html.escape(r['status'])}</td>"
            f"<td>{r['stars'] or '—'} ★ — {html.escape(r['title'])}</td>"
            f"<td>{html.escape(r['sla_due_at'])}</td>"
            f"<td>{'OVERDUE' if r['overdue'] else '—'}</td>"
            f"<td>{html.escape(r['claimed_by'] or '—')}</td>"
            f"<td>{'' if r['status'] == 'resolved' else f'''<form method="post"
              action="/project_q08/queues/resolve" style="margin:0">
              <input type="hidden" name="queue_id" value="{r['id']}">
              <input type="text" name="actor" placeholder="owner name" style="width:110px">
              <button type="submit">Resolve</button></form>'''}</td></tr>"
            for r in summary["queues"])
        body = f"""
<div class="card"><h2>Q08 — Triage Queues</h2>
<p><a href="/project_q08">Dashboard</a> ·
<a href="/project_q08/reviews">Reviews</a> ·
<a href="/project_q08/drafts">Drafts</a></p>
<p>SLA timers are UTC. Overdue entries are escalated by the SLA sweep;
resolving is a human action recorded in the audit trail.</p></div>
<div class="card"><table><tr><th>ID</th><th>Queue</th><th>Severity</th>
<th>Status</th><th>Review</th><th>SLA due (UTC)</th><th>Overdue</th>
<th>Resolved by</th><th></th></tr>
{tr or '<tr><td colspan="9">No queue entries.</td></tr>'}</table></div>
"""
        return _html(200, "Q08 — Triage Queues", body)

    def q08_drafts_page(self, environ: dict):
        conn = self._conn()
        try:
            drafts = conn.execute(
                """SELECT d.id, d.review_id, d.template_name, d.tone, d.body,
                          d.status, d.created_by, d.approved_by,
                          r.title, r.stars
                   FROM review_drafts d JOIN reviews r ON r.id = d.review_id
                   ORDER BY d.id DESC LIMIT 200"""
            ).fetchall()
        finally:
            conn.close()
        tr = ""
        for d in drafts:
            if d["status"] == "draft":
                action = (f"<form method='post' action='/project_q08/drafts/decide' "
                          f"style='margin:0'><input type='hidden' name='draft_id' "
                          f"value='{d['id']}'>"
                          f"<input type='text' name='approver' placeholder='approver' "
                          f"style='width:110px'> "
                          f"<button type='submit' name='decision' value='approve'>Approve</button> "
                          f"<button type='submit' name='decision' value='reject'>Reject</button>"
                          f"</form>")
            else:
                action = f"decided by {html.escape(d['approved_by'] or '—')}"
            tr += (f"<tr><td>{d['id']}</td><td>{d['review_id']}</td>"
                   f"<td>{d['stars'] or '—'} ★ — {html.escape(d['title'])}</td>"
                   f"<td>{html.escape(d['template_name'])}/{html.escape(d['tone'])}</td>"
                   f"<td>{html.escape(d['body'][:140])}…</td>"
                   f"<td><span class='state'>{d['status']}</span></td>"
                   f"<td>{action}</td></tr>")
        body = f"""
<div class="card"><h2>Q08 — Response Drafts</h2>
<p><a href="/project_q08">Dashboard</a> ·
<a href="/project_q08/reviews">Reviews</a> ·
<a href="/project_q08/queues">Queues</a></p>
<p>Drafts are generated from templates that contain <strong>no factual
claims</strong> (no dates, amounts, or promises). A human must approve or
reject each draft. <strong>Approval does not post anything</strong> — there
is no send path; an approved draft is cleared for a human to copy and send
manually.</p></div>
<div class="card"><table><tr><th>ID</th><th>Review</th><th>Template/tone</th>
<th>Draft</th><th>Status</th><th>Decision</th></tr>
{tr or '<tr><td colspan="6">No drafts yet — generate one from the Reviews page.</td></tr>'}
</table></div>
"""
        return _html(200, "Q08 — Response Drafts", body)

    def q08_ingest_submit(self, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"),
                              keep_blank_values=True))
        conn = self._conn()
        try:
            review_service.ensure_lexicons(conn)
            try:
                stats = review_service.ingest_csv(
                    conn, data.get("csv") or "", source="web_csv",
                    actor="web-form")
            except (ValueError, review_service.ReviewError, ValidationError) as exc:
                return self._q08_error(exc)
        finally:
            conn.close()
        note = (f"Ingested {stats['ingested']}, duplicates {stats['duplicates']}, "
                f"skipped {stats['skipped']}.")
        return _html(200, "Q08 — Ingest",
                     f"<p>{html.escape(note)}</p>"
                     "<p><a href=\"/project_q08\">Back to dashboard</a> · "
                     "<a href=\"/project_q08/reviews\">Reviews →</a></p>")

    def q08_queue_resolve_submit(self, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"),
                              keep_blank_values=True))
        conn = self._conn()
        try:
            try:
                review_service.resolve_queue(
                    conn, int(data.get("queue_id") or 0),
                    actor=(data.get("actor") or "web-form").strip() or "web-form")
            except (ValueError, review_service.ReviewError) as exc:
                return self._q08_error(exc)
        finally:
            conn.close()
        return 303, [("Location", "/project_q08/queues")], b""

    def q08_draft_generate_submit(self, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"),
                              keep_blank_values=True))
        conn = self._conn()
        try:
            try:
                review_service.generate_draft(
                    conn, int(data.get("review_id") or 0),
                    tone=(data.get("tone") or "professional").strip(),
                    created_by="web-form")
            except (ValueError, review_service.ReviewError) as exc:
                return self._q08_error(exc)
        finally:
            conn.close()
        return 303, [("Location", "/project_q08/drafts")], b""

    def q08_draft_decide_submit(self, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"),
                              keep_blank_values=True))
        conn = self._conn()
        try:
            try:
                review_service.decide_draft(
                    conn, int(data.get("draft_id") or 0),
                    approve=(data.get("decision") == "approve"),
                    approver=(data.get("approver") or "web-form").strip() or "web-form")
            except (ValueError, review_service.ReviewError) as exc:
                return self._q08_error(exc)
        finally:
            conn.close()
        return 303, [("Location", "/project_q08/drafts")], b""

    # ---- Q09: technician dispatch optimizer ------------------------------
    def _q09_error(self, exc: Exception):
        return _html(422, "Q09 — Dispatch Optimizer",
                     f"<p class='errors'>Error: {html.escape(str(exc))}</p>"
                     "<p><a href=\"/project_q09\">Back</a></p>")

    def _q09_form(self, environ: dict) -> dict:
        return dict(parse_qsl(self._read_body(environ).decode("utf-8"),
                              keep_blank_values=True))

    def q09_page(self, environ: dict):
        conn = self._conn()
        try:
            techs = dispatch_service.list_techs(conn)
            jobs = dispatch_service.list_jobs(conn)
            runs = conn.execute(
                "SELECT * FROM dispatch_runs ORDER BY id DESC LIMIT 20"
            ).fetchall()
            latest_id = runs[0]["id"] if runs else None
        finally:
            conn.close()
        run_rows = "".join(
            f"<tr><td><a href=\"/project_q09/runs/{r['id']}\">run {r['id']}</a></td>"
            f"<td>{html.escape(r['solver'])}</td>"
            f"<td>{r['assigned_count']}</td><td>{r['infeasible_count']}</td>"
            f"<td>{r['total_cost']:.0f}</td><td>{r['baseline_cost']:.0f}</td>"
            f"<td>{r['cost_gap_pct']:+.1f}%</td>"
            f"<td>{html.escape(r['created_at'])}</td></tr>"
            for r in runs)
        latest_link = (f"<p><a href=\"/project_q09/runs/{latest_id}\">"
                       f"Latest run detail →</a></p>" if latest_id else "")
        body = f"""<div class="card"><h2>Q09 — Technician Dispatch Optimizer</h2>
<p>Synthetic dispatch day: greedy + local-improvement heuristic proposes an
assignment, explains every choice with reason codes, and reports its honest
gap versus a nearest-available baseline. The heuristic is <b>not</b>
optimal — the gap is measured, not marketed. Dispatchers can pin/reassign
jobs; every override is logged with its reason.</p>
<p><b>{len(techs)}</b> techs · <b>{len(jobs)}</b> jobs · {len(runs)} runs</p>
<p><a href="/project_q09/overrides">Dispatcher overrides →</a></p>{latest_link}</div>
<div class="card"><h3>Load synthetic demo day</h3>
<form method="post" action="/project_q09/seed">
<label>Seed <input name="seed" value="7"></label>
<label>Techs <input name="n_techs" value="6"></label>
<label>Jobs <input name="n_jobs" value="24"></label>
<button type="submit">Seed fixtures</button></form>
<p>Deterministic: the same seed always builds the same day. All names, zones
and jobs are fabricated.</p></div>
<div class="card"><h3>Run the solver</h3>
<form method="post" action="/project_q09/run">
<button type="submit">Solve current techs + jobs</button></form>
<p>Runs greedy + local improvement side-by-side with the nearest-available
baseline, honors dispatcher pins, and records the infeasibility report.</p></div>
<div class="card"><h3>Recent runs</h3>
<table><tr><th>Run</th><th>Solver</th><th>Assigned</th><th>Infeasible</th>
<th>Cost</th><th>Baseline</th><th>Gap</th><th>At</th></tr>
{run_rows or "<tr><td colspan='8'>No runs yet.</td></tr>"}</table></div>
<p><a href="/">Hub</a></p>"""
        return _html(200, "Q09 — Dispatch Optimizer", body)

    def q09_seed_submit(self, environ: dict):
        data = self._q09_form(environ)
        try:
            seed = int(data.get("seed") or 7)
            n_techs = int(data.get("n_techs") or 6)
            n_jobs = int(data.get("n_jobs") or 24)
            if not (1 <= n_techs <= 50 and 1 <= n_jobs <= 500):
                raise ValueError("out of range")
        except ValueError as exc:
            return self._q09_error(exc)
        conn = self._conn()
        try:
            dispatch_service.seed_demo(conn, seed=seed, n_techs=n_techs,
                                       n_jobs=n_jobs, actor="web-form")
        finally:
            conn.close()
        return 303, [("Location", "/project_q09")], b""

    def q09_run_submit(self, environ: dict):
        conn = self._conn()
        try:
            try:
                summary = dispatch_service.run_solver(conn, actor="web-form")
            except (ValidationError, dispatch_service.DispatchError,
                    KeyError) as exc:
                return self._q09_error(exc)
        finally:
            conn.close()
        return 303, [("Location",
                      f"/project_q09/runs/{summary['run_id']}")], b""

    def q09_run_page(self, run_id: str):
        conn = self._conn()
        try:
            try:
                detail = dispatch_service.run_detail(conn, int(run_id))
            except (ValueError, KeyError) as exc:
                return self._q09_error(exc)
        finally:
            conn.close()
        run = detail["run"]
        fmt = dispatch_model.fmt_clock
        assign_rows = "".join(
            f"<tr><td>{html.escape(a['job_ext'])}</td>"
            f"<td>{html.escape(a['zone'])}</td><td>{html.escape(a['skill'])}</td>"
            f"<td>{html.escape(a['tech_ext'])} ({html.escape(a['tech_name'])})</td>"
            f"<td>{fmt(a['scheduled_start'])}–{fmt(a['scheduled_end'])}</td>"
            f"<td>{a['travel_minutes']} min</td>"
            f"<td><code>{html.escape(', '.join(json.loads(a['reason_codes'])))}</code></td></tr>"
            for a in detail["assignments"])
        inf_rows = "".join(
            f"<tr><td>{html.escape(i['job_ext'])}</td>"
            f"<td>{html.escape(i['zone'])}</td><td>{html.escape(i['skill'])}</td>"
            f"<td><code>{html.escape(', '.join(json.loads(i['violated'])))}</code></td>"
            f"<td>{html.escape(i['detail'])}</td></tr>"
            for i in detail["infeasible"])
        body = f"""<div class="card"><h2>Dispatch run {run['id']}</h2>
<p>Solver <code>{html.escape(run['solver'])}</code> ·
params <code>{html.escape(run['policy_params'])}</code></p>
<table><tr><th></th><th>Heuristic</th><th>Baseline (nearest-available)</th></tr>
<tr><td>Total cost</td><td>{run['total_cost']:.1f}</td><td>{run['baseline_cost']:.1f}</td></tr>
<tr><td>Travel (min)</td><td>{run['total_travel']}</td><td>{run['baseline_travel']}</td></tr>
<tr><td colspan="3"><b>Honest gap: {run['cost_gap_pct']:+.2f}%</b>
(positive = heuristic beat the baseline on this day)</td></tr></table>
<p>Assigned <b>{run['assigned_count']}</b> · infeasible <b>{run['infeasible_count']}</b> ·
solved in {run['duration_ms']} ms by {html.escape(run['actor'])}</p></div>
<div class="card"><h3>Assignments ({len(detail['assignments'])})</h3>
<table><tr><th>Job</th><th>Zone</th><th>Skill</th><th>Tech</th><th>Slot</th>
<th>Travel in</th><th>Reason codes</th></tr>
{assign_rows or "<tr><td colspan='7'>None.</td></tr>"}</table></div>
<div class="card"><h3>Infeasibility report ({len(detail['infeasible'])})</h3>
<p>Jobs the solver could not place — explicit violated constraints, never
silent drops.</p>
<table><tr><th>Job</th><th>Zone</th><th>Skill</th><th>Violated</th><th>Detail</th></tr>
{inf_rows or "<tr><td colspan='5'>None — every job was placed.</td></tr>"}</table></div>
<p><a href="/project_q09">Q09 dashboard</a> · <a href="/">Hub</a></p>"""
        return _html(200, f"Q09 — Run {run['id']}", body)

    def q09_overrides_page(self, environ: dict):
        conn = self._conn()
        try:
            overrides = dispatch_service.list_overrides(conn)
            techs = dispatch_service.list_techs(conn)
            jobs = dispatch_service.list_jobs(conn)
        finally:
            conn.close()
        job_opts = "".join(
            f"<option value=\"{html.escape(j['external_id'])}\">"
            f"{html.escape(j['external_id'])} ({html.escape(j['skill'])}, "
            f"{html.escape(j['zone'])})</option>" for j in jobs)
        tech_opts = "".join(
            f"<option value=\"{html.escape(t['external_id'])}\">"
            f"{html.escape(t['external_id'])} — {html.escape(t['name'])}</option>"
            for t in techs)
        rows = "".join(
            f"<tr><td>{html.escape(o['job'])}</td>"
            f"<td>{html.escape(o['tech'] or '—')}</td>"
            f"<td>{html.escape(o['kind'])}</td>"
            f"<td>{html.escape(o['reason'])}</td>"
            f"<td>{html.escape(o['actor'])}</td>"
            f"<td>{html.escape(o['created_at'])}</td></tr>"
            for o in overrides)
        body = f"""<div class="card"><h2>Q09 — Dispatcher overrides</h2>
<p>Pin a job to a tech, reassign it, or release the pin. <b>A written reason
is required</b> — every override is append-only in the audit trail and is
honored as a hard constraint by the next solve.</p></div>
<div class="card"><h3>Record override</h3>
<form method="post" action="/project_q09/overrides">
<label>Job <select name="job_id">{job_opts}</select></label>
<label>Tech <select name="tech_id"><option value="">— (unpin only)</option>{tech_opts}</select></label>
<label>Kind <select name="kind"><option value="pin">pin</option>
<option value="reassign">reassign</option><option value="unpin">unpin</option></select></label>
<label>Reason (required) <input name="reason" placeholder="Why is the dispatcher overruling the solver?"></label>
<label>Dispatcher <input name="actor" value="dispatcher"></label>
<button type="submit">Record override</button></form></div>
<div class="card"><h3>Audit trail ({len(overrides)})</h3>
<table><tr><th>Job</th><th>Tech</th><th>Kind</th><th>Reason</th><th>By</th><th>At</th></tr>
{rows or "<tr><td colspan='6'>No overrides recorded.</td></tr>"}</table></div>
<p><a href="/project_q09">Q09 dashboard</a> · <a href="/">Hub</a></p>"""
        return _html(200, "Q09 — Overrides", body)

    def q09_override_submit(self, environ: dict):
        data = self._q09_form(environ)
        conn = self._conn()
        try:
            try:
                dispatch_service.record_override(
                    conn, (data.get("job_id") or "").strip(),
                    (data.get("tech_id") or "").strip() or None,
                    (data.get("kind") or "pin").strip(),
                    data.get("reason") or "",
                    actor=(data.get("actor") or "web-form").strip() or "web-form")
            except (ValidationError, KeyError) as exc:
                return self._q09_error(exc)
        finally:
            conn.close()
        return 303, [("Location", "/project_q09/overrides")], b""

    # ---- Q09 JSON API ------------------------------------------------------
    def api_dispatch_seed(self, environ: dict):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            result = dispatch_service.seed_demo(
                conn, seed=int(data.get("seed", 7)),
                n_techs=int(data.get("n_techs", 6)),
                n_jobs=int(data.get("n_jobs", 24)),
                actor=str(data.get("actor") or "api"))
        finally:
            conn.close()
        return _json(200, result)

    def api_dispatch_techs(self):
        conn = self._conn()
        try:
            return _json(200, {"techs": dispatch_service.list_techs(conn)})
        finally:
            conn.close()

    def api_dispatch_tech_create(self, environ: dict):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            result = dispatch_service.create_tech(
                conn, data, actor=str(data.get("actor") or "api"))
        finally:
            conn.close()
        return _json(201, result)

    def api_dispatch_jobs(self):
        conn = self._conn()
        try:
            return _json(200, {"jobs": dispatch_service.list_jobs(conn)})
        finally:
            conn.close()

    def api_dispatch_job_create(self, environ: dict):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            result = dispatch_service.create_job(
                conn, data, actor=str(data.get("actor") or "api"))
        finally:
            conn.close()
        return _json(201, result)

    def api_dispatch_run(self, environ: dict):
        data = self._read_json(environ)
        policy = dispatch_service.GreedyLocalImprovementPolicy(
            lateness_weight=float(data.get("lateness_weight", 0.5)),
            max_passes=int(data.get("max_passes", 20)))
        conn = self._conn()
        try:
            summary = dispatch_service.run_solver(
                conn, policy=policy, actor=str(data.get("actor") or "api"))
        finally:
            conn.close()
        return _json(200, summary)

    def api_dispatch_run_detail(self, run_id: str):
        conn = self._conn()
        try:
            try:
                detail = dispatch_service.run_detail(conn, int(run_id))
            except (ValueError, KeyError) as exc:
                return _json(404, _error_envelope("not_found", str(exc)))
            for a in detail["assignments"]:
                a["reason_codes"] = json.loads(a["reason_codes"])
            for i in detail["infeasible"]:
                i["violated"] = json.loads(i["violated"])
            return _json(200, detail)
        finally:
            conn.close()

    def api_dispatch_overrides(self):
        conn = self._conn()
        try:
            return _json(200,
                         {"overrides": dispatch_service.list_overrides(conn)})
        finally:
            conn.close()

    def api_dispatch_override_create(self, environ: dict):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            try:
                result = dispatch_service.record_override(
                    conn, str(data.get("job_id") or ""),
                    str(data.get("tech_id") or "") or None,
                    str(data.get("kind") or "pin"),
                    str(data.get("reason") or ""),
                    actor=str(data.get("actor") or "api"))
            except KeyError as exc:
                return _json(404, _error_envelope("not_found", str(exc)))
        finally:
            conn.close()
        return _json(201, result)

    # ---- Q08 JSON API ------------------------------------------------------
    def api_reviews_ingest(self, environ: dict):
        data = self._read_json(environ)
        events = data.get("events")
        if not isinstance(events, list):
            return _json(400, _error_envelope(
                "bad_request", "'events' must be a list of review events."))
        conn = self._conn()
        try:
            review_service.ensure_lexicons(conn)
            stats = {"ingested": 0, "duplicates": 0, "skipped": 0, "errors": []}
            for i, raw in enumerate(events):
                try:
                    out = review_service.ingest_event(
                        conn, raw if isinstance(raw, dict) else {},
                        actor=str(data.get("actor") or "api"))
                except (ValidationError, review_service.ReviewError) as exc:
                    stats["skipped"] += 1
                    stats["errors"].append({"index": i, "error": str(exc)})
                    continue
                stats["duplicates" if out["duplicate"] else "ingested"] += 1
        finally:
            conn.close()
        return _json(200, stats)

    def api_reviews_list(self, environ: dict):
        q = self._q08_query(environ)
        conn = self._conn()
        try:
            rows = conn.execute(
                """SELECT r.id, r.source, r.external_id, r.stars, r.title,
                          r.body, r.reviewed_at, r.author_mask, r.ingested_at,
                          q.queue, q.severity, q.status AS qstatus,
                          q.sla_due_at
                   FROM reviews r LEFT JOIN review_queues q
                     ON q.review_id = r.id
                   ORDER BY r.id DESC LIMIT 500"""
            ).fetchall()
            tag_rows = conn.execute(
                "SELECT review_id, kind, label, confidence, lexicon_version, "
                "detail FROM review_tags").fetchall()
        finally:
            conn.close()
        tags: dict[int, list] = {}
        for t in tag_rows:
            tags.setdefault(t["review_id"], []).append({
                "kind": t["kind"], "label": t["label"],
                "confidence": t["confidence"],
                "lexicon_version": t["lexicon_version"],
            })
        reviews_out = []
        for r in rows:
            row = dict(r)
            row["tags"] = tags.get(r["id"], [])
            reviews_out.append(row)
        sentiment = (q.get("sentiment") or "").strip()
        if sentiment:
            reviews_out = [
                r for r in reviews_out
                if any(t["kind"] == "sentiment" and t["label"] == sentiment
                       for t in r["tags"])]
        return _json(200, {"reviews": reviews_out})

    def api_reviews_queues(self, environ: dict):
        conn = self._conn()
        try:
            summary = review_service.queue_summary(conn)
        finally:
            conn.close()
        return _json(200, summary)

    def api_reviews_sla(self, environ: dict):
        conn = self._conn()
        try:
            status = review_service.sla_status(conn)
        finally:
            conn.close()
        return _json(200, status)

    def api_reviews_drafts(self, environ: dict):
        q = self._q08_query(environ)
        status = (q.get("status") or "").strip()
        conn = self._conn()
        try:
            sql = "SELECT * FROM review_drafts ORDER BY id DESC LIMIT 500"
            params: list = []
            if status:
                sql = "SELECT * FROM review_drafts WHERE status = ? ORDER BY id DESC LIMIT 500"
                params.append(status)
            drafts = [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()
        return _json(200, {"drafts": drafts})

    def api_reviews_draft_generate(self, review_id: str, environ: dict):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            review_service.ensure_lexicons(conn)
            try:
                out = review_service.generate_draft(
                    conn, int(review_id),
                    template_name=str(data.get("template") or "acknowledge_negative"),
                    tone=str(data.get("tone") or "professional"),
                    created_by=str(data.get("actor") or "api"))
            except (ValueError, review_service.ReviewError) as exc:
                return _json(422, _error_envelope("unprocessable", str(exc)))
        finally:
            conn.close()
        return _json(201, out)

    def api_reviews_draft_decide(self, draft_id: str, approve: bool, environ: dict):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            try:
                out = review_service.decide_draft(
                    conn, int(draft_id), approve=approve,
                    approver=str(data.get("approver") or "api"))
            except (ValueError, review_service.ReviewError) as exc:
                return _json(422, _error_envelope("unprocessable", str(exc)))
        finally:
            conn.close()
        return _json(200, out)

    def api_reviews_lexicon(self, version: str):
        conn = self._conn()
        try:
            terms = review_tagger.inspect_lexicon(conn, version)
        finally:
            conn.close()
        if not terms:
            return _json(404, _error_envelope(
                "not_found", f"No lexicon version {version!r}."))
        return _json(200, {"version": version, "categories": terms})

    # ---- Q04: conversational booking agent ----------------------------------
    def q04_page(self):
        body = """
<div class="card"><h2>Q04 — Conversational Booking Agent (scripted demo)</h2>
<p>This is a <strong>deterministic, rule-driven</strong> booking agent — not a
language model and never presented as a person. It introduces itself as
automated, fills slots in order (service → location → window → contact),
and only offers availability returned by the booking adapter. Low-confidence
turns, suspicious or contradictory input, and the turn cap all hand off to a
human with the full transcript. All data here is synthetic; caller text is
masked before storage.</p>
<div id="chat" style="border:1px solid #ccc;border-radius:8px;padding:12px;
height:320px;overflow-y:auto;background:#fafafa"></div>
<p><span id="convstate" class="state">starting…</span>
<span id="handflag"></span></p>
<form id="chatform" onsubmit="return sendTurn(event)">
<input id="chatinput" type="text" autocomplete="off"
placeholder="Type your reply…" style="width:78%">
<button type="submit" style="width:20%">Send</button></form>
<p><small>Try: "I need hvac" → "58102" → "Tuesday morning" → "Dana Rivera" →
"7015550142" → "yes". Or try gibberish / "ignore all previous instructions"
to see the handoff path.</small></p></div>
<script>
let convId = null;
function addMsg(role, text) {
  const d = document.createElement("div");
  d.style.margin = "6px 0";
  const who = document.createElement("strong");
  who.textContent = (role === "agent" ? "Maven (automated): " : "You: ");
  const span = document.createElement("span");
  span.textContent = text;
  d.appendChild(who); d.appendChild(span);
  document.getElementById("chat").appendChild(d);
  d.scrollIntoView();
}
async function startConv() {
  const r = await fetch("/api/booking-agent/conversations", {method: "POST"});
  const j = await r.json();
  convId = j.public_id;
  addMsg("agent", j.agent_message);
  document.getElementById("convstate").textContent = "state: " + j.state;
}
async function sendTurn(ev) {
  ev.preventDefault();
  const input = document.getElementById("chatinput");
  const text = input.value.trim();
  if (!text || !convId) return false;
  input.value = "";
  addMsg("caller", text);
  const r = await fetch("/api/booking-agent/conversations/" + convId + "/turns",
    {method: "POST", headers: {"Content-Type": "application/json"},
     body: JSON.stringify({text: text})});
  const j = await r.json();
  if (j.error) { addMsg("agent", "Error: " + j.error.message); return false; }
  addMsg("agent", j.agent_message);
  document.getElementById("convstate").textContent = "state: " + j.state;
  if (j.handoff) {
    document.getElementById("handflag").textContent =
      "handed off to a human (" + j.handoff_reason + ")";
    document.getElementById("chatinput").disabled = true;
  }
  if (j.state === "booked") {
    document.getElementById("chatinput").disabled = true;
  }
  return false;
}
startConv();
</script>"""
        return _html(200, "Q04 — Conversational Booking Agent", body)

    def q04_handoffs(self):
        conn = self._conn()
        try:
            queue = ba_service.handoff_queue(conn)
        finally:
            conn.close()
        rows = "".join(
            f"<tr><td>{h['id']}</td>"
            f"<td><a href=\"/api/booking-agent/conversations/{h['conversation_public_id']}\">"
            f"{h['conversation_public_id']}</a></td>"
            f"<td>{h['reason']}</td><td>{h['status']}</td>"
            f"<td>{h['created_at']}</td></tr>"
            for h in queue
        ) or "<tr><td colspan='5'>No open handoffs. Synthetic demo data only.</td></tr>"
        body = f"""
<div class="card"><h2>Q04 — Human handoff queue</h2>
<p>Escalation packages: masked transcript + extracted slots + reason.
Claim or resolve via <code>POST /api/booking-agent/handoffs/&lt;id&gt;</code>
with <code>{{"status": "claimed"|"resolved"}}</code>.</p>
<table><tr><th>ID</th><th>Conversation</th><th>Reason</th><th>Status</th><th>Created</th></tr>
{rows}</table></div>"""
        return _html(200, "Q04 — Handoff queue", body)

    def q04_bookings(self):
        conn = self._conn()
        try:
            bookings = ba_service.list_bookings(conn)
        finally:
            conn.close()
        rows = "".join(
            f"<tr><td>{b['booking_ref']}</td>"
            f"<td>{b['conversation_public_id']}</td>"
            f"<td>{b['adapter_name']}</td><td>{b['slot_when']}</td>"
            f"<td>{b['created_at']}</td></tr>"
            for b in bookings
        ) or "<tr><td colspan='5'>No bookings yet. Synthetic demo data only.</td></tr>"
        body = f"""
<div class="card"><h2>Q04 — Adapter-confirmed bookings</h2>
<p>Every row below exists only because the booking adapter confirmed it —
the agent cannot write a booking on its own.</p>
<table><tr><th>Reference</th><th>Conversation</th><th>Adapter</th><th>Slot</th><th>Created</th></tr>
{rows}</table></div>"""
        return _html(200, "Q04 — Bookings", body)

    def api_ba_start(self):
        conn = self._conn()
        try:
            result = ba_service.start_conversation(conn, policy=self.dialogue_policy)
        finally:
            conn.close()
        return _json(201, result)

    def api_ba_turn(self, public_id, environ):
        data = self._read_json(environ)
        text = data.get("text", "")
        if not isinstance(text, str) or not text.strip():
            return _json(422, _error_envelope("validation_failed",
                                             "Turn text must be a non-empty string."))
        conn = self._conn()
        try:
            try:
                result = ba_service.send_turn(
                    conn, public_id, text,
                    adapter=self.q04_booking_adapter,
                    policy=self.dialogue_policy,
                )
            except KeyError:
                return _json(404, _error_envelope("not_found",
                                                 f"No conversation {public_id!r}."))
            except ValueError as exc:
                return _json(409, _error_envelope("conflict", str(exc)))
        finally:
            conn.close()
        return _json(200, result)

    def api_ba_get(self, public_id):
        conn = self._conn()
        try:
            try:
                convo = ba_service.get_conversation(conn, public_id)
            except KeyError:
                return _json(404, _error_envelope("not_found",
                                                 f"No conversation {public_id!r}."))
        finally:
            conn.close()
        return _json(200, convo)

    def api_ba_handoffs(self):
        conn = self._conn()
        try:
            return _json(200, {"handoffs": ba_service.handoff_queue(conn)})
        finally:
            conn.close()

    def api_ba_handoff_status(self, handoff_id, environ):
        data = self._read_json(environ)
        status = data.get("status", "")
        conn = self._conn()
        try:
            try:
                ba_service.set_handoff_status(conn, int(handoff_id), status)
            except KeyError:
                return _json(404, _error_envelope("not_found",
                                                 f"No handoff {handoff_id!r}."))
            except ValueError as exc:
                return _json(422, _error_envelope("validation_failed", str(exc)))
        finally:
            conn.close()
        return _json(200, {"id": int(handoff_id), "status": status})

    def api_ba_bookings(self):
        conn = self._conn()
        try:
            return _json(200, {"bookings": ba_service.list_bookings(conn)})
        finally:
            conn.close()

    # ---- Q05: invoice reconciliation & exception reporter ----------------------
    def _q05_error(self, exc: Exception) -> tuple[int, list, bytes]:
        if isinstance(exc, KeyError):
            return _json(404, _error_envelope("not_found", str(exc)))
        if isinstance(exc, (InvalidTransition, ValueError)):
            return _json(409, _error_envelope("action_rejected", str(exc)))
        if isinstance(exc, ValidationError):
            return _json(422, _error_envelope("validation_failed",
                                             "The submission failed validation.",
                                             exc.field_errors))
        raise exc

    def q05_upload_page(self, errors: Optional[dict] = None):
        conn = self._conn()
        try:
            summary = recon_service.reconciliation_summary(conn)
        finally:
            conn.close()
        err_html = ""
        if errors:
            items = "".join(f"<li><strong>{k}</strong>: {v}</li>" for k, v in errors.items())
            err_html = f'<div class="error-list"><ul>{items}</ul></div>'
        body = f"""
<div class="card"><h2>Q05 — Invoice Reconciliation &amp; Exception Reporter</h2>
<p><strong>Synthetic data only.</strong> Ingest invoice and payment CSVs,
run the deterministic matcher (exact invoice-ID pass, then a scored fuzzy
pass with a documented threshold), and work the exception queue. Every
match carries its reasons; every total reconciles to source rows. Money is
computed with Decimal, never float. Write-off actions need a human — the
system proposes, never posts.</p>
{err_html}
<h3>Upload CSV</h3>
<form method="post" action="/project_q05/upload">
<label>Dataset
<select name="kind"><option value="invoices">invoices</option>
<option value="payments">payments</option></select></label>
<label>Your name (actor stamp) <input name="actor" placeholder="operator"></label>
<label>Paste CSV
<textarea name="csv" rows="8" placeholder="invoice_id,customer,amount,issued_date,due_date"></textarea></label>
<p><button type="submit">Ingest CSV</button></p>
</form>
<h3>Run the matcher</h3>
<form method="post" action="/project_q05/run-match">
<label>Your name (actor stamp) <input name="actor" placeholder="operator"></label>
<p><button type="submit">Run match (exact pass → fuzzy pass → exception rebuild)</button></p>
</form></div>
<div class="card"><h3>Current reconciliation snapshot</h3>
<table>
<tr><th>Invoiced</th><td>{summary["total_invoiced"]} ({summary["invoice_count"]} invoices)</td></tr>
<tr><th>Paid</th><td>{summary["total_paid"]} ({summary["payment_count"]} payments)</td></tr>
<tr><th>Matched payments</th><td>{summary["matched_payments"]}</td></tr>
<tr><th>Outstanding</th><td><strong>{summary["outstanding"]}</strong></td></tr>
<tr><th>Overpaid</th><td>{summary["overpaid"]}</td></tr>
<tr><th>Exceptions</th><td>{summary["exceptions_by_state"] or "none"}</td></tr>
</table>
<p><a href="/project_q05/exceptions">Exception queue →</a> ·
<a href="/project_q05/reports">Reports →</a></p></div>
"""
        return _html(200, "Q05 — Invoice Reconciliation", body)

    def q05_upload_submit(self, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        kind = (data.get("kind") or "").strip()
        csv_text = data.get("csv") or ""
        actor = (data.get("actor") or "public-form").strip() or "public-form"
        conn = self._conn()
        try:
            if kind == "invoices":
                result = recon_service.ingest_invoices(conn, csv_text, actor=actor)
            elif kind == "payments":
                result = recon_service.ingest_payments(conn, csv_text, actor=actor)
            else:
                return _html(422, "Q05 — Upload",
                              "<p>Choose <code>invoices</code> or <code>payments</code>.</p>")
        finally:
            conn.close()
        if result["errors"]:
            return self.q05_upload_page(errors={"rows": f"{len(result['errors'])} row(s) rejected; "
                                                         f"{result['inserted']} inserted."})
        return 303, [("Location", "/project_q05/exceptions")], b""

    def q05_run_match_submit(self, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        actor = (data.get("actor") or "public-form").strip() or "public-form"
        conn = self._conn()
        try:
            match_service.run_match(conn, actor=actor)
        finally:
            conn.close()
        return 303, [("Location", "/project_q05/exceptions")], b""

    def q05_exceptions_page(self):
        conn = self._conn()
        try:
            excs = recon_service.list_exceptions(conn)
        finally:
            conn.close()
        rows = "".join(
            f"<tr><td><a href=\"/project_q05/exceptions/{e['id']}\">{e['id']}</a></td>"
            f"<td>{html.escape(e['kind'])}</td>"
            f"<td>{html.escape(e['ref_public_id'])}</td>"
            f"<td><span class='state'>{e['state']}</span></td>"
            f"<td>{html.escape(e['actor'])}</td>"
            f"<td>{html.escape(e['created_at'])}</td></tr>"
            for e in excs
        ) or "<tr><td colspan=\"6\"><em>Queue is empty — ingest CSVs and run the matcher.</em></td></tr>"
        body = f"""
<div class="card"><h2>Q05 — Exception queue</h2>
<p>Every exception carries a suggested next action (see the detail view).
States: <code>open → investigating → resolved | written_off</code> —
enforced in code; illegal moves are rejected.</p>
<table><tr><th>ID</th><th>Kind</th><th>Reference</th><th>State</th>
<th>Last actor</th><th>Raised</th></tr>{rows}</table>
<p><a href="/project_q05">← Upload / run match</a> ·
<a href="/project_q05/reports">Reports →</a></p></div>
"""
        return _html(200, "Q05 — Exception queue", body)

    def q05_exception_detail(self, exc_id: str):
        conn = self._conn()
        try:
            excs = recon_service.list_exceptions(conn)
            exc = next((e for e in excs if e["id"] == int(exc_id)), None)
            if exc is None:
                raise KeyError(f"No exception with id {exc_id}.")
            history = recon_service.exception_history(conn, exc["id"])
        finally:
            conn.close()
        allowed = sorted(EXCEPTION_WORKFLOW.allowed_from(exc["state"]))
        buttons = "".join(
            f"""<form method="post" action="/project_q05/exceptions/{exc['id']}"
style="display:inline"><input type="hidden" name="to_state" value="{s}">
<button type="submit">{s}</button></form> """
            for s in allowed
        ) or "<em>Terminal state — no further transitions.</em>"
        hist_rows = "".join(
            f"<tr><td>{h['from_state'] or '—'}</td><td>{h['to_state']}</td>"
            f"<td>{html.escape(h['actor'])}</td>"
            f"<td>{html.escape(h['detail'])}</td><td>{h['created_at']}</td></tr>"
            for h in history
        )
        detail_pretty = html.escape(json.dumps(exc["detail"], indent=2, sort_keys=True))
        body = f"""
<div class="card"><h2>Q05 — Exception #{exc['id']}</h2>
<table>
<tr><th>Kind</th><td>{html.escape(exc['kind'])}</td></tr>
<tr><th>Reference</th><td>{html.escape(exc['ref_public_id'])} ({exc['ref_type']})</td></tr>
<tr><th>State</th><td><span class="state">{exc['state']}</span></td></tr>
<tr><th>Last actor</th><td>{html.escape(exc['actor'])}</td></tr>
</table>
<h3>Suggested next action</h3>
<p><strong>{html.escape(exc['suggested_action'])}</strong></p>
<h3>Details</h3>
<pre>{detail_pretty}</pre>
<h3>Transition</h3>
<p>{buttons}</p>
<h3>History (actor-stamped audit trail)</h3>
<table><tr><th>From</th><th>To</th><th>Actor</th><th>Detail</th><th>At</th></tr>
{hist_rows}</table>
<p><a href="/project_q05/exceptions">← Back to queue</a></p></div>
"""
        return _html(200, f"Q05 — Exception {exc['id']}", body)

    def q05_exception_form(self, exc_id: str, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        to_state = (data.get("to_state") or "").strip()
        actor = (data.get("actor") or "public-form").strip() or "public-form"
        conn = self._conn()
        try:
            try:
                recon_service.transition_exception(conn, int(exc_id), to_state,
                                                   actor=actor, detail="web form")
            except InvalidTransition as exc:
                conn.close()
                return _html(409, "Q05 — Transition rejected",
                             f"<p>Illegal transition: {html.escape(str(exc))}</p>"
                             f"<p><a href=\"/project_q05/exceptions/{exc_id}\">← Back</a></p>")
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return 303, [("Location", f"/project_q05/exceptions/{exc_id}")], b""

    def q05_reports_page(self):
        conn = self._conn()
        try:
            summary = recon_service.reconciliation_summary(conn)
            aging = recon_service.aging_report(conn)
            exc_aging = recon_service.exception_aging(conn)
        finally:
            conn.close()
        bucket_rows = "".join(
            f"<tr><td>{b}</td><td>{v['invoice_count']}</td>"
            f"<td>{v['outstanding']}</td></tr>"
            for b, v in aging["buckets"].items()
        )
        exc_rows = "".join(
            f"<tr><td>{b}</td><td>{v['exception_count']}</td>"
            f"<td>{html.escape(json.dumps(v['kinds']))}</td></tr>"
            for b, v in exc_aging["buckets"].items()
        )
        body = f"""
<div class="card"><h2>Q05 — Reconciliation reports</h2>
<p>Every total below is computed from source rows. Reconciliation identity:
outstanding − overpaid == invoiced − matched-paid
({summary['outstanding_cents'] - summary['overpaid_cents']} ==
{summary['total_invoiced_cents'] - summary['matched_payments_cents']}).</p>
<h3>Summary</h3>
<table>
<tr><th>Total invoiced</th><td>{summary['total_invoiced']} ({summary['invoice_count']})</td></tr>
<tr><th>Total paid</th><td>{summary['total_paid']} ({summary['payment_count']})</td></tr>
<tr><th>Matched invoices</th><td>{summary['matched_invoices']}</td></tr>
<tr><th>Matched payments</th><td>{summary['matched_payments']}</td></tr>
<tr><th>Unmatched payments</th><td>{summary['unmatched_payments']}</td></tr>
<tr><th>Outstanding</th><td><strong>{summary['outstanding']}</strong></td></tr>
<tr><th>Overpaid</th><td>{summary['overpaid']}</td></tr>
</table>
<h3>Aging (as of {aging['as_of']}) — outstanding by days overdue</h3>
<table><tr><th>Bucket</th><th>Invoices</th><th>Outstanding</th></tr>{bucket_rows}</table>
<h3>Exception aging — open/investigating by age</h3>
<table><tr><th>Bucket</th><th>Exceptions</th><th>Kinds</th></tr>{exc_rows}</table>
<p><a href="/project_q05">← Upload / run match</a> ·
<a href="/project_q05/exceptions">Exception queue →</a></p></div>
"""
        return _html(200, "Q05 — Reports", body)

    # -- Q05: JSON API -----------------------------------------------------------
    def api_recon_upload(self, environ: dict):
        data = self._read_json(environ)
        kind = str(data.get("kind", "")).strip()
        csv_text = str(data.get("csv", ""))
        actor = str(data.get("actor", "api")).strip() or "api"
        conn = self._conn()
        try:
            try:
                if kind == "invoices":
                    result = recon_service.ingest_invoices(conn, csv_text, actor=actor)
                elif kind == "payments":
                    result = recon_service.ingest_payments(conn, csv_text, actor=actor)
                else:
                    raise ValidationError({"kind": "kind must be 'invoices' or 'payments'."})
            except (InvalidTransition, ValueError) as exc:
                return self._q05_error(exc)
        finally:
            conn.close()
        serializable = {k: (v if k != "errors" else v) for k, v in result.items()}
        return _json(201, serializable)

    def api_recon_run_match(self, environ: dict):
        data = self._read_json(environ)
        actor = str(data.get("actor", "api")).strip() or "api"
        conn = self._conn()
        try:
            stats = match_service.run_match(conn, actor=actor)
        finally:
            conn.close()
        return _json(200, {k: v for k, v in stats.items() if k != "decisions"})

    def api_recon_summary(self):
        conn = self._conn()
        try:
            summary = recon_service.reconciliation_summary(conn)
        finally:
            conn.close()
        return _json(200, {k: (str(v) if isinstance(v, Decimal) else v)
                            for k, v in summary.items()})

    def api_recon_aging(self):
        conn = self._conn()
        try:
            aging = recon_service.aging_report(conn)
            exc_aging = recon_service.exception_aging(conn)
        finally:
            conn.close()
        payload = {
            "aging": {b: {"invoice_count": v["invoice_count"],
                          "outstanding_cents": v["outstanding_cents"],
                          "outstanding": str(v["outstanding"])}
                      for b, v in aging["buckets"].items()},
            "exception_aging": exc_aging["buckets"],
            "as_of": aging["as_of"],
        }
        return _json(200, payload)

    def api_recon_exceptions(self, environ: dict):
        query = dict(parse_qsl(environ.get("QUERY_STRING", "")))
        conn = self._conn()
        try:
            excs = recon_service.list_exceptions(
                conn, state=query.get("state"), kind=query.get("kind"))
        finally:
            conn.close()
        return _json(200, {"exceptions": excs})

    def api_recon_exception_get(self, exc_id: str):
        conn = self._conn()
        try:
            excs = recon_service.list_exceptions(conn)
            exc = next((e for e in excs if e["id"] == int(exc_id)), None)
            if exc is None:
                raise KeyError(f"No exception with id {exc_id}.")
            history = recon_service.exception_history(conn, exc["id"])
        finally:
            conn.close()
        return _json(200, {"exception": exc, "history": history})

    def api_recon_exception_transition(self, exc_id: str, environ: dict):
        data = self._read_json(environ)
        to_state = str(data.get("to_state", "")).strip()
        actor = str(data.get("actor", "api")).strip() or "api"
        detail = str(data.get("detail", ""))
        conn = self._conn()
        try:
            try:
                result = recon_service.transition_exception(
                    conn, int(exc_id), to_state, actor=actor, detail=detail)
            except (InvalidTransition, ValueError, KeyError) as exc:
                return self._q05_error(exc)
        finally:
            conn.close()
        return _json(200, {"exception": result})

    # ---- Q06: data quality & entity resolution ------------------------------
    def _q06_error(self, exc: Exception) -> tuple[int, list, bytes]:
        if isinstance(exc, KeyError):
            return _json(404, _error_envelope("not_found", str(exc)))
        if isinstance(exc, (er_service.MergeError, ValueError)):
            return _json(409, _error_envelope("action_rejected", str(exc)))
        raise exc

    def q06_page(self, errors: Optional[dict] = None):
        conn = self._conn()
        try:
            stats = er_service.resolution_stats(conn)
        finally:
            conn.close()
        err_html = ""
        if errors:
            items = "".join(f"<li><strong>{k}</strong>: {v}</li>" for k, v in errors.items())
            err_html = f'<div class="error-list"><ul>{items}</ul></div>'
        bands = stats["bands"]
        body = f"""
<div class="card"><h2>Q06 — Data Quality &amp; Entity Resolution Service</h2>
<p><strong>Synthetic data only.</strong> Ingest contact CSVs from several
sources, normalize them with deterministic idempotent cleaners, block on
cheap equality keys (phone digits, lowercased email, ZIP+surname), and score
candidate pairs with a transparent weighted formula. Pairs land in
<strong>match / review / no-match</strong> bands. A merge is never automatic:
match-band pairs get <em>proposals</em> that a named human confirms, every
confirmed merge stores full pre-merge images of both records, and any merge
is exactly reversible.</p>
<p>Thresholds: match ≥ <code>{stats.get('match_threshold', '0.85')}</code> ·
review ≥ <code>{stats.get('review_threshold', '0.60')}</code></p></div>
{err_html}
<div class="card"><h3>Upload a source CSV</h3>
<form method="post" action="/project_q06/upload">
<label>Source label <input name="label" placeholder="spreadsheet-customers"></label>
<label>Source kind <select name="source_kind">
<option value="spreadsheet">spreadsheet</option><option value="form">form</option>
<option value="phone">phone</option><option value="other">other</option></select></label>
<label>Your name (actor stamp) <input name="actor" placeholder="operator"></label>
<label>Paste CSV (columns: name,phone,email,address,zip,notes)
<textarea name="csv" rows="6" placeholder="name,phone,email,address,zip,notes"></textarea></label>
<p><button type="submit">Ingest source</button></p></form></div>
<div class="card"><h3>Run the pipeline</h3>
<form method="post" action="/project_q06/run">
<label>Your name (actor stamp) <input name="actor" placeholder="operator"></label>
<p><button type="submit">Normalize → block → score → propose</button></p></form></div>
<div class="card"><h3>Pipeline snapshot</h3>
<table><tr><th>Metric</th><th>Value</th></tr>
<tr><td>Sources</td><td>{stats['sources']}</td></tr>
<tr><td>Active contacts</td><td>{stats['active_contacts']}</td></tr>
<tr><td>Merged contacts</td><td>{stats['merged_contacts']}</td></tr>
<tr><td>Distinct blocks</td><td>{stats['distinct_blocks']}</td></tr>
<tr><td>Candidate pairs</td><td>{stats['pairs_total']}</td></tr>
<tr><td>All possible pairs</td><td>{stats['possible_pairs']}</td></tr>
<tr><td>O(n²) reduction</td><td>{stats['reduction_ratio']:.1%}</td></tr>
<tr><td>Match band</td><td>{bands['match']}</td></tr>
<tr><td>Review band</td><td>{bands['review']}</td></tr>
<tr><td>No-match band</td><td>{bands['no_match']}</td></tr></table>
<p><a href="/project_q06/pairs">Review pairs →</a> ·
<a href="/project_q06/merges">Merge proposals →</a></p></div>"""
        return _html(200, "Q06 — Entity Resolution", body)

    def q06_upload_submit(self, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        label = (data.get("label") or "").strip()
        source_kind = (data.get("source_kind") or "spreadsheet").strip()
        csv_text = data.get("csv") or ""
        actor = (data.get("actor") or "public-form").strip() or "public-form"
        conn = self._conn()
        try:
            try:
                result = er_service.ingest_source(
                    conn, label=label, source_kind=source_kind,
                    csv_text=csv_text, actor=actor)
            except (ValueError, er_service.MergeError) as exc:
                return self.q06_page(errors={"upload": str(exc)})
        finally:
            conn.close()
        if result["errors"]:
            return self.q06_page(errors={
                "rows": f"{len(result['errors'])} row(s) rejected; "
                        f"{result['inserted']} inserted."})
        return 303, [("Location", "/project_q06")], b""

    def q06_run_submit(self, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        actor = (data.get("actor") or "public-form").strip() or "public-form"
        conn = self._conn()
        try:
            er_service.run_resolution(conn, actor=actor)
        finally:
            conn.close()
        return 303, [("Location", "/project_q06/pairs")], b""

    def q06_pairs_page(self, environ: dict):
        query = dict(parse_qsl(environ.get("QUERY_STRING", "")))
        band = (query.get("band") or "").strip() or None
        conn = self._conn()
        try:
            pairs = er_service.list_pairs(conn, band=band, limit=200)
        except ValueError as exc:
            return _html(422, "Q06 — Pairs", f"<p>{html.escape(str(exc))}</p>")
        finally:
            conn.close()
        rows = "".join(
            f"<tr><td>{p['id']}</td><td>{html.escape(p['a_name'])}</td>"
            f"<td>{html.escape(p['b_name'])}</td><td>{p['score']}</td>"
            f"<td><span class=\"state\">{p['band']}</span></td>"
            f"<td><code>{html.escape(p['block_key'])}</code></td>"
            f"<td><a href=\"/project_q06/pairs/{p['id']}\">open</a></td></tr>"
            for p in pairs
        )
        body = f"""
<div class="card"><h2>Q06 — Candidate pairs</h2>
<p>Filter: <a href="/project_q06/pairs">all</a> ·
<a href="/project_q06/pairs?band=match">match</a> ·
<a href="/project_q06/pairs?band=review">review</a> ·
<a href="/project_q06/pairs?band=no_match">no-match</a>
{f' (showing <strong>{band}</strong>)' if band else ''} — {len(pairs)} pairs.
Only pairs that share a blocking key are ever generated (no O(n²) scan).</p>
<table><tr><th>#</th><th>Contact A</th><th>Contact B</th><th>Score</th>
<th>Band</th><th>Shared block</th><th></th></tr>{rows}</table></div>"""
        return _html(200, "Q06 — Pairs", body)

    def q06_pair_detail(self, pair_id: str):
        conn = self._conn()
        try:
            detail = er_service.get_pair(conn, int(pair_id))
            existing = conn.execute(
                "SELECT id, state FROM er_merge_proposals WHERE pair_id = ?",
                (detail["id"],)).fetchone()
        except (er_service.MergeError, ValueError) as exc:
            return self._q06_error(exc)
        finally:
            conn.close()
        score_detail = json.loads(detail["score_detail_json"] or "{}")
        comp_rows = "".join(
            f"<tr><td><code>{html.escape(k)}</code></td><td>{v}</td></tr>"
            for k, v in score_detail.get("components", {}).items())
        reasons = "".join(f"<li>{html.escape(r)}</li>"
                          for r in score_detail.get("reasons", []))

        def contact_card(side: str, c: dict) -> str:
            return f"""<div class="card"><h3>Contact {side} (#{c['id']})</h3>
<table><tr><th>Field</th><th>Raw</th><th>Normalized</th></tr>
<tr><td>Name</td><td>{html.escape(c['raw_name'])}</td><td>{html.escape(c['name_norm'])}</td></tr>
<tr><td>Phone</td><td>{html.escape(c['raw_phone'])}</td><td>{html.escape(c['raw_phone'] and c['phone_digits'])}</td></tr>
<tr><td>Email</td><td>{html.escape(c['raw_email'])}</td><td>{html.escape(c['email_norm'])}</td></tr>
<tr><td>Address</td><td>{html.escape(c['raw_address'])}</td><td>{html.escape(c['address_norm'])}</td></tr>
<tr><td>ZIP</td><td>{html.escape(c['raw_zip'])}</td><td>{html.escape(c['zip_norm'])}</td></tr>
<tr><td>Status</td><td colspan="2">{html.escape(c['status'])}</td></tr></table></div>"""

        propose_html = ""
        if detail["band"] == "review" and existing is None:
            propose_html = f"""
<div class="card"><h3>Propose a merge (human decision)</h3>
<p>This pair is in the <strong>review</strong> band — the scorer is unsure.
A named human may propose a merge; nothing merges without explicit
confirmation on the proposal page.</p>
<form method="post" action="/project_q06/merges">
<input type="hidden" name="pair_id" value="{detail['id']}">
<label>Your name (required) <input name="actor" placeholder="reviewer"></label>
<label>Note <input name="note" placeholder="why these are the same person"></label>
<p><button type="submit">Propose merge</button></p></form></div>"""
        elif existing is not None:
            propose_html = (f"<div class=\"card\"><p>Proposal "
                            f"<a href=\"/project_q06/merges/{existing['id']}\">#{existing['id']}</a> "
                            f"exists (<span class=\"state\">{existing['state']}</span>).</p></div>")
        body = f"""
<div class="card"><h2>Q06 — Pair #{detail['id']}</h2>
<p>Score <strong>{detail['score']}</strong> ·
<span class="state">{detail['band']}</span> ·
shared block <code>{html.escape(detail['block_key'])}</code> ·
scorer <code>{html.escape(score_detail.get('scorer', ''))}</code></p>
<h3>Score breakdown</h3><table><tr><th>Component</th><th>Weighted</th></tr>
{comp_rows}</table><ul>{reasons}</ul></div>
{contact_card('A', detail['contact_a'])}{contact_card('B', detail['contact_b'])}
{propose_html}"""
        return _html(200, f"Q06 — Pair {detail['id']}", body)

    def q06_merges_page(self, environ: dict):
        query = dict(parse_qsl(environ.get("QUERY_STRING", "")))
        state = (query.get("state") or "").strip() or None
        conn = self._conn()
        try:
            proposals = er_service.list_proposals(conn, state=state)
        finally:
            conn.close()
        rows = "".join(
            f"<tr><td><a href=\"/project_q06/merges/{p['id']}\">{p['id']}</a></td>"
            f"<td>{html.escape(p['winner_name'])}</td><td>{html.escape(p['loser_name'])}</td>"
            f"<td>{p['pair_score']}</td><td><span class=\"state\">{p['pair_band']}</span></td>"
            f"<td><span class=\"state\">{p['state']}</span></td>"
            f"<td>{html.escape(p['proposed_by'])}</td></tr>"
            for p in proposals
        )
        body = f"""
<div class="card"><h2>Q06 — Merge proposals</h2>
<p>Filter: <a href="/project_q06/merges">all</a> ·
<a href="/project_q06/merges?state=proposed">proposed</a> ·
<a href="/project_q06/merges?state=confirmed">confirmed</a> ·
<a href="/project_q06/merges?state=rejected">rejected</a> ·
<a href="/project_q06/merges?state=reversed">reversed</a>
{f' (showing <strong>{state}</strong>)' if state else ''} — {len(proposals)} proposals.</p>
<p><strong>The pipeline never confirms a merge by itself.</strong> Every
proposal below waits for a named human; confirmed merges are fully audited
and exactly reversible.</p>
<table><tr><th>#</th><th>Survivor</th><th>Merged away</th><th>Score</th>
<th>Band</th><th>State</th><th>Proposed by</th></tr>{rows}</table></div>"""
        return _html(200, "Q06 — Merge proposals", body)

    def q06_merge_detail(self, prop_id: str, errors: Optional[dict] = None):
        conn = self._conn()
        try:
            detail = er_service.get_proposal(conn, int(prop_id))
            events = er_service.proposal_events(conn, int(prop_id))
        except (er_service.MergeError, ValueError) as exc:
            return self._q06_error(exc)
        finally:
            conn.close()
        err_html = ""
        if errors:
            items = "".join(f"<li><strong>{k}</strong>: {v}</li>" for k, v in errors.items())
            err_html = f'<div class="error-list"><ul>{items}</ul></div>'
        plan_rows = "".join(
            f"<tr><td><code>{html.escape(p['field'])}</code></td>"
            f"<td>{html.escape(p['value'])}</td><td>#{p['from_contact_id']}</td>"
            f"<td>{html.escape(p['reason'])}</td></tr>"
            for p in detail["field_plan"])
        event_rows = "".join(
            f"<li><code>{html.escape(e['created_at'])}</code> "
            f"<strong>{html.escape(e['event_type'])}</strong> by {html.escape(e['actor'])} "
            f"({html.escape(e['from_state'] or '—')} → {html.escape(e['to_state'] or '—')})</li>"
            for e in events)
        action_html = ""
        if detail["state"] == "proposed":
            action_html = f"""
<div class="card"><h3>Human decision required</h3>
<form method="post" action="/project_q06/merges/{detail['id']}">
<label>Your name (required — blank and "system" are rejected)
<input name="actor" placeholder="reviewer"></label>
<label>Note <input name="note" placeholder="decision rationale"></label>
<p><button type="submit" name="action" value="confirm">Confirm merge</button>
<button type="submit" name="action" value="reject">Reject proposal</button></p></form>
<p><small>Confirming applies the field plan to the survivor, marks the other
record merged, and writes a full before-image audit row. Rejecting changes
no data.</small></p></div>"""
        elif detail["state"] == "confirmed":
            action_html = f"""
<div class="card"><h3>Reverse this merge</h3>
<p>Reversal restores both records' exact pre-merge images. The audit row is
kept and stamped — history is never deleted.</p>
<form method="post" action="/project_q06/merges/{detail['id']}">
<label>Your name (required) <input name="actor" placeholder="reviewer"></label>
<p><button type="submit" name="action" value="reverse">Reverse merge</button></p></form></div>"""
        audit_html = ""
        if detail["audit"]:
            a = detail["audit"][-1]
            audit_html = (f"<div class=\"card\"><h3>Merge audit</h3>"
                          f"<p>Audit row #{a['id']} · merged by {html.escape(a['merged_by'])} "
                          f"at <code>{html.escape(a['merged_at'])}</code>"
                          + (f" · <strong>reversed</strong> by {html.escape(a['reversed_by'])} "
                             f"at <code>{html.escape(a['reversed_at'])}</code>"
                             if a["reversed_at"] else " · <em>not reversed</em>")
                          + "</p></div>")
        body = f"""
<div class="card"><h2>Q06 — Merge proposal #{detail['id']}</h2>
<p>State <span class="state">{detail['state']}</span> ·
proposed by {html.escape(detail['proposed_by'])} ·
pair score {detail['pair_score']} ({detail['pair_band']})</p>
<p>Survivor: <strong>#{detail['winner_id']}</strong>
{html.escape(detail['winner']['name_norm'])} ·
merged away: <strong>#{detail['loser_id']}</strong>
{html.escape(detail['loser']['name_norm'])}</p>
<h3>Field plan (per-field provenance)</h3>
<table><tr><th>Field</th><th>Winning value</th><th>From record</th><th>Reason</th></tr>
{plan_rows}</table></div>
{err_html}{action_html}{audit_html}
<div class="card"><h3>Audit trail</h3><ul class="timeline">{event_rows}</ul></div>"""
        return _html(200, f"Q06 — Proposal {detail['id']}", body)

    def q06_propose_submit(self, environ: dict):
        """Human proposes a merge for a review-band pair (from the pair page)."""
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        actor = (data.get("actor") or "").strip()
        note = (data.get("note") or "").strip()
        try:
            pair_id = int(data.get("pair_id") or 0)
        except ValueError:
            return _html(422, "Q06 — Propose", "<p>pair_id is required.</p>")
        conn = self._conn()
        try:
            try:
                new_id = er_service.propose_merge(conn, pair_id, actor=actor, note=note)
            except (er_service.MergeError, ValueError) as exc:
                return _html(409, "Q06 — Propose",
                             f"<p>Proposal rejected: {html.escape(str(exc))}</p>"
                             f"<p><a href=\"/project_q06/pairs/{pair_id}\">Back to pair</a></p>")
        finally:
            conn.close()
        return 303, [("Location", f"/project_q06/merges/{new_id}")], b""

    def q06_merge_action(self, prop_id: str, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        action = (data.get("action") or "").strip()
        actor = (data.get("actor") or "").strip()
        note = (data.get("note") or "").strip()
        conn = self._conn()
        try:
            try:
                pid = int(prop_id)
                if action == "confirm":
                    er_service.confirm_merge(conn, pid, actor=actor, note=note)
                elif action == "reject":
                    er_service.reject_proposal(conn, pid, actor=actor, note=note)
                elif action == "reverse":
                    er_service.reverse_merge(conn, pid, actor=actor)
                else:
                    return self.q06_merge_detail(prop_id, errors={"action": "unknown action"})
            except (er_service.MergeError, ValueError) as exc:
                return self.q06_merge_detail(prop_id, errors={"decision": str(exc)})
        finally:
            conn.close()
        return 303, [("Location", f"/project_q06/merges/{prop_id}")], b""

    # -- JSON API ------------------------------------------------------------
    def api_er_upload(self, environ: dict):
        data = self._read_json(environ)
        label = str(data.get("label", "")).strip()
        source_kind = str(data.get("source_kind", "spreadsheet")).strip()
        csv_text = str(data.get("csv", ""))
        actor = str(data.get("actor", "api")).strip() or "api"
        conn = self._conn()
        try:
            try:
                result = er_service.ingest_source(
                    conn, label=label, source_kind=source_kind,
                    csv_text=csv_text, actor=actor)
            except (ValueError, er_service.MergeError) as exc:
                return self._q06_error(exc)
        finally:
            conn.close()
        return _json(201, result)

    def api_er_run(self, environ: dict):
        data = self._read_json(environ)
        actor = str(data.get("actor", "api")).strip() or "api"
        conn = self._conn()
        try:
            stats = er_service.run_resolution(conn, actor=actor)
        finally:
            conn.close()
        return _json(200, stats)

    def api_er_stats(self):
        conn = self._conn()
        try:
            return _json(200, er_service.resolution_stats(conn))
        finally:
            conn.close()

    def api_er_pairs(self, environ: dict):
        query = dict(parse_qsl(environ.get("QUERY_STRING", "")))
        band = (query.get("band") or "").strip() or None
        try:
            limit = max(1, min(500, int(query.get("limit", "200"))))
        except ValueError:
            limit = 200
        conn = self._conn()
        try:
            try:
                pairs = er_service.list_pairs(conn, band=band, limit=limit)
            except ValueError as exc:
                return self._q06_error(exc)
        finally:
            conn.close()
        return _json(200, {"pairs": pairs})

    def api_er_pair_get(self, pair_id: str):
        conn = self._conn()
        try:
            try:
                return _json(200, er_service.get_pair(conn, int(pair_id)))
            except (er_service.MergeError, ValueError) as exc:
                return self._q06_error(exc)
        finally:
            conn.close()

    def api_er_proposals(self, environ: dict):
        query = dict(parse_qsl(environ.get("QUERY_STRING", "")))
        state = (query.get("state") or "").strip() or None
        conn = self._conn()
        try:
            return _json(200, {"proposals": er_service.list_proposals(conn, state=state)})
        finally:
            conn.close()

    def api_er_propose(self, environ: dict):
        # human proposes a merge for a review-band pair; no proposal id yet
        data = self._read_json(environ)
        try:
            pair_id = int(data.get("pair_id"))
        except (TypeError, ValueError):
            return _json(422, _error_envelope("validation_failed", "pair_id is required"))
        actor = str(data.get("actor", "")).strip()
        note = str(data.get("note", ""))
        conn = self._conn()
        try:
            try:
                new_id = er_service.propose_merge(conn, pair_id, actor=actor, note=note)
            except (er_service.MergeError, ValueError) as exc:
                return self._q06_error(exc)
        finally:
            conn.close()
        return _json(201, {"proposal_id": new_id})

    def api_er_proposal_get(self, prop_id: str):
        conn = self._conn()
        try:
            try:
                return _json(200, er_service.get_proposal(conn, int(prop_id)))
            except (er_service.MergeError, ValueError) as exc:
                return self._q06_error(exc)
        finally:
            conn.close()

    def api_er_proposal_confirm(self, prop_id: str, environ: dict):
        data = self._read_json(environ)
        actor = str(data.get("actor", "")).strip()
        note = str(data.get("note", ""))
        conn = self._conn()
        try:
            try:
                audit_id = er_service.confirm_merge(conn, int(prop_id), actor=actor, note=note)
            except (er_service.MergeError, ValueError) as exc:
                return self._q06_error(exc)
        finally:
            conn.close()
        return _json(200, {"proposal_id": int(prop_id), "audit_id": audit_id,
                           "state": "confirmed"})

    def api_er_proposal_reject(self, prop_id: str, environ: dict):
        data = self._read_json(environ)
        actor = str(data.get("actor", "")).strip()
        note = str(data.get("note", ""))
        conn = self._conn()
        try:
            try:
                er_service.reject_proposal(conn, int(prop_id), actor=actor, note=note)
            except (er_service.MergeError, ValueError) as exc:
                return self._q06_error(exc)
        finally:
            conn.close()
        return _json(200, {"proposal_id": int(prop_id), "state": "rejected"})

    def api_er_proposal_reverse(self, prop_id: str, environ: dict):
        data = self._read_json(environ)
        actor = str(data.get("actor", "")).strip()
        conn = self._conn()
        try:
            try:
                er_service.reverse_merge(conn, int(prop_id), actor=actor)
            except (er_service.MergeError, ValueError) as exc:
                return self._q06_error(exc)
        finally:
            conn.close()
        return _json(200, {"proposal_id": int(prop_id), "state": "reversed"})

    def api_er_proposal_audit(self, prop_id: str):
        conn = self._conn()
        try:
            try:
                return _json(200, er_service.merge_audit_view(conn, int(prop_id)))
            except (er_service.MergeError, ValueError) as exc:
                return self._q06_error(exc)
        finally:
            conn.close()

    # ---- Q07: multi-location KPI rollup pipeline -----------------------------

    def _q07_error(self, exc: Exception):
        return _json(422, _error_envelope("unprocessable",
                                          f"{type(exc).__name__}: {exc}"))

    def q07_page(self, environ: dict):
        query = dict(parse_qsl(environ.get("QUERY_STRING", "")))
        period = (query.get("period") or "").strip()
        conn = self._conn()
        try:
            periods = kpi_service.list_periods(conn)
            if not period and periods:
                period = periods[0]
            values = kpi_service.dashboard_values(conn, period) if period else []
            locations = kpi_service.list_locations(conn)
            alerts = kpi_service.list_alerts(conn)
            n_quarantine = conn.execute(
                "SELECT COUNT(*) AS c FROM kpi_quarantine").fetchone()["c"]
        finally:
            conn.close()
        opts = "".join(
            f'<option value="{html.escape(p)}"'
            f'{" selected" if p == period else ""}>{html.escape(p)}</option>'
            for p in periods)
        rows = "".join(
            f"<tr><td>{html.escape(v['location_code'] or 'ALL (rollup)')}</td>"
            f"<td>{html.escape(v['kpi_name'])}</td>"
            f"<td>{html.escape(v['value'] or 'n/a')}</td>"
            f"<td>{html.escape(v['def_version'])}</td>"
            f"<td><a href=\"/project_q07/kpi/{v['id']}\">drill down</a></td></tr>"
            for v in values)
        locs = "".join(
            f"<li><b>{html.escape(x['code'])}</b> — {html.escape(x['name'])} "
            f"(schema {html.escape(x['schema_version'] or '?')})</li>"
            for x in locations)
        body = f"""<p>Three shops, three spreadsheets, one tired owner doing
Sundays with a calculator. This pipeline speaks each shop's dialect
(configured schema maps), quarantines the bad rows loudly, and rolls
everything up — with every total traceable back to the row it came from.</p>
<div class="card"><h3>Period</h3><form method="get" action="/project_q07">
<select name="period">{opts}</select> <button type="submit">View</button>
</form></div>
<div class="card"><h3>Consolidated KPIs — {html.escape(period or 'no data')}</h3>
<table><tr><th>Scope</th><th>KPI</th><th>Value</th><th>Definition</th><th></th></tr>
{rows or '<tr><td colspan="5">No values yet — upload CSVs and compute.</td></tr>'}
</table></div>
<div class="card"><h3>Locations</h3><ul>{locs or '<li>none registered</li>'}</ul>
<p><a href="/project_q07/locations">Manage locations &amp; schema maps →</a></p></div>
<div class="card"><h3>Upload a location CSV</h3>
<form method="post" action="/project_q07/upload">
<label>Location code <input name="location_code"></label>
<label>Period (YYYY-MM) <input name="period" value="{html.escape(period)}"></label>
<label>CSV <textarea name="csv" rows="8"></textarea></label>
<button type="submit">Ingest</button></form></div>
<div class="card"><h3>Compute KPIs</h3>
<form method="post" action="/project_q07/compute">
<label>Period (YYYY-MM) <input name="period" value="{html.escape(period)}"></label>
<button type="submit">Compute location + rollup KPIs</button></form></div>
<p>Open alerts: <b>{len(alerts)}</b> · Quarantined rows/columns: <b>{n_quarantine}</b> ·
<a href="/project_q07/quarantine">Quarantine &amp; alerts →</a> ·
<a href="/project_q07/kpi">KPI dashboard →</a> ·
<a href="/project_q07/restatements">Restatement log →</a></p>"""
        return _html(200, "Q07 — KPI Rollup Pipeline", body)

    def q07_locations_page(self):
        conn = self._conn()
        try:
            locations = kpi_service.list_locations(conn)
            defs = kpi_service.list_definitions(conn)
        finally:
            conn.close()
        loc_rows = "".join(
            f"<tr><td>{html.escape(x['code'])}</td><td>{html.escape(x['name'])}</td>"
            f"<td>{html.escape(x['schema_version'] or '?')}</td>"
            f"<td>{'active' if x['active'] else 'inactive'}</td></tr>"
            for x in locations)
        def_rows = "".join(
            f"<tr><td>{html.escape(d['name'])}</td><td>{html.escape(d['version'])}</td>"
            f"<td>{html.escape(d['status'])}</td></tr>" for d in defs)
        body = f"""<div class="card"><h3>Register a location + schema map</h3>
<form method="post" action="/project_q07/locations">
<label>Location code <input name="code" placeholder="north"></label>
<label>Name <input name="name" placeholder="North Shop"></label>
<label>Schema version <input name="schema_version" value="v1"></label>
<label>Schema map (JSON: canonical field → CSV column)
<textarea name="map_json" rows="8">{{"job_id": "ticket_id",
"completed_date": "date", "revenue": "rev_usd", "costs": "cost_usd",
"is_callback": "callback_flag", "tech_days": "tech_days"}}</textarea></label>
<button type="submit">Register</button></form>
<p>Canonical fields: <code>job_id, completed_date, revenue, costs,
is_callback, tech_days</code>. The map is configured per location — never assumed.</p></div>
<div class="card"><h3>Locations</h3>
<table><tr><th>Code</th><th>Name</th><th>Schema</th><th>Status</th></tr>
{loc_rows or '<tr><td colspan="4">none</td></tr>'}</table></div>
<div class="card"><h3>KPI definitions (versioned)</h3>
<table><tr><th>KPI</th><th>Version</th><th>Status</th></tr>
{def_rows or '<tr><td colspan="3">none — seed via API</td></tr>'}</table></div>"""
        return _html(200, "Q07 — Locations", body)

    def q07_locations_submit(self, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"),
                              keep_blank_values=True))
        conn = self._conn()
        try:
            try:
                schema_map = json.loads(data.get("map_json") or "{}")
                kpi_service.register_location(
                    conn, data.get("code") or "", data.get("name") or "",
                    schema_map,
                    schema_version=(data.get("schema_version") or "v1"),
                    actor="web-form")
                kpi_definitions.seed_default_definitions(conn, actor="web-form")
            except (ValueError, kpi_service.KpiPipelineError,
                    kpi_definitions.KpiError) as exc:
                return _html(422, "Q07 — Locations",
                             f"<p class='errors'>Error: {html.escape(str(exc))}</p>"
                             "<p><a href=\"/project_q07/locations\">Back</a></p>")
        finally:
            conn.close()
        return 303, [("Location", "/project_q07/locations")], b""

    def q07_upload_submit(self, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"),
                              keep_blank_values=True))
        conn = self._conn()
        try:
            try:
                stats = kpi_service.ingest_csv(
                    conn, data.get("location_code") or "",
                    data.get("period") or "", data.get("csv") or "",
                    actor="web-form")
            except (ValueError, kpi_service.KpiPipelineError) as exc:
                return _html(422, "Q07 — KPI Rollup",
                             f"<p class='errors'>Error: {html.escape(str(exc))}</p>"
                             "<p><a href=\"/project_q07\">Back</a></p>")
        finally:
            conn.close()
        note = (f"Staged {stats['staged']}, quarantined {stats['quarantined']}, "
                f"alerts {stats['alerts']}"
                + (" (deduped — already ingested)" if stats.get("deduped") else ""))
        return _html(200, "Q07 — Upload",
                     f"<p>{html.escape(note)}</p>"
                     "<p><a href=\"/project_q07\">Back to dashboard</a> · "
                     "<a href=\"/project_q07/quarantine\">Quarantine →</a></p>")

    def q07_compute_submit(self, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"),
                              keep_blank_values=True))
        period = (data.get("period") or "").strip()
        conn = self._conn()
        try:
            try:
                for loc in kpi_service.list_locations(conn):
                    kpi_service.compute_location_kpis(
                        conn, loc["code"], period, actor="web-form")
                kpi_service.compute_rollup(conn, period, actor="web-form")
            except (ValueError, kpi_service.KpiPipelineError,
                    kpi_definitions.KpiError) as exc:
                return _html(422, "Q07 — KPI Rollup",
                             f"<p class='errors'>Error: {html.escape(str(exc))}</p>"
                             "<p><a href=\"/project_q07\">Back</a></p>")
        finally:
            conn.close()
        return 303, [("Location", f"/project_q07/kpi?period={period}")], b""

    def q07_quarantine_page(self, environ: dict):
        query = dict(parse_qsl(environ.get("QUERY_STRING", "")))
        period = (query.get("period") or "").strip() or None
        conn = self._conn()
        try:
            rows = kpi_service.list_quarantine(conn, period=period)
            alerts = kpi_service.list_alerts(conn)
        finally:
            conn.close()
        q_rows = "".join(
            f"<tr><td>{html.escape(r['location_code'])}</td>"
            f"<td>{html.escape(r['period'])}</td>"
            f"<td>{r['source_row'] if r['source_row'] is not None else '— (column)'}</td>"
            f"<td>{html.escape(r['reason'])}</td></tr>" for r in rows)
        a_rows = "".join(
            f"<tr><td>{html.escape(a['alert_type'])}</td>"
            f"<td>{html.escape(a['location_code'] or '—')}</td>"
            f"<td>{html.escape(a['period'] or '—')}</td>"
            f"<td><form method='post' action='/api/kpi/alerts/{a['id']}/resolve'>"
            f"<button type='submit'>Resolve</button></form></td></tr>"
            for a in alerts)
        body = f"""<p>Nothing is silently dropped: every quarantined row or
column carries a reason. Unknown CSV columns are held here (column-level)
while the good rows still flow.</p>
<div class="card"><h3>Open alerts ({len(alerts)})</h3>
<table><tr><th>Type</th><th>Location</th><th>Period</th><th></th></tr>
{a_rows or '<tr><td colspan="4">none open</td></tr>'}</table></div>
<div class="card"><h3>Quarantine ({len(rows)})</h3>
<table><tr><th>Location</th><th>Period</th><th>Row</th><th>Reason</th></tr>
{q_rows or '<tr><td colspan="4">empty — zero silent drops</td></tr>'}</table></div>"""
        return _html(200, "Q07 — Quarantine", body)

    def q07_kpi_page(self, environ: dict):
        query = dict(parse_qsl(environ.get("QUERY_STRING", "")))
        period = (query.get("period") or "").strip()
        conn = self._conn()
        try:
            periods = kpi_service.list_periods(conn)
            if not period and periods:
                period = periods[0]
            values = kpi_service.dashboard_values(conn, period) if period else []
        finally:
            conn.close()
        opts = "".join(
            f'<option value="{html.escape(p)}"'
            f'{" selected" if p == period else ""}>{html.escape(p)}</option>'
            for p in periods)
        by_scope: dict[str, list] = {}
        for v in values:
            by_scope.setdefault(v["location_code"] or "ALL (rollup)", []).append(v)
        sections = ""
        for scope, vals in sorted(by_scope.items()):
            rows = "".join(
                f"<tr><td>{html.escape(x['kpi_name'])}</td>"
                f"<td>{html.escape(x['value'] or 'n/a')}</td>"
                f"<td>{html.escape(x['def_version'])}</td>"
                f"<td><code>{html.escape(str(json.loads(x['inputs_json'])))}</code></td>"
                f"<td><a href=\"/project_q07/kpi/{x['id']}\">drill down</a></td></tr>"
                for x in vals)
            sections += (f"<div class='card'><h3>{html.escape(scope)}</h3>"
                         "<table><tr><th>KPI</th><th>Value</th><th>Def</th>"
                         "<th>Inputs</th><th></th></tr>" + rows + "</table></div>")
        body = f"""<form method="get" action="/project_q07/kpi">
<select name="period">{opts}</select> <button type="submit">View</button></form>
{sections or '<p>No KPI values yet for this period.</p>'}"""
        return _html(200, "Q07 — KPI Dashboard", body)

    def q07_kpi_detail(self, value_id: str):
        conn = self._conn()
        try:
            try:
                dd = kpi_service.get_drilldown(conn, int(value_id))
            except (ValueError, kpi_service.KpiPipelineError) as exc:
                return _html(404, "Q07 — KPI",
                             f"<p class='errors'>{html.escape(str(exc))}</p>")
        finally:
            conn.close()
        v = dd["value"]
        rows = "".join(
            f"<tr><td>{html.escape(r['location_code'])}</td>"
            f"<td>{html.escape(r['job_id'])}</td>"
            f"<td>{html.escape(r['completed_date'])}</td>"
            f"<td>{html.escape(r['revenue'])}</td>"
            f"<td>{html.escape(r['costs'])}</td>"
            f"<td>{r['is_callback']}</td>"
            f"<td>{html.escape(r['tech_days'])}</td></tr>"
            for r in dd["rows"])
        body = f"""<div class="card"><h3>
{html.escape(v['kpi_name'])} = {html.escape(v['value'] or 'n/a')}</h3>
<p>Scope: <b>{html.escape(v['location_code'] or 'ALL (rollup)')}</b> ·
Period: <b>{html.escape(v['period'])}</b> ·
Definition: <b>{html.escape(v['def_version'])}</b> ·
Source rows: <b>{len(dd['rows'])}</b></p>
<p>Every consolidated number traces to the staging rows that fed it —
this is the drill-down lineage guarantee.</p></div>
<table><tr><th>Location</th><th>Job</th><th>Date</th><th>Revenue</th>
<th>Costs</th><th>Callback</th><th>Tech-days</th></tr>{rows}</table>"""
        return _html(200, "Q07 — KPI Drill-down", body)

    def q07_restatements_page(self):
        conn = self._conn()
        try:
            rows = kpi_service.list_restatements(conn)
        finally:
            conn.close()
        items = "".join(
            f"<tr><td>{html.escape(r['created_at'])}</td>"
            f"<td>{html.escape(r['period'])}</td>"
            f"<td>{html.escape(r['kpi_name'])}</td>"
            f"<td>{html.escape(r['old_version'])} → {html.escape(r['new_version'])}</td>"
            f"<td>{html.escape(r['reason'])}</td>"
            f"<td>{html.escape(r['actor'])}</td></tr>" for r in rows)
        body = f"""<p>KPI definitions are versioned, never edited in place.
When a definition changes, old values are superseded (kept, not deleted)
and the period is recomputed — every change is logged here with a reason.</p>
<table><tr><th>When</th><th>Period</th><th>KPI</th><th>Change</th>
<th>Reason</th><th>Actor</th></tr>
{items or '<tr><td colspan="6">no restatements yet</td></tr>'}</table>"""
        return _html(200, "Q07 — Restatement Log", body)

    # ---- Q07 JSON API ------------------------------------------------------

    def api_kpi_location_create(self, environ: dict):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            try:
                location_id = kpi_service.register_location(
                    conn, str(data.get("code", "")), str(data.get("name", "")),
                    data.get("schema_map") or {},
                    schema_version=str(data.get("schema_version", "v1")),
                    actor=str(data.get("actor") or "api"))
            except (ValueError, kpi_service.KpiPipelineError) as exc:
                return self._q07_error(exc)
        finally:
            conn.close()
        return _json(201, {"location_id": location_id})

    def api_kpi_locations(self):
        conn = self._conn()
        try:
            return _json(200, {"locations": kpi_service.list_locations(conn)})
        finally:
            conn.close()

    def api_kpi_upload(self, environ: dict):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            try:
                stats = kpi_service.ingest_csv(
                    conn, str(data.get("location_code", "")),
                    str(data.get("period", "")), str(data.get("csv", "")),
                    actor=str(data.get("actor") or "api"),
                    label=str(data.get("label") or "") or None)
            except (ValueError, kpi_service.KpiPipelineError) as exc:
                return self._q07_error(exc)
        finally:
            conn.close()
        return _json(200, stats)

    def api_kpi_compute(self, environ: dict):
        data = self._read_json(environ)
        period = str(data.get("period", "")).strip()
        conn = self._conn()
        try:
            try:
                out: dict = {}
                for loc in kpi_service.list_locations(conn):
                    out[loc["code"]] = kpi_service.compute_location_kpis(
                        conn, loc["code"], period,
                        actor=str(data.get("actor") or "api"))
                out["__rollup__"] = kpi_service.compute_rollup(
                    conn, period, actor=str(data.get("actor") or "api"))
            except (ValueError, kpi_service.KpiPipelineError,
                    kpi_definitions.KpiError) as exc:
                return self._q07_error(exc)
        finally:
            conn.close()
        return _json(200, {"period": period, "values": out})

    def api_kpi_dashboard(self, environ: dict):
        query = dict(parse_qsl(environ.get("QUERY_STRING", "")))
        conn = self._conn()
        try:
            return _json(200, {"periods": kpi_service.list_periods(conn),
                               "values": kpi_service.dashboard_values(
                                   conn, (query.get("period") or "").strip())})
        finally:
            conn.close()

    def api_kpi_lineage(self, value_id: str):
        conn = self._conn()
        try:
            try:
                return _json(200, kpi_service.get_drilldown(conn, int(value_id)))
            except (ValueError, kpi_service.KpiPipelineError) as exc:
                return _json(404, _error_envelope("not_found", str(exc)))
        finally:
            conn.close()

    def api_kpi_quarantine(self, environ: dict):
        query = dict(parse_qsl(environ.get("QUERY_STRING", "")))
        conn = self._conn()
        try:
            return _json(200, {"quarantine": kpi_service.list_quarantine(
                conn, period=(query.get("period") or "").strip() or None)})
        finally:
            conn.close()

    def api_kpi_alerts(self):
        conn = self._conn()
        try:
            return _json(200, {"alerts": kpi_service.list_alerts(conn)})
        finally:
            conn.close()

    def api_kpi_alert_resolve(self, alert_id: str, environ: dict):
        data = self._read_json(environ) if environ.get(
            "CONTENT_TYPE", "").startswith("application/json") else {}
        conn = self._conn()
        try:
            try:
                kpi_service.resolve_alert(
                    conn, int(alert_id),
                    actor=str(data.get("actor") or "web-form"))
            except (ValueError, kpi_service.KpiPipelineError) as exc:
                return self._q07_error(exc)
        finally:
            conn.close()
        return 303, [("Location", "/project_q07/quarantine")], b""

    def api_kpi_definitions(self):
        conn = self._conn()
        try:
            return _json(200,
                         {"definitions": kpi_service.list_definitions(conn)})
        finally:
            conn.close()

    def api_kpi_definition_update(self, environ: dict):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            try:
                new = kpi_definitions.update_definition(
                    conn, str(data.get("name", "")),
                    str(data.get("new_version", "")),
                    str(data.get("formula", "")),
                    str(data.get("includes", "")),
                    str(data.get("excludes", "")),
                    actor=str(data.get("actor") or "api"))
            except (ValueError, kpi_definitions.KpiError) as exc:
                return self._q07_error(exc)
        finally:
            conn.close()
        return _json(201, {"id": new.id, "name": new.name,
                           "version": new.version})

    def api_kpi_restate(self, environ: dict):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            try:
                result = kpi_service.restate_period(
                    conn, str(data.get("period", "")),
                    reason=str(data.get("reason", "")),
                    actor=str(data.get("actor") or "api"))
            except (ValueError, kpi_service.KpiPipelineError) as exc:
                return self._q07_error(exc)
        finally:
            conn.close()
        return _json(200, result)

    # ---- Q10: webhook integration hub --------------------------------------
    def q10_page(self):
        conn = self._conn()
        try:
            events = wh_service.list_events(conn, limit=25)
            rules = wh_router.list_rules(conn)
            circuits = wh_delivery.endpoint_states(conn)
            dead = wh_delivery.list_dead_letters(conn, limit=5)
            counts = conn.execute(
                """
                SELECT (SELECT to_state FROM webhook_lineage l
                        WHERE l.event_id = e.event_id ORDER BY l.id DESC LIMIT 1) AS st,
                       COUNT(*) AS c
                FROM webhook_events e GROUP BY st
                """
            ).fetchall()
        finally:
            conn.close()
        count_rows = "".join(
            f"<tr><td><span class='state'>{r['st'] or '?'}</span></td>"
            f"<td>{r['c']}</td></tr>" for r in counts
        ) or "<tr><td colspan='2'>No events yet.</td></tr>"
        event_rows = "".join(
            f"<tr><td><a href='/api/webhooks/events/{e['public_id']}'>{e['public_id']}</a></td>"
            f"<td>{e['source']}</td><td>{e['event_type']}</td>"
            f"<td><span class='state'>{e['status']}</span></td>"
            f"<td>{'yes' if e['signature_ok'] else 'no'}</td>"
            f"<td>{e['created_at']}</td></tr>"
            for e in events
        ) or "<tr><td colspan='6'>No events yet. Send one with the curl example below.</td></tr>"
        rule_rows = "".join(
            f"<tr><td>{r['name']}</td><td>v{r['version']}</td>"
            f"<td>{r['event_type']}</td><td>{r['priority']}</td>"
            f"<td>{'enabled' if r['enabled'] else 'disabled'}</td></tr>"
            for r in rules
        ) or "<tr><td colspan='5'>No rules yet — seed the demo rules below.</td></tr>"
        circuit_rows = "".join(
            f"<tr><td>{c['endpoint']}</td>"
            f"<td><span class='state'>{c['state']}</span></td>"
            f"<td>{c['consecutive_failures']}</td></tr>"
            for c in circuits
        ) or "<tr><td colspan='3'>No circuit activity yet.</td></tr>"
        dead_rows = "".join(
            f"<tr><td>{d['event_id']}</td><td>{d['reason']}</td>"
            f"<td>{d['created_at']}</td></tr>"
            for d in dead
        ) or "<tr><td colspan='3'>Dead-letter queue is empty.</td></tr>"
        body = f"""
<div class="card"><h2>Q10 — Webhook Integration Hub (demo)</h2>
<p>Receives webhook events (HMAC-verified in strict mode), normalizes them to
a canonical envelope, routes them with versioned rules, and delivers to
<strong>stub endpoints only</strong> — in-process callables, no real SaaS,
no real HTTP. All data here is synthetic. Full payloads are never logged;
only redacted summaries (key names + value types) appear anywhere.</p>
<h3>Event status</h3>
<table><tr><th>Status</th><th>Count</th></tr>{count_rows}</table>
<h3>Recent events</h3>
<table><tr><th>ID</th><th>Source</th><th>Type</th><th>Status</th>
<th>Verified</th><th>Received</th></tr>{event_rows}</table>
<h3>Routing rules</h3>
<table><tr><th>Name</th><th>Version</th><th>Event type</th>
<th>Priority</th><th>State</th></tr>{rule_rows}</table>
<h3>Endpoint circuits</h3>
<table><tr><th>Endpoint</th><th>Circuit</th><th>Consec. failures</th></tr>
{circuit_rows}</table>
<h3>Recent dead letters</h3>
<table><tr><th>Event</th><th>Reason</th><th>At</th></tr>{dead_rows}</table>
<p><a href="/project_q10/dead-letters">Dead-letter queue →</a></p></div>
<div class="card"><h3>Try it (signed event)</h3>
<p>The demo source <code>demo-form</code> uses the documented test-only
secret <code>test-secret-demo-form-001</code> (see SECURITY.md — real
deployments must use real secrets from the environment).</p>
<pre><code>BODY='{{"source":"demo-form","event_type":"lead.created",
  "event_id":"demo-001","payload":{{"name":"Sample Lead","amount":1500}}}}'
SIG=$(python3 -c "import hmac,hashlib,sys;
print('sha256='+hmac.new(b'test-secret-demo-form-001',
  sys.argv[1].encode(),hashlib.sha256).hexdigest())" "$BODY")
curl -s -X POST http://localhost:8080/api/webhooks/events \\
  -H "Content-Type: application/json" \\
  -H "X-Webhook-Signature: $SIG" -d "$BODY" | python3 -m json.tool
curl -s -X POST http://localhost:8080/api/webhooks/deliver/run
</code></pre>
<form method="post" action="/api/webhooks/routes/seed"
onsubmit="fetch(this.action,{{method:'POST'}}).then(()=>location.reload());
return false;"><button type="submit">Seed demo routing rules</button></form></div>
"""
        return _html(200, "Q10 — Webhook Integration Hub", body)

    def q10_dead_letters_page(self):
        conn = self._conn()
        try:
            dead = wh_delivery.list_dead_letters(conn, limit=100)
        finally:
            conn.close()
        rows = "".join(
            f"<tr><td>{d['id']}</td><td>{d['event_id']}</td>"
            f"<td>{d['source']}/{d['event_type']}</td><td>{d['reason']}</td>"
            f"<td>{'yes' if d['replayed'] else 'no'}</td>"
            f"<td>{d['created_at']}</td></tr>"
            for d in dead
        ) or "<tr><td colspan='6'>Dead-letter queue is empty. Synthetic demo data only.</td></tr>"
        body = f"""
<div class="card"><h2>Q10 — Dead-letter queue</h2>
<p>Events that could not be delivered: malformed envelopes, routing
errors, exhausted retries, or unknown endpoints. Delivery-level dead
letters can be replayed via
<code>POST /api/webhooks/dead-letters/&lt;id&gt;/replay</code>.</p>
<table><tr><th>ID</th><th>Event</th><th>Source / type</th><th>Reason</th>
<th>Replayed</th><th>At</th></tr>{rows}</table></div>
"""
        return _html(200, "Q10 — Dead-letter queue", body)

    def api_wh_receive(self, environ):
        body = self._read_body(environ)
        try:
            data = json.loads(body.decode("utf-8")) if body.strip() else {}
        except (ValueError, UnicodeDecodeError):
            return _json(422, _error_envelope(
                "validation_failed", "Request body must be valid JSON."))
        if not isinstance(data, dict):
            return _json(422, _error_envelope(
                "validation_failed", "Request body must be a JSON object."))
        signature = environ.get("HTTP_X_WEBHOOK_SIGNATURE", "")
        conn = self._conn()
        try:
            result = wh_service.ingest_event(
                conn, body=body, signature=signature,
                secrets=wh_service.load_secrets(),
                strict=wh_service.strict_mode(),
                source_hint=environ.get("HTTP_X_WEBHOOK_SOURCE"),
                actor="http",
            )
            if not result["accepted"]:
                return _json(401, {
                    "accepted": False,
                    "reason": result["rejection_reason"],
                    "event_id": result["event_id"],
                })
            base = {
                "accepted": True,
                "event_id": result["event_id"],
                "public_id": result["public_id"],
                "verified": result["verified"],
            }
            if result.get("duplicate"):
                base["duplicate"] = True
                return _json(200, base)
            if result.get("poison"):
                base["poison"] = True
                base["dead_lettered"] = True
                return _json(201, base)
            outcome = wh_service.process_envelope(
                conn, result["envelope"], self.webhook_endpoints, actor="http")
            if outcome["ok"]:
                base["routing"] = outcome["plan"]
                return _json(201, base)
            base["routing_error"] = outcome["error"]
            return _json(201, base)
        finally:
            conn.close()

    def api_wh_events(self, environ):
        query = dict(parse_qsl(environ.get("QUERY_STRING", "")))
        status = (query.get("status") or "").strip() or None
        try:
            limit = max(1, min(500, int(query.get("limit") or 100)))
        except ValueError:
            limit = 100
        conn = self._conn()
        try:
            events = wh_service.list_events(conn, status=status, limit=limit)
        finally:
            conn.close()
        return _json(200, {"events": events, "status_filter": status})

    def api_wh_event(self, public_id):
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT event_id FROM webhook_events WHERE public_id = ?",
                (public_id,),
            ).fetchone()
            if row is None:
                return _json(404, _error_envelope(
                    "not_found", f"No event {public_id!r}."))
            event = wh_service.get_event(conn, row["event_id"])
            lineage = wh_service.get_lineage(conn, row["event_id"])
            deliveries = wh_delivery.list_deliveries(conn)
            deliveries = [d for d in deliveries
                          if d["event_id"] == row["event_id"]]
            event["envelope"] = json.loads(event.pop("envelope_json"))
            event["status"] = wh_service.event_status(conn, row["event_id"])
            return _json(200, {"event": event, "lineage": lineage,
                               "deliveries": deliveries})
        finally:
            conn.close()

    def api_wh_routes_list(self):
        conn = self._conn()
        try:
            return _json(200, {"routes": wh_router.list_rules(conn)})
        finally:
            conn.close()

    def api_wh_route_create(self, environ):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            try:
                rule = wh_router.create_rule(
                    conn, name=data.get("name"),
                    event_type=data.get("event_type", "*"),
                    conditions=data.get("conditions", []),
                    actions=data.get("actions", []),
                    priority=int(data.get("priority", 100)),
                    enabled=bool(data.get("enabled", True)),
                )
            except wh_router.RuleError as exc:
                return _json(422, _error_envelope(
                    "validation_failed", str(exc)))
        finally:
            conn.close()
        return _json(201, {"rule": rule})

    def api_wh_route_get(self, rule_id):
        conn = self._conn()
        try:
            try:
                return _json(200, {"rule": wh_router.get_rule(conn, int(rule_id))})
            except KeyError:
                return _json(404, _error_envelope(
                    "not_found", f"No rule {rule_id!r}."))
        finally:
            conn.close()

    def api_wh_route_update(self, rule_id, environ):
        data = self._read_json(environ)
        fields: dict = {}
        for key in ("name", "event_type", "conditions", "actions",
                    "priority", "enabled"):
            if key in data:
                fields[key] = data[key]
        conn = self._conn()
        try:
            try:
                rule = wh_router.update_rule(conn, int(rule_id), **fields)
            except KeyError:
                return _json(404, _error_envelope(
                    "not_found", f"No rule {rule_id!r}."))
            except wh_router.RuleError as exc:
                return _json(422, _error_envelope(
                    "validation_failed", str(exc)))
        finally:
            conn.close()
        return _json(200, {"rule": rule})

    def api_wh_route_delete(self, rule_id):
        conn = self._conn()
        try:
            try:
                wh_router.delete_rule(conn, int(rule_id))
            except KeyError:
                return _json(404, _error_envelope(
                    "not_found", f"No rule {rule_id!r}."))
        finally:
            conn.close()
        return _json(200, {"deleted": int(rule_id)})

    def api_wh_route_dryrun(self, environ):
        body = self._read_body(environ)
        try:
            data = json.loads(body.decode("utf-8")) if body.strip() else {}
        except (ValueError, UnicodeDecodeError):
            return _json(422, _error_envelope(
                "validation_failed", "Request body must be valid JSON."))
        try:
            envelope = wh_service.normalize_envelope(data)
        except wh_service.EnvelopeError as exc:
            return _json(422, _error_envelope(
                "validation_failed", str(exc)))
        conn = self._conn()
        try:
            return _json(200, wh_router.dry_run(conn, envelope))
        finally:
            conn.close()

    def api_wh_routes_seed(self):
        conn = self._conn()
        try:
            made = wh_router.seed_demo_rules(conn)
        finally:
            conn.close()
        return _json(200, {"seeded": [r["name"] for r in made],
                           "skipped_existing": not made})

    def api_wh_deliveries(self, environ):
        query = dict(parse_qsl(environ.get("QUERY_STRING", "")))
        state = (query.get("state") or "").strip() or None
        if state and state not in ("queued", "delivered", "dead_lettered"):
            return _json(422, _error_envelope(
                "validation_failed",
                "state must be queued, delivered, or dead_lettered."))
        conn = self._conn()
        try:
            return _json(200, {"deliveries": wh_delivery.list_deliveries(
                conn, state=state)})
        finally:
            conn.close()

    def api_wh_deliver_run(self):
        conn = self._conn()
        try:
            stats = wh_delivery.run_delivery_loop(
                conn, self.webhook_endpoints, actor="http")
        finally:
            conn.close()
        return _json(200, {"delivery_loop": stats})

    def api_wh_dead_letters(self):
        conn = self._conn()
        try:
            return _json(200, {"dead_letters": wh_delivery.list_dead_letters(conn)})
        finally:
            conn.close()

    def api_wh_dead_letter_replay(self, dead_letter_id):
        conn = self._conn()
        try:
            try:
                result = wh_delivery.replay_dead_letter(
                    conn, int(dead_letter_id), self.webhook_endpoints,
                    actor="http")
            except KeyError:
                return _json(404, _error_envelope(
                    "not_found", f"No dead letter {dead_letter_id!r}."))
            except ValueError as exc:
                return _json(422, _error_envelope(
                    "validation_failed", str(exc)))
        finally:
            conn.close()
        return _json(200, result)

    def api_wh_endpoints(self):
        conn = self._conn()
        try:
            return _json(200, {"endpoints": wh_delivery.endpoint_states(conn),
                               "registered": sorted(self.webhook_endpoints)})
        finally:
            conn.close()

    # ---- S01: network security (defensive lab & monitoring) -------------------
    _S01_LAB_BANNER = (
        "<div class=\"card\"><p><b>Lawful lab only.</b> This project documents "
        "a defensive network design and tests it with a local packet "
        "simulator. All addresses, packets, alerts, and incidents are "
        "synthetic. Do not scan, probe, or test any network you do not own."
        "</p></div>"
    )

    def _s01_json(self, data: dict, status: int = 200):
        return _json(status, {"lab_only": True, **data})

    def s01_page(self):
        conn = self._conn()
        try:
            alerts = conn.execute(
                "SELECT COUNT(*) c FROM netsec_alerts").fetchone()["c"]
            incidents = conn.execute(
                "SELECT status, COUNT(*) c FROM netsec_incidents "
                "GROUP BY status").fetchall()
            tunings = conn.execute(
                "SELECT COUNT(*) c FROM netsec_tuning").fetchone()["c"]
        finally:
            conn.close()
        lint_errors = fw_service.lint()
        lint_html = ("<p><b>Config lint: clean</b> — default-deny present, "
                     "no shadowed rules, every allow documented.</p>"
                     if not lint_errors else
                     "<p><b>Config lint errors:</b></p><ul>" +
                     "".join(f"<li>{html.escape(e)}</li>"
                             for e in lint_errors) + "</ul>")
        inc_rows = "".join(
            f"<tr><td>{html.escape(r['status'])}</td><td>{r['c']}</td></tr>"
            for r in incidents)
        body = f"""{self._S01_LAB_BANNER}
<div class="card"><h2>S01 — Network Security: Defensive Lab &amp; Monitoring</h2>
<p>A small-office network designed the way it should be: segmented VLANs,
default-deny firewall, and a monitoring routine a generalist can run. The
ruleset below is the actual lab policy, executable — every packet verdict is
computed from it, and every rule is verified by the lab test plan.</p>
<p>Ruleset v{html.escape(fw_service.RULESET_VERSION)} ·
<b>{len(fw_service.RULESET)}</b> rules ·
<b>{alerts}</b> synthetic alerts · <b>{tunings}</b> tuning entries</p>
{lint_html}
<p><a href="/project_s01/ruleset">Ruleset viewer →</a>
<a href="/project_s01/runbook">Triage runbook →</a>
<a href="/project_s01/incidents">Incident tickets →</a></p></div>
<div class="card"><h3>Lab topology (documented design — host-only)</h3>
<pre>
            +------------------+
            |    INTERNET      |  (WAN: any public address)
            +--------+---------+
                     |
            +--------+---------+        VLAN 10  OFFICE  10.10.10.0/24
            |  lab firewall    |        VLAN 20  GUEST   10.10.20.0/24
            |  (default-deny)  |        VLAN 30  IOT     10.10.30.0/24
            +---+--+---+---+--+        VLAN 99  MGMT    10.10.99.0/24
                |  |   |   |
          +-----+  |   |  +-----+
          | OFFICE |   |  | MGMT |
          |.10.0/24|   |  |.99.0/24
                |   |
           +----+ +----+
           |GUEST | IOT |
           |.20.0/24|.30.0/24
</pre>
<p>All segments attach to the firewall on a host-only lab network. The guest
and IoT VLANs are internet-only; the management VLAN is reachable solely
from the pinned admin workstation (10.10.10.50).</p></div>
<div class="card"><h3>Incidents by status</h3>
<table><tr><th>Status</th><th>Count</th></tr>
{inc_rows or "<tr><td colspan='2'>None yet.</td></tr>"}</table></div>
<div class="card"><h3>Seed synthetic demo data</h3>
<form method="post" action="/project_s01/seed">
<label>Seed <input name="seed" value="7"></label>
<button type="submit">Seed</button></form>
<p>Tuning log, synthetic alerts, one incident, and a ruleset version
snapshot. Deterministic for a given seed; all invented.</p></div>
<p><a href="/">Hub</a></p>"""
        return _html(200, "S01 — Network Security Lab", body)

    def s01_ruleset_page(self):
        rows = "".join(
            f"<tr><td>{r.order}</td><td><code>{html.escape(r.rule_id)}</code></td>"
            f"<td><span class='state'>{r.action}</span></td>"
            f"<td><code>{html.escape(r.src)}</code></td>"
            f"<td><code>{html.escape(r.dst)}</code></td>"
            f"<td>{html.escape(r.proto)}</td>"
            f"<td>{','.join(map(str, r.ports)) if r.ports else 'any'}</td>"
            f"<td>{html.escape(r.description)}"
            + (f"<br><i>Exception: {html.escape(r.exception_reason)}</i>"
               if r.exception_reason else "") + "</td></tr>"
            for r in sorted(fw_service.RULESET, key=lambda x: x.order))
        matrix = fw_service.allow_deny_matrix(list(fw_service.LAB_TEST_PACKETS))
        mrows = "".join(
            f"<tr><td>{html.escape(m['label'])}</td>"
            f"<td><span class='state'>{m['verdict']}</span></td>"
            f"<td><code>{html.escape(m['rule_id'] or 'default-deny')}</code></td></tr>"
            for m in matrix)
        cov = fw_service.matrix_coverage(matrix)
        body = f"""{self._S01_LAB_BANNER}
<div class="card"><h2>S01 — Firewall ruleset (v{html.escape(fw_service.RULESET_VERSION)})</h2>
<p>Ordered, first-match-wins, default-deny. Every <b>allow</b> rule carries a
documented exception reason; the lint checklist (default-deny present, no
shadowed rules, all allows documented) is enforced in code.</p>
<table><tr><th>#</th><th>Rule</th><th>Action</th><th>Src</th><th>Dst</th>
<th>Proto</th><th>Ports</th><th>Description / exception reason</th></tr>
{rows}</table>
<p>Implicit final rule: <b>deny all</b> (default-deny).</p></div>
<div class="card"><h3>Allow/deny matrix — lab test plan results</h3>
<p>Coverage: {cov['rules_hit']}/{cov['rules_total']} rules exercised ·
unhit allow rules: {len(cov['unhit_allow'])} ·
unhit deny rules: {len(cov['unhit_deny'])}</p>
<table><tr><th>Test packet</th><th>Verdict</th><th>Matched rule</th></tr>
{mrows}</table>
<p>Try your own packet: <code>POST /api/netsec/evaluate</code> with
<code>{{"src_ip","dst_ip","proto","dst_port"}}</code>.</p></div>
<p><a href="/project_s01">S01 home</a></p>"""
        return _html(200, "S01 — Firewall Ruleset", body)

    def s01_runbook_page(self):
        conn = self._conn()
        try:
            tunings = ns_service.list_tuning(conn)
        finally:
            conn.close()
        sev_blocks = []
        for sev in ns_service.SEVERITIES:
            steps = "".join(
                f"<tr><td>{html.escape(s['step'])}</td>"
                f"<td>{html.escape(s['action'])}</td>"
                f"<td>{s['timebox_s']}s</td></tr>"
                for s in ns_service.triage_steps(sev))
            sev_blocks.append(
                f"<h4>{sev}</h4><table><tr><th>Step</th><th>Action</th>"
                f"<th>Time box</th></tr>{steps}</table>")
        tuning_rows = "".join(
            f"<tr><td><code>{html.escape(t['alert_type'])}</code></td>"
            f"<td>{html.escape(t['action'])}</td>"
            f"<td>{html.escape(t['reason'])}</td>"
            f"<td>{html.escape(t['actor'])}</td></tr>" for t in tunings)
        body = f"""{self._S01_LAB_BANNER}
<div class="card"><h2>S01 — Triage runbook</h2>
<p>Severity → ordered steps → time boxes. The timed walkthrough harness
executes these steps against synthetic incidents and verifies every step
lands inside its box.</p>
{''.join(sev_blocks)}</div>
<div class="card"><h3>Alert-fatigue tuning log</h3>
<p>What was silenced, throttled, or de-escalated — and why. Suppressed
alerts stay reviewable; the reason is the point.</p>
<table><tr><th>Alert type</th><th>Action</th><th>Reason</th><th>By</th></tr>
{tuning_rows or "<tr><td colspan='4'>No tuning entries yet.</td></tr>"}</table></div>
<div class="card"><h3>Daily log-review checklist</h3>
<ol><li>Denied WAN inbound: expected background noise? (tuned: batch at
&gt;50/hr)</li>
<li>Any mgmt-VLAN login failures? → open incident.</li>
<li>IoT TLS volume vs. 7-day baseline.</li>
<li>Guest DHCP churn anomalies (rogue server?).</li>
<li>Firewall rule hit counts: any rule with zero hits in 7 days?</li></ol></div>
<p><a href="/project_s01">S01 home</a></p>"""
        return _html(200, "S01 — Triage Runbook", body)

    def s01_incidents_page(self):
        conn = self._conn()
        try:
            incidents = ns_service.list_incidents(conn)
        finally:
            conn.close()
        rows = "".join(
            f"<tr><td>{i['id']}</td>"
            f"<td><a href=\"/api/netsec/incidents/{i['id']}\">"
            f"{html.escape(i['title'])}</a></td>"
            f"<td>{html.escape(i['severity'])}</td>"
            f"<td><span class='state'>{html.escape(i['status'])}</span></td>"
            f"<td>{html.escape(i['created_at'])}</td></tr>" for i in incidents)
        body = f"""{self._S01_LAB_BANNER}
<div class="card"><h2>S01 — Incident tickets</h2>
<table><tr><th>ID</th><th>Title</th><th>Severity</th><th>Status</th>
<th>Opened</th></tr>
{rows or "<tr><td colspan='5'>No incidents yet.</td></tr>"}</table></div>
<div class="card"><h3>Open a ticket</h3>
<form method="post" action="/api/netsec/incidents">
<label>Title <input name="title"></label>
<label>Severity <select name="severity">
<option>critical</option><option>high</option><option>medium</option>
<option>low</option><option>info</option></select></label>
<button type="submit">Create</button></form>
<p>Lifecycle: open → triaged → contained → resolved → closed (reopen
allowed). Every transition is actor-stamped on an append-only timeline.
For JSON use, POST to <code>/api/netsec/incidents</code>.</p></div>
<p><a href="/project_s01">S01 home</a></p>"""
        return _html(200, "S01 — Incident Tickets", body)

    def s01_seed_submit(self, environ):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"),
                              keep_blank_values=True))
        try:
            seed = int(data.get("seed") or 7)
        except ValueError:
            seed = 7
        conn = self._conn()
        try:
            summary = ns_service.seed_demo(conn, seed=seed)
        finally:
            conn.close()
        body = (f"<div class='card'><h2>S01 demo seeded</h2>"
                f"<p>{html.escape(json.dumps(summary))}</p>"
                f"<p><a href='/project_s01'>Back to S01</a></p></div>")
        return _html(200, "S01 — Seeded", body)

    # ---- S01 JSON API ------------------------------------------------------
    def api_ns_topology(self):
        return self._s01_json({
            "ruleset_version": fw_service.RULESET_VERSION,
            "zones": {z: {"subnet": c, "vlan": v, "gateway": g}
                      for (z, c), (v, g) in zip(
                          fw_service.SUBNETS.items(),
                          [(10, fw_service.GATEWAYS["OFFICE"]),
                           (20, fw_service.GATEWAYS["GUEST"]),
                           (30, fw_service.GATEWAYS["IOT"]),
                           (99, fw_service.GATEWAYS["MGMT"])])},
            "admin_workstation": fw_service.ADMIN_WORKSTATION,
            "default_deny": fw_service.DEFAULT_DENY,
            "note": "Documented lab design (host-only). Do not apply to "
                    "networks you do not own.",
        })

    def api_ns_rules(self):
        return self._s01_json({
            "version": fw_service.RULESET_VERSION,
            "default_deny": fw_service.DEFAULT_DENY,
            "lint": fw_service.lint(),
            "rules": [r.as_dict() for r in
                      sorted(fw_service.RULESET, key=lambda x: x.order)],
        })

    def api_ns_evaluate(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError as exc:
            return _json(422, _error_envelope("validation_failed", str(exc)))
        try:
            pkt = fw_service.Packet(
                src_ip=str(data["src_ip"]), dst_ip=str(data["dst_ip"]),
                proto=str(data.get("proto", "tcp")).lower(),
                dst_port=(int(data["dst_port"]) if data.get("dst_port")
                          is not None else None),
                established=bool(data.get("established", False)))
            # validate the addresses parse (cheap input validation)
            fw_service.zone_of(pkt.src_ip)
            fw_service.zone_of(pkt.dst_ip)
        except (KeyError, ValueError, TypeError) as exc:
            return _json(422, _error_envelope(
                "validation_failed",
                f"Packet needs src_ip, dst_ip, proto; optional dst_port, "
                f"established. ({exc})"))
        result = fw_service.evaluate(pkt)
        return self._s01_json({"packet": {
            "src_ip": pkt.src_ip, "dst_ip": pkt.dst_ip, "proto": pkt.proto,
            "dst_port": pkt.dst_port, "established": pkt.established,
            "src_zone": fw_service.zone_of(pkt.src_ip),
            "dst_zone": fw_service.zone_of(pkt.dst_ip)},
            "verdict": result.as_dict()})

    def api_ns_matrix(self):
        matrix = fw_service.allow_deny_matrix(
            list(fw_service.LAB_TEST_PACKETS))
        return self._s01_json({
            "matrix": matrix,
            "coverage": fw_service.matrix_coverage(matrix)})

    def api_ns_runbook(self):
        return self._s01_json({
            "severities": list(ns_service.SEVERITIES),
            "runbook": {sev: ns_service.triage_steps(sev)
                        for sev in ns_service.SEVERITIES},
            "alert_types": {k: v for k, v in ns_service.ALERT_TYPES.items()}})

    def api_ns_alerts(self):
        conn = self._conn()
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM netsec_alerts ORDER BY id DESC LIMIT 100"
            ).fetchall()]
        finally:
            conn.close()
        return self._s01_json({"alerts": rows})

    def api_ns_alert_ingest(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError as exc:
            return _json(422, _error_envelope("validation_failed", str(exc)))
        alert_type = str(data.get("alert_type") or "")
        if alert_type not in ns_service.ALERT_TYPES:
            return _json(422, _error_envelope(
                "validation_failed",
                f"Unknown alert_type. Known: {sorted(ns_service.ALERT_TYPES)}"))
        source_ip = str(data.get("source_ip") or "203.0.113.9")
        conn = self._conn()
        try:
            alert = ns_service.synthetic_alert(alert_type, source_ip)
            triaged = ns_service.triage(alert, ns_service.list_tuning(conn))
            ns_service.record_alert(conn, alert, triaged)
            walk = ns_service.walkthrough(triaged)
        finally:
            conn.close()
        return _json(201, {"lab_only": True, "alert": alert,
                           "triage": {k: v for k, v in triaged.items()
                                      if k != "steps"},
                           "walkthrough": walk})

    def api_ns_tuning(self):
        conn = self._conn()
        try:
            rows = ns_service.list_tuning(conn)
        finally:
            conn.close()
        return self._s01_json({"tuning": rows})

    def api_ns_tuning_create(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError as exc:
            return _json(422, _error_envelope("validation_failed", str(exc)))
        conn = self._conn()
        try:
            try:
                tid = ns_service.log_tuning(
                    conn, str(data.get("alert_type") or ""),
                    str(data.get("action") or ""),
                    str(data.get("reason") or ""), actor="http")
            except ns_service.IncidentError as exc:
                return _json(422, _error_envelope("validation_failed",
                                                  str(exc)))
        finally:
            conn.close()
        return _json(201, {"lab_only": True, "tuning_id": tid})

    def api_ns_incidents(self):
        conn = self._conn()
        try:
            rows = ns_service.list_incidents(conn)
        finally:
            conn.close()
        return self._s01_json({"incidents": rows})

    def api_ns_incident_create(self, environ):
        ctype = environ.get("CONTENT_TYPE", "")
        if "application/json" in ctype:
            try:
                data = self._read_json(environ)
            except ValidationError as exc:
                return _json(422, _error_envelope("validation_failed",
                                                 str(exc)))
        else:  # HTML form posts urlencoded
            data = dict(parse_qsl(self._read_body(environ).decode("utf-8"),
                                  keep_blank_values=True))
        conn = self._conn()
        try:
            try:
                iid = ns_service.create_incident(
                    conn, str(data.get("title") or ""),
                    str(data.get("severity") or "medium"),
                    source_alert_type=data.get("source_alert_type"),
                    actor="http")
            except ns_service.IncidentError as exc:
                return _json(422, _error_envelope("validation_failed",
                                                 str(exc)))
            incident = ns_service.get_incident(conn, iid)
        finally:
            conn.close()
        return _json(201, {"lab_only": True, "incident": incident})

    def api_ns_incident_detail(self, incident_id):
        conn = self._conn()
        try:
            try:
                incident = ns_service.get_incident(conn, int(incident_id))
            except ns_service.IncidentError as exc:
                return _json(404, _error_envelope("not_found", str(exc)))
        finally:
            conn.close()
        return self._s01_json({"incident": incident})

    def api_ns_incident_transition(self, incident_id, environ):
        try:
            data = self._read_json(environ)
        except ValidationError as exc:
            return _json(422, _error_envelope("validation_failed", str(exc)))
        conn = self._conn()
        try:
            try:
                ns_service.transition_incident(
                    conn, int(incident_id), str(data.get("to_status") or ""),
                    actor="http", note=str(data.get("note") or ""))
            except ns_service.IncidentError as exc:
                return _json(422, _error_envelope("validation_failed",
                                                 str(exc)))
            incident = ns_service.get_incident(conn, int(incident_id))
        finally:
            conn.close()
        return self._s01_json({"incident": incident})

    def api_ns_seed(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError:
            data = {}
        try:
            seed = int(data.get("seed", 7))
        except (ValueError, TypeError):
            seed = 7
        conn = self._conn()
        try:
            summary = ns_service.seed_demo(conn, seed=seed)
        finally:
            conn.close()
        return self._s01_json({"seeded": summary})

    # ---- S02 pages ---------------------------------------------------------
    _S02_LAB_BANNER = (
        "<div class=\"card\"><p><b>Controlled lab only — simulated states.</b> "
        "This project verifies hardening baselines against a <i>simulated</i> "
        "system-state snapshot (a Python dict), not a live VM. All accounts, "
        "services, and findings are synthetic. The techniques documented here "
        "must never be applied to systems without authorization.</p></div>"
    )

    def _s02_json(self, data: dict, status: int = 200):
        return _json(status, {"lab_only": True, "simulated": True, **data})

    def _s02_baseline_doc(self, b):
        return {"id": b["id"], "category": b["category"], "title": b["title"],
                "description": b["description"], "expected": b["expected"],
                "remediation": b["remediation"]}

    def s02_page(self):
        conn = self._conn()
        try:
            findings = conn.execute(
                "SELECT status, COUNT(*) c FROM ossec_findings "
                "GROUP BY status").fetchall()
            runs = conn.execute(
                "SELECT state_label, passed, failed FROM ossec_baseline_runs "
                "ORDER BY id DESC LIMIT 10").fetchall()
        finally:
            conn.close()
        vuln_res = os_service.verify_baseline(os_service.vulnerable_state())
        hard_res = os_service.verify_baseline(os_service.hardened_state())
        sv, sh = (os_service.baseline_summary(vuln_res),
                  os_service.baseline_summary(hard_res))
        f_rows = "".join(
            f"<tr><td>{html.escape(r['status'])}</td><td>{r['c']}</td></tr>"
            for r in findings) or "<tr><td colspan='2'>None yet.</td></tr>"
        r_rows = "".join(
            f"<tr><td>{html.escape(r['state_label'])}</td>"
            f"<td>{r['passed']}</td><td>{r['failed']}</td></tr>"
            for r in runs) or "<tr><td colspan='3'>None yet.</td></tr>"
        body = f"""{self._S02_LAB_BANNER}
<div class="card"><h2>S02 — OS Architecture &amp; Vulnerabilities</h2>
<p>Most compromises exploit the basics: excessive privilege, unpatched
services, weak authentication. This project maps <i>where the boundaries
are</i> — privilege models, process isolation, authentication flows — and
verifies hardening baselines against simulated training-VM states: detect
the weakness, apply the fix, prove the fix.</p>
<p><b>{len(os_service.FINDINGS)}</b> vulnerability classes ·
<b>{len(os_service.BASELINES)}</b> baseline items · vulnerable fixture
<b>{sv['passed']}/{sv['total']}</b> passing · hardened fixture
<b>{sh['passed']}/{sh['total']}</b> passing</p>
<p><a href="/project_s02/concepts">Concepts →</a>
<a href="/project_s02/lab">Lab inventory →</a>
<a href="/project_s02/findings">Findings →</a>
<a href="/project_s02/baselines">Baselines →</a></p></div>
<div class="card"><h3>Findings by status (stored)</h3>
<table><tr><th>Status</th><th>Count</th></tr>{f_rows}</table></div>
<div class="card"><h3>Baseline runs (stored)</h3>
<table><tr><th>State</th><th>Passed</th><th>Failed</th></tr>{r_rows}</table></div>
<div class="card"><h3>Seed synthetic demo data</h3>
<form method="post" action="/project_s02/seed">
<label>Seed <input name="seed" value="7"></label>
<button type="submit">Seed</button></form>
<p>One finding row per vulnerability class plus baseline runs for the
vulnerable and hardened fixtures. Deterministic; all invented.</p></div>
<p><a href="/">Hub</a></p>"""
        return _html(200, "S02 — OS Architecture & Vulnerabilities", body)

    def s02_concepts_page(self):
        rings = """
 Ring 0  (kernel)      The CPU's most privileged mode. The kernel owns
                       memory management, device drivers, and scheduling.
                       Code here can do anything — so almost nothing should
                       run here.
 ── privilege boundary (hardware-enforced) ──
 Ring 3  (user mode)   Every normal process lives here: your shell, the web
                       browser, services. A user-mode process cannot touch
                       hardware or another process's memory directly; it must
                       ask the kernel through a system call — a narrow,
                       checked gate.
 Misconfigurations that punch holes in this boundary (a second uid-0
 account, an unjustified setuid-root binary, a service running as root
 that does not need to) are exactly what the S02 baselines check for."""
        isolation = """
 Each process gets its own virtual address space — process A cannot read
 process B's memory by default. The kernel enforces this with hardware
 memory protection. Isolation breaks down when:
   • a process runs with more privilege than its job needs (then a bug in
     it becomes a bug in everything);
   • file permissions leak data across the boundary (world-readable
     credential stores — baseline perm-01);
   • binaries cross the boundary standing up (unjustified setuid —
     baseline perm-02)."""
        authflow = """
 A login is a claim ("I am trainee") plus proof. The lab policy requires:
   1. Proof by key, not password, over SSH (auth-01).
   2. No direct root login — authenticate as yourself, then elevate, so
      the audit trail names the operator (auth-02).
   3. Bounded guessing: few attempts per connection, then disconnect
      (auth-03).
   4. Passwords that meet the policy, rotated by rule not by reuse
      (acct-02); dormant accounts disabled (acct-03)."""
        def _card(title, pre):
            return (f"<div class='card'><h3>{html.escape(title)}</h3>"
                    f"<pre>{html.escape(pre)}</pre></div>")
        body = f"""{self._S02_LAB_BANNER}
<div class="card"><h2>S02 — Privilege-boundary concepts</h2>
<p>Written for a hiring manager, technically accurate. These three ideas
are <i>why</i> the baselines exist: each baseline item is one of these
boundaries, checked in code.</p></div>
{_card("Privilege rings: user mode vs kernel mode", rings)}
{_card("Process isolation: separate address spaces, shared kernel", isolation)}
{_card("Authentication flow: claim, proof, audit", authflow)}
<p><a href="/project_s02">Back to S02</a></p>"""
        return _html(200, "S02 — Concepts", body)

    def s02_lab_page(self):
        rows = [
            ("lab-vm-vulnerable", "Intentionally misconfigured training "
             "image (simulated state, not a live VM)", "all 15 baseline "
             "items fail; all 6 findings detect", "Snapshot A (pre-fix)"),
            ("lab-vm-hardened", "Same fixture after the remediation "
             "simulator applies every fix", "15/15 baseline items pass; "
             "0 findings detect", "Snapshot B (post-fix)"),
        ]
        tr = "".join(
            f"<tr><td><code>{html.escape(r[0])}</code></td>"
            f"<td>{html.escape(r[1])}</td><td>{html.escape(r[2])}</td>"
            f"<td>{html.escape(r[3])}</td></tr>" for r in rows)
        body = f"""{self._S02_LAB_BANNER}
<div class="card"><h2>S02 — Lab inventory (simulated)</h2>
<p>The "lab VMs" in this project are <b>simulated system-state snapshots</b>
— Python dicts evaluated by the verification functions. There is no
hypervisor, no live guest, and no network traffic anywhere in S02.</p>
<table><tr><th>State label</th><th>Role</th><th>Expected result</th>
<th>Snapshot discipline</th></tr>{tr}</table></div>
<div class="card"><h3>Snapshot discipline</h3>
<ul><li><b>Snapshot A</b> is immutable in tests: verification never mutates
its input (asserted by <code>test_verify_does_not_mutate_state</code>).</li>
<li><b>Snapshot B</b> is derived, never hand-written: the remediation
simulator deep-copies A and applies fixes, so B is proof the fixes work —
not a second fixture that could drift.</li>
<li>Every remediation run records before/after evidence per baseline item
(see <a href="/project_s02/baselines">Baselines</a>).</li></ul></div>
<div class="card"><h3>Host-only network proof</h3>
<p>Vacuously true by construction: the simulator performs no I/O. There is
no socket, SSH, or subprocess code in <code>ossec.py</code> — verification
reads a dict, remediation returns a transformed dict. Nothing can leave
the process, so there is nothing to segment.</p></div>
<div class="card"><h3>Scope boundary checklist</h3>
<ul><li>Training states only — synthetic fixtures, invented data.</li>
<li>No real host, account, credential, or vulnerability is represented.</li>
<li>Techniques documented here must never be applied to systems without
authorization.</li>
<li>No exploit code exists in this project; detection and fix only.</li></ul></div>
<p><a href="/project_s02">Back to S02</a></p>"""
        return _html(200, "S02 — Lab Inventory", body)

    def s02_findings_page(self):
        vuln = os_service.vulnerable_state()
        cards = []
        for f in os_service.FINDINGS:
            d = os_service.detect_finding(vuln, f["id"])
            items = ", ".join(
                f"<code>{html.escape(i)}</code>"
                for i in f["baseline_item_ids"])
            cards.append(
                f"<div class='card'><h3>{html.escape(f['name'])}</h3>"
                f"<p><b>Class:</b> {html.escape(f['vuln_class'])}</p>"
                f"<p>{html.escape(f['description'])}</p>"
                f"<p><b>Detection:</b> {html.escape(f['detection_method'])}</p>"
                f"<p><b>Detection on vulnerable fixture:</b> "
                f"<span class='state'>{'DETECTED' if d['detected'] else 'not detected'}</span> — "
                f"{html.escape(d['evidence'])}</p>"
                f"<p><b>Remediation:</b> {html.escape(f['remediation'])}</p>"
                f"<p><b>Verification:</b> {html.escape(f['verification_method'])}</p>"
                f"<p><b>Baseline items:</b> {items}</p></div>")
        body = f"""{self._S02_LAB_BANNER}
<div class="card"><h2>S02 — Vulnerability-class findings</h2>
<p>Every finding carries description → detection method → remediation →
verification evidence. Detection is read from configuration — nothing is
exploited, even in simulation.</p></div>
{''.join(cards)}
<p><a href="/project_s02">Back to S02</a></p>"""
        return _html(200, "S02 — Findings", body)

    def s02_baselines_page(self):
        def _table(state):
            rows = "".join(
                f"<tr><td><code>{html.escape(r['item_id'])}</code></td>"
                f"<td>{html.escape(r['title'])}</td>"
                f"<td><span class='state'>{'PASS' if r['passed'] else 'FAIL'}"
                f"</span></td><td>{html.escape(r['evidence'])}</td></tr>"
                for r in os_service.verify_baseline(state))
            return (f"<table><tr><th>Item</th><th>Title</th><th>Result</th>"
                    f"<th>Evidence</th></tr>{rows}</table>")
        report = os_service.before_after_report(os_service.vulnerable_state())
        sb, sa = report["summary_before"], report["summary_after"]
        body = f"""{self._S02_LAB_BANNER}
<div class="card"><h2>S02 — Hardening baselines</h2>
<p>Baseline items as executable checks. Vulnerable fixture:
<b>{sb['passed']}/{sb['total']}</b> passing. Hardened fixture:
<b>{sa['passed']}/{sa['total']}</b> passing (pass rate
{sa['pass_rate']:.0%}).</p>
<p>Every item has a verification function and a simulated remediation —
the coverage audit enforces this structurally
(<code>/api/ossec/coverage</code>).</p></div>
<div class="card"><h3>Vulnerable fixture — verification results</h3>
{_table(os_service.vulnerable_state())}</div>
<div class="card"><h3>Hardened fixture — verification results</h3>
{_table(os_service.hardened_state())}</div>
<div class="card"><h3>Before/after proof of fix</h3>
<p>Applying all six finding remediations to the vulnerable fixture fixes
<b>{sum(1 for i in report['items'] if i['fixed'])}/{len(report['items'])}</b>
baseline items. Full per-item evidence is available via
<code>POST /api/ossec/remediate</code>.</p></div>
<p><a href="/project_s02">Back to S02</a></p>"""
        return _html(200, "S02 — Baselines", body)

    def s02_seed_submit(self, environ):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"),
                              keep_blank_values=True))
        try:
            seed = int(data.get("seed") or 7)
        except ValueError:
            seed = 7
        conn = self._conn()
        try:
            summary = os_service.seed_demo(conn, seed=seed)
        finally:
            conn.close()
        body = (f"<div class='card'><h2>S02 demo seeded</h2>"
                f"<p>{html.escape(json.dumps(summary))}</p>"
                f"<p><a href='/project_s02'>Back to S02</a></p></div>")
        return _html(200, "S02 — Seeded", body)

    # ---- S02 JSON API ------------------------------------------------------
    def api_os_baselines(self):
        return self._s02_json({
            "categories": list(os_service.BASELINE_CATEGORIES),
            "items": [self._s02_baseline_doc(b)
                      for b in os_service.BASELINES],
            "coverage_gaps": os_service.coverage_audit(),
        })

    def api_os_findings(self):
        vuln = os_service.vulnerable_state()
        out = []
        for f in os_service.FINDINGS:
            d = os_service.detect_finding(vuln, f["id"])
            out.append({
                "id": f["id"], "name": f["name"],
                "vuln_class": f["vuln_class"],
                "description": f["description"],
                "detection_method": f["detection_method"],
                "remediation": f["remediation"],
                "verification_method": f["verification_method"],
                "baseline_item_ids": f["baseline_item_ids"],
                "detected_on_vulnerable_fixture": d["detected"],
                "detection_evidence": d["evidence"],
            })
        return self._s02_json({"findings": out})

    def api_os_evaluate(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError as exc:
            return _json(422, _error_envelope("validation_failed", str(exc)))
        state = data.get("state")
        if not isinstance(state, dict):
            return _json(422, _error_envelope(
                "validation_failed",
                "Body must be JSON with a 'state' object matching the "
                "simulated system-state schema."))
        problems = os_service.validate_state(state)
        if problems:
            return _json(422, _error_envelope(
                "validation_failed",
                f"State schema problems: {'; '.join(problems)}"))
        results = os_service.verify_baseline(state)
        return self._s02_json({
            "state_label": state.get("label"),
            "results": results,
            "summary": os_service.baseline_summary(results),
        })

    def api_os_remediate(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError as exc:
            return _json(422, _error_envelope("validation_failed", str(exc)))
        state = data.get("state")
        if not isinstance(state, dict):
            return _json(422, _error_envelope(
                "validation_failed",
                "Body must be JSON with a 'state' object and optional "
                "'finding_ids' list."))
        problems = os_service.validate_state(state)
        if problems:
            return _json(422, _error_envelope(
                "validation_failed",
                f"State schema problems: {'; '.join(problems)}"))
        finding_ids = data.get("finding_ids")
        if finding_ids is not None and (
                not isinstance(finding_ids, list)
                or any(not isinstance(i, str) for i in finding_ids)):
            return _json(422, _error_envelope(
                "validation_failed", "'finding_ids' must be a list of strings."))
        try:
            report = os_service.before_after_report(state, finding_ids)
        except KeyError as exc:
            return _json(422, _error_envelope("validation_failed", str(exc)))
        return self._s02_json(report)

    def api_os_coverage(self):
        return self._s02_json({
            "baseline_items": len(os_service.BASELINES),
            "gaps": os_service.coverage_audit(),
            "full_coverage": not os_service.coverage_audit(),
        })

    def api_os_seed(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError:
            data = {}
        try:
            seed = int(data.get("seed", 7))
        except (ValueError, TypeError):
            seed = 7
        conn = self._conn()
        try:
            summary = os_service.seed_demo(conn, seed=seed)
        finally:
            conn.close()
        return self._s02_json({"seeded": summary})

    # ---- S05 pages ---------------------------------------------------------
    _S05_BANNER_HTML = (
        "<div class='card' style='border-left:4px solid #b00'>"
        "<strong>Educational demo only — NOT production cryptography.</strong> "
        "SHA-256, HMAC, and PBKDF2 run on Python's standard library. The "
        "symmetric construction is a <em>teaching aid</em> for nonce discipline "
        "and encrypt-then-MAC — never use it in production; real systems need "
        "an audited library (e.g. AES-GCM via <code>cryptography</code>). "
        "Asymmetric signatures and certificate validation are documented as "
        "design patterns, not implemented here. All keys are synthetic "
        "test-only material.</div>")

    def _crypto_json(self, data: dict, status: int = 200):
        return _json(status, {
            "educational_only": True,
            "warning": crypto_service.EDUCATIONAL_BANNER,
            "synthetic": True,
            **data,
        })

    def s05_page(self):
        body = (self._S05_BANNER_HTML +
                "<div class='card'><h2>S05 — Applied Cryptography</h2>"
                "<p>Correct use of <em>established</em> primitives, each paired "
                "with the classic failure mode it prevents.</p><ul>"
                "<li><b>REAL (implemented + tested):</b> SHA-256 hashing, "
                "HMAC-SHA256 (constant-time verify), PBKDF2 password hashing "
                "with a work factor — stdlib <code>hashlib</code>/<code>hmac</code>/"
                "<code>secrets</code>, checked against published vectors.</li>"
                "<li><b>EDUCATIONAL-ONLY:</b> SHA-256 counter-mode stream + "
                "encrypt-then-MAC — teaches nonce discipline and verify-before-"
                "decrypt. Bannered on every surface; never production.</li>"
                "<li><b>DESIGN-ONLY:</b> asymmetric sign/verify and X.509 "
                "certificate validation — documented patterns, not code.</li>"
                "<li><b>Key lifecycle:</b> versioned registry (generation, "
                "rotation, destruction, compromise response) backed by SQLite.</li>"
                "</ul><p><a href=\"/project_s05/primitives\">Primitives →</a> "
                "<a href=\"/project_s05/pitfalls\">Pitfalls →</a> "
                "<a href=\"/project_s05/keymgmt\">Key management →</a></p>"
                "<form method='post' action='/project_s05/demo'>"
                "<button type='submit'>Run guided demo (synthetic data)</button>"
                "</form></div>")
        return _html(200, "S05 — Applied Cryptography", body)

    def s05_primitives_page(self):
        rows = []
        for title, desc in [
            ("SHA-256 hashing", "One-way, deterministic, unkeyed. Integrity, "
             "not secrecy. Known-answer vectors: NIST FIPS 180-4."),
            ("HMAC-SHA256", "Keyed authentication. Verification uses "
             "hmac.compare_digest (constant time). RFC 4231 vectors 1–4 pass."),
            ("PBKDF2 password hashing", "Salted, iterated KDF with a work-factor "
             "parameter (demo default 100,000; calibrate up for real use). "
             "RFC 6070 vectors pass."),
            ("Educational encrypt-then-MAC", "SHA-256 counter-mode stream + "
             "HMAC tag over nonce + AAD + ciphertext. 256-bit random nonce "
             "from secrets; replays rejected; verify-before-decrypt."),
            ("Symmetric MAC 'sign' workflow", "Honestly labeled symmetric "
             "authentication — not a public-key signature. Paired with key "
             "rotation and destruction."),
        ]:
            rows.append(f"<tr><td>{html.escape(title)}</td>"
                        f"<td>{html.escape(desc)}</td></tr>")
        body = (self._S05_BANNER_HTML +
                "<div class='card'><h2>S05 Primitives</h2>"
                "<table><tr><th>Primitive</th><th>Correct-use summary</th></tr>"
                + "".join(rows) + "</table>"
                "<p><a href='/project_s05'>Back to S05</a></p></div>")
        return _html(200, "S05 — Primitives", body)

    def s05_pitfalls_page(self):
        items = []
        for p in crypto_service.PITFALLS:
            items.append(
                f"<div class='card'><h3>{html.escape(p['id'])} — "
                f"{html.escape(p['title'])}</h3>"
                f"<p><b>The mistake:</b> {html.escape(p['the_mistake'])}</p>"
                f"<p><b>How it fails:</b> {html.escape(p['how_it_fails'])}</p>"
                f"<p><b>Avoided by:</b> {html.escape(p['avoided_by'])}</p></div>")
        body = (self._S05_BANNER_HTML +
                "<div class='card'><h2>S05 Pitfalls catalog</h2>"
                "<p>Each classic mistake mapped to the demonstration that "
                "avoids it. Every 'DON'T' fixture fails closed.</p></div>"
                + "".join(items) +
                "<p><a href='/project_s05'>Back to S05</a></p>")
        return _html(200, "S05 — Pitfalls", body)

    def s05_keymgmt_page(self):
        conn = self._conn()
        try:
            inventory = crypto_service.key_inventory(conn)
        finally:
            conn.close()
        if not inventory:
            table = "<p>No demo keys yet — run the guided demo below.</p>"
        else:
            rows = "".join(
                f"<tr><td>v{k['key_version']}</td><td>{k['status']}</td>"
                f"<td>{html.escape(k['created_at'] or '')}</td>"
                f"<td>{len(k['events'])} events</td></tr>"
                for k in inventory)
            table = ("<table><tr><th>Version</th><th>Status</th><th>Created</th>"
                     "<th>Events</th></tr>" + rows + "</table>")
        body = (self._S05_BANNER_HTML +
                "<div class='card'><h2>S05 Key management</h2>"
                "<p>Versioned registry: generation (<code>secrets</code>), "
                "rotation (old data stays readable), destruction (wipe + "
                "tombstone refuses use), compromise response (rotate + "
                "re-encrypt). All keys synthetic, test-only.</p>" + table +
                "<form method='post' action='/project_s05/demo'>"
                "<button type='submit'>Run guided demo (synthetic data)</button>"
                "</form><p><a href='/project_s05'>Back to S05</a></p></div>")
        return _html(200, "S05 — Key Management", body)

    def s05_demo_submit(self, environ):
        conn = self._conn()
        try:
            sign_steps = crypto_service.demo_sign_workflow(
                conn, "web-demo", b"synthetic contract v3")
            enc = crypto_service.demo_encrypt_workflow(b"synthetic payload")
        finally:
            conn.close()
        items = "".join(
            f"<li><b>{html.escape(s['step'])}:</b> {html.escape(s['detail'])}</li>"
            for s in sign_steps)
        body = (self._S05_BANNER_HTML +
                "<div class='card'><h2>S05 guided demo (synthetic data)</h2>"
                "<h3>MAC sign workflow across rotation + destruction</h3><ol>"
                + items + "</ol>"
                f"<h3>Educational encrypt → tamper → decrypt</h3>"
                f"<p>Roundtrip ok: {enc['roundtrip_ok']}; "
                f"{html.escape(enc['tamper_result'])}</p>"
                "<p><a href='/project_s05'>Back to S05</a> "
                "<a href='/project_s05/keymgmt'>Key management →</a></p></div>")
        return _html(200, "S05 — Demo", body)

    # ---- N01: network forensics (synthetic captures, lawful lab only) -----
    _N01_BANNER_HTML = (
        "<div class='banner'><b>N01 — Network Forensics.</b> LAWFUL LAB ONLY: "
        "every capture below is <b>synthetic</b> packets generated in-process "
        "by a seeded script; this app contains no socket/pcap code and cannot "
        "tap a real network.</div>")

    _N01_SCENARIO_BLURBS = {
        "baseline_clean": "Routine lab chatter only (LAB-HTTP, LAB-DNS, "
            "LAB-NTP). Ground truth: zero anomalies.",
        "port_scan": "Attacker VM probes 24 ports on the lab server; the "
            "defense denies every probe (RST). Ground truth: 1 port-scan anomaly.",
        "c2_beaconing": "Compromised lab workstation emits LAB-BEACON "
            "frames every 60 s (+/-0.2 s jitter) to a synthetic external host. "
            "Ground truth: 1 beaconing anomaly at ~60 s interval.",
        "data_exfiltration": "560,000 synthetic bytes outbound on unusual "
            "port 31337. Ground truth: 1 byte-exfiltration anomaly.",
    }

    def _nf_json(self, data: dict, status: int = 200):
        return _json(status, {
            "synthetic": True,
            "ethical_banner": nf_service.ETHICAL_BANNER,
            **data,
        })

    def _nf_capture_id(self, environ):
        qs = dict(parse_qsl(environ.get("QUERY_STRING", "") or ""))
        raw = qs.get("capture_id")
        if raw is None or raw == "":
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    def _nf_latest_or_404(self, conn, capture_id):
        caps = nf_service.list_captures(conn)
        if not caps:
            return None, None
        if capture_id is None:
            capture_id = caps[0]["id"]
        try:
            cap = nf_service.get_capture(conn, capture_id)
        except nf_service.NetForensicsError:
            return None, None
        return cap, capture_id

    def _nf_no_captures_page(self):
        return _html(404, "N01 — no captures", self._N01_BANNER_HTML +
                     "<div class='card'><p>No captures yet. "
                     "<a href='/project_n01'>Run one</a>.</p></div>")

    def n01_page(self):
        conn = self._conn()
        try:
            captures = nf_service.list_captures(conn)
        finally:
            conn.close()
        plan_rows = "".join(
            f"<tr><td><code>{html.escape(sc)}</code></td>"
            f"<td>{html.escape(blurb)}</td></tr>"
            for sc, blurb in self._N01_SCENARIO_BLURBS.items())
        options = "".join(
            f"<option value='{sc}'>{sc}</option>"
            for sc in nf_service.SCENARIOS)
        if captures:
            cap_rows = "".join(
                f"<tr><td>{c['id']}</td>"
                f"<td>{html.escape(c['capture_ref'])}</td>"
                f"<td>{html.escape(c['scenario'])}</td>"
                f"<td>{c['packet_count']}</td>"
                f"<td><a href='/project_n01/sessions?capture_id={c['id']}'>"
                f"Sessions</a> <a href='/project_n01/timeline?capture_id={c['id']}'>"
                f"Timeline</a> <a href='/project_n01/anomalies?capture_id={c['id']}'>"
                f"Anomalies</a> <a href='/project_n01/scoping?capture_id={c['id']}'>"
                f"Scoping</a> <a href='/project_n01/report?capture_id={c['id']}'>"
                f"Report</a></td></tr>"
                for c in captures)
            cap_table = ("<table><tr><th>ID</th><th>Ref</th><th>Scenario</th>"
                         "<th>Packets</th><th>Views</th></tr>" + cap_rows +
                         "</table>")
        else:
            cap_table = ("<p>No captures yet — run a scripted scenario below "
                         "(synthetic data only).</p>")
        body = (self._N01_BANNER_HTML +
                "<div class='card'><h2>N01 — Network Forensics: Packet Capture "
                "to Evidentiary Report</h2>"
                "<p>Capture plan → synthetic capture → session reconstruction → "
                "protocol notes → timeline → anomaly detection (documented "
                "baseline) → scoping → evidentiary report (facts vs inference). "
                "Every claim cites a packet range.</p>"
                "<h3>Capture plan (scripted scenarios, seeded, deterministic)</h3>"
                "<table><tr><th>Scenario</th><th>What it scripts</th></tr>"
                + plan_rows + "</table>"
                "<h3>Run a capture</h3>"
                "<form method='post' action='/project_n01/run'>"
                f"<label>Scenario <select name='scenario'>{options}</select></label> "
                "<label>Seed <input name='seed' value='20261023' size='10'></label> "
                "<button type='submit'>Run (synthetic)</button></form>"
                "<h3>Saved captures</h3>" + cap_table + "</div>")
        return _html(200, "N01 — Network Forensics", body)

    def _nf_persist(self, conn, scenario, seed, result):
        base = f"{scenario}-{seed}"
        ref, n = base, 1
        while True:
            try:
                cid = nf_service.save_capture(
                    conn, ref, scenario, seed, result["packets"])
                break
            except nf_service.NetForensicsError:
                n += 1
                ref = f"{base}-{n}"
        nf_service.save_sessions(conn, cid, result["sessions"])
        nf_service.save_anomalies(conn, cid, result["anomalies"])
        nf_service.save_report(conn, cid, ref + "-report", result["report"])
        return cid, ref

    def n01_run_submit(self, environ):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"),
                              keep_blank_values=True))
        scenario = (data.get("scenario") or "").strip()
        if scenario not in nf_service.SCENARIOS:
            return _html(422, "N01 — invalid scenario",
                         self._N01_BANNER_HTML +
                         "<div class='card'><p>Unknown scenario. "
                         "<a href='/project_n01'>Back</a></p></div>")
        try:
            seed = int((data.get("seed") or "20261023").strip())
        except ValueError:
            seed = 20261023
        result = nf_service.run_full_pipeline(scenario, seed=seed)
        conn = self._conn()
        try:
            cid, ref = self._nf_persist(conn, scenario, seed, result)
        finally:
            conn.close()
        return self.n01_sessions_page_for(cid, ref)

    def n01_sessions_page_for(self, cid, ref):
        conn = self._conn()
        try:
            sessions = nf_service.list_sessions(conn, cid)
        finally:
            conn.close()
        rows = "".join(
            f"<tr><td>{html.escape(s['session_key'])}</td>"
            f"<td>[{s['start_index']}, {s['end_index']}]</td>"
            f"<td>{s['packet_count']}</td><td>{s['total_bytes']}</td>"
            f"<td>{'yes' if s['handshake_complete'] else 'no'}</td>"
            f"<td>{'yes' if s['teardown_seen'] else 'no'}</td>"
            f"<td>{html.escape(s['protocol_note'] or '—')}</td></tr>"
            for s in sessions)
        body = (self._N01_BANNER_HTML +
                "<div class='card'>"
                f"<h2>N01 Sessions — {html.escape(ref)}</h2>"
                "<p>Bidirectional 5-tuple reassembly with handshake/teardown "
                "tracking on the synthetic TCP-ish flags.</p>"
                "<table><tr><th>Session</th><th>Packet range</th>"
                "<th>Packets</th><th>Bytes</th><th>Handshake</th>"
                "<th>Teardown</th><th>Protocols</th></tr>" + rows + "</table>"
                f"<p><a href='/project_n01/timeline?capture_id={cid}'>Timeline →</a> "
                f"<a href='/project_n01'>Back to N01</a></p></div>")
        return _html(200, "N01 — Sessions", body)

    def n01_sessions_page(self, environ):
        conn = self._conn()
        try:
            cap, cid = self._nf_latest_or_404(conn, self._nf_capture_id(environ))
        finally:
            conn.close()
        if cap is None:
            return self._nf_no_captures_page()
        return self.n01_sessions_page_for(cid, cap["capture_ref"])

    def n01_timeline_page(self, environ):
        conn = self._conn()
        try:
            cap, cid = self._nf_latest_or_404(conn, self._nf_capture_id(environ))
            if cap is None:
                return self._nf_no_captures_page()
            packets = nf_service.list_packets(conn, cid)
            sessions = nf_service.list_sessions(conn, cid)
            anomalies = nf_service.list_anomalies(conn, cid)
        finally:
            conn.close()
        pkt_dicts = [{"index": p["pkt_index"], "ts": p["ts"]} for p in packets]
        sess = [{
            "session_key": s["session_key"], "src": "", "dst": "",
            "src_port": 0, "dst_port": 0,
            "start_index": s["start_index"], "end_index": s["end_index"],
            "packet_count": s["packet_count"],
            "total_bytes": s["total_bytes"],
            "start_ts": packets[s["start_index"]]["ts"] if packets else 0,
        } for s in sessions]
        alerts = [{
            "ts": packets[a["start_index"]]["ts"] if packets else 0,
            "kind": "alert", "alert_type": a["anomaly_type"],
            "summary": a["summary"],
            "packet_range": [a["start_index"], a["end_index"]],
        } for a in anomalies]
        timeline = nf_service.build_timeline(pkt_dicts, sess, alerts)
        rows = "".join(
            f"<tr><td>{html.escape(e['kind'])}</td>"
            f"<td>{html.escape(e['summary'])}</td>"
            f"<td>[{e['packet_range'][0]}, {e['packet_range'][1]}]</td></tr>"
            for e in timeline)
        body = (self._N01_BANNER_HTML +
                "<div class='card'>"
                f"<h2>N01 Timeline — {html.escape(cap['capture_ref'])}</h2>"
                f"<p>{len(timeline)} events; every event cites a packet range.</p>"
                "<table><tr><th>Kind</th><th>Event</th><th>Packet range</th></tr>"
                + rows + "</table>"
                f"<p><a href='/project_n01/anomalies?capture_id={cid}'>Anomalies →</a> "
                f"<a href='/project_n01'>Back to N01</a></p></div>")
        return _html(200, "N01 — Timeline", body)

    def n01_anomalies_page(self, environ):
        conn = self._conn()
        try:
            cap, cid = self._nf_latest_or_404(conn, self._nf_capture_id(environ))
            if cap is None:
                return self._nf_no_captures_page()
            anomalies = nf_service.list_anomalies(conn, cid)
        finally:
            conn.close()
        base = nf_service.BASELINE
        base_rows = "".join(
            f"<tr><td><code>{html.escape(k)}</code></td>"
            f"<td>{html.escape(str(v))}</td></tr>"
            for k, v in base.items() if k != "name")
        if anomalies:
            rows = "".join(
                f"<tr><td>{html.escape(a['anomaly_type'])}</td>"
                f"<td>{html.escape(a['summary'])}</td>"
                f"<td>[{a['start_index']}, {a['end_index']}]</td>"
                f"<td>{html.escape(a['confidence'])}</td></tr>"
                for a in anomalies)
            table = ("<table><tr><th>Type</th><th>Detail</th>"
                     "<th>Packet range</th><th>Confidence</th></tr>"
                     + rows + "</table>")
        else:
            table = ("<p><b>No anomalies</b> — the capture is consistent "
                     "with the documented baseline.</p>")
        body = (self._N01_BANNER_HTML +
                "<div class='card'>"
                f"<h2>N01 Anomalies — {html.escape(cap['capture_ref'])}</h2>"
                + table +
                f"<h3>Documented baseline: {html.escape(base['name'])}</h3>"
                "<table><tr><th>Threshold</th><th>Value</th></tr>"
                + base_rows + "</table>"
                f"<p><a href='/project_n01/scoping?capture_id={cid}'>Scoping →</a> "
                f"<a href='/project_n01'>Back to N01</a></p></div>")
        return _html(200, "N01 — Anomalies", body)

    def n01_scoping_page(self, environ):
        conn = self._conn()
        try:
            cap, cid = self._nf_latest_or_404(conn, self._nf_capture_id(environ))
            if cap is None:
                return self._nf_no_captures_page()
            anomalies = nf_service.list_anomalies(conn, cid)
            sessions = nf_service.list_sessions(conn, cid)
            packets = nf_service.list_packets(conn, cid)
        finally:
            conn.close()
        anoms = [dict(a, type=a["anomaly_type"],
                      packet_range=[a["start_index"], a["end_index"]],
                      detail=json.loads(a["detail_json"]))
                 for a in anomalies]
        sess = [dict(s) for s in sessions]
        pkts = [{"index": p["pkt_index"], "ts": p["ts"]} for p in packets]
        scope = nf_service.scope_incident(anoms, sess, pkts)
        hosts = ", ".join(html.escape(h) for h in scope["affected_hosts"]) or "—"
        sesslist = ", ".join(html.escape(s) for s in scope["affected_sessions"]) or "—"
        body = (self._N01_BANNER_HTML +
                "<div class='card'><h2>N01 Scoping memo — "
                f"{html.escape(cap['capture_ref'])}</h2>"
                "<p>Incident scope is derived mechanically from the detected "
                "anomalies — no manual attribution beyond the lab.</p><ul>"
                f"<li><b>Affected hosts:</b> {hosts}</li>"
                f"<li><b>Affected sessions:</b> {sesslist}</li>"
                f"<li><b>Anomaly types:</b> {', '.join(scope['anomaly_types']) or '—'}</li>"
                f"<li><b>Packet range:</b> [{scope['start_index']}, {scope['end_index']}]</li>"
                f"</ul><p><b>Memo:</b> {html.escape(scope['summary'])}</p>"
                f"<p><a href='/project_n01/report?capture_id={cid}'>Report →</a> "
                f"<a href='/project_n01'>Back to N01</a></p></div>")
        return _html(200, "N01 — Scoping", body)

    def n01_report_page(self, environ):
        conn = self._conn()
        try:
            cap, cid = self._nf_latest_or_404(conn, self._nf_capture_id(environ))
            if cap is None:
                return self._nf_no_captures_page()
            stored = nf_service.get_report(conn, cid)
        finally:
            conn.close()
        rep = stored["report"]
        fact_rows = "".join(
            f"<tr><td>{html.escape(f['statement'])}</td>"
            f"<td>[{f['packet_range'][0]}, {f['packet_range'][1]}]</td></tr>"
            for f in rep["facts"])
        inf_rows = "".join(
            f"<tr><td>{html.escape(i['statement'])}</td>"
            f"<td>{html.escape(i['confidence'])}</td>"
            f"<td>[{i['packet_range'][0]}, {i['packet_range'][1]}]</td></tr>"
            for i in rep["inferences"])
        body = (self._N01_BANNER_HTML +
                "<div class='card'><h2>N01 Evidentiary report — "
                f"{html.escape(cap['capture_ref'])}</h2>"
                f"<p>Scenario <code>{html.escape(rep['scenario'])}</code>, "
                f"seed <code>{rep['seed']}</code>, {rep['packet_count']} "
                "synthetic packets. Ground-truth match: "
                f"<b>{rep['ground_truth_match']}</b>.</p>"
                "<h3>Facts (observed; every fact cites a packet range)</h3>"
                "<table><tr><th>Fact</th><th>Packet range</th></tr>"
                + fact_rows + "</table>"
                "<h3>Inferences (interpretation; confidence required)</h3>"
                "<table><tr><th>Inference</th><th>Confidence</th>"
                "<th>Packet range</th></tr>" + inf_rows + "</table>"
                "<p><b>Scope:</b> "
                f"{html.escape(rep['scope']['summary'])}</p>"
                f"<p><a href='/project_n01'>Back to N01</a></p></div>")
        return _html(200, "N01 — Report", body)

    # ---- N01 JSON API (synthetic data, bannered) ----------------------------
    def api_nf_captures(self):
        conn = self._conn()
        try:
            captures = nf_service.list_captures(conn)
        finally:
            conn.close()
        return self._nf_json({"captures": captures})

    def api_nf_capture(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError as exc:
            return _json(422, _error_envelope("validation_failed", str(exc)))
        scenario = data.get("scenario")
        if scenario not in nf_service.SCENARIOS:
            return _json(422, _error_envelope(
                "validation_failed",
                f"scenario must be one of {list(nf_service.SCENARIOS)}"))
        seed = data.get("seed", 20261023)
        if not isinstance(seed, int):
            return _json(422, _error_envelope(
                "validation_failed", "seed must be an int"))
        result = nf_service.run_full_pipeline(scenario, seed=seed)
        conn = self._conn()
        try:
            cid, ref = self._nf_persist(conn, scenario, seed, result)
        finally:
            conn.close()
        return self._nf_json({
            "capture_id": cid,
            "capture_ref": ref,
            "scenario": scenario,
            "packet_count": len(result["packets"]),
            "session_count": len(result["sessions"]),
            "anomalies": [a["type"] for a in result["anomalies"]],
            "ground_truth_match": result["report"]["ground_truth_match"],
        })

    def api_nf_anomalies(self, environ):
        conn = self._conn()
        try:
            cap, cid = self._nf_latest_or_404(conn, self._nf_capture_id(environ))
            if cap is None:
                return _json(404, _error_envelope(
                    "not_found", "no captures yet"))
            anomalies = nf_service.list_anomalies(conn, cid)
        finally:
            conn.close()
        return self._nf_json({
            "capture_id": cid,
            "anomalies": [dict(a, detail=json.loads(a["detail_json"]))
                            for a in anomalies],
        })

    def api_nf_report(self, environ):
        conn = self._conn()
        try:
            cap, cid = self._nf_latest_or_404(conn, self._nf_capture_id(environ))
            if cap is None:
                return _json(404, _error_envelope(
                    "not_found", "no captures yet"))
            stored = nf_service.get_report(conn, cid)
        finally:
            conn.close()
        return self._nf_json({"capture_id": cid, "report": stored["report"]})

    # ---- N02: cyber risk assessment & management (synthetic workbook) ------
    _N02_BANNER_HTML = (
        "<div class='banner'><b>N02 — Cyber Risk Assessment &amp; Management.</b> "
        "FICTIONAL COMPANY — every asset, threat, rating, cost, and effort below "
        "is <b>synthetic</b>. Scores are illustrative worked examples of the "
        "documented rules — <b>never</b> an audit opinion or certification.</div>")

    def _risk_json(self, data: dict, status: int = 200):
        return _json(status, {
            "synthetic": True,
            "ethical_banner": risk_service.ETHICAL_BANNER,
            **data,
        })

    @staticmethod
    def _fmt_usd(cents: int) -> str:
        return f"${cents / 100:,.2f}"

    def _n02_unseeded_page(self):
        body = (self._N02_BANNER_HTML +
                "<div class='card'><h2>N02 — Cyber Risk Assessment &amp; Management</h2>"
                "<p>Fictional company: <b>Synthetic Test Co.</b></p>"
                "<p>No workbook seeded yet.</p>"
                "<form method='post' action='/project_n02/seed'>"
                "<button type='submit'>Seed synthetic workbook</button></form></div>")
        return _html(200, "N02 — Risk Workbook", body)

    def _n02_nav(self):
        return ("<p><a href='/project_n02'>Workbook</a> · "
                "<a href='/project_n02/scales'>Scales</a> · "
                "<a href='/project_n02/register'>Risk register</a> · "
                "<a href='/project_n02/remediation'>Remediation plan</a> · "
                "<a href='/project_n02/residual'>Residual-risk memo</a></p>")

    def n02_page(self):
        conn = self._conn()
        try:
            if not risk_service.seeded(conn):
                return self._n02_unseeded_page()
            register = risk_service.list_risks(conn)
            totals = risk_service.register_totals(register)
            assets = risk_service.list_assets(conn)
        finally:
            conn.close()
        comp = risk_service.COMPANY
        bc = totals["band_counts"]
        body = (self._N02_BANNER_HTML +
                "<div class='card'><h2>N02 — Cyber Risk Assessment &amp; Management</h2>"
                f"<p><b>{html.escape(comp['name'])}</b> (fictional): "
                f"{html.escape(comp['profile'])}</p>"
                f"<p><b>{len(assets)}</b> synthetic assets · "
                f"<b>{totals['count']}</b> register entries · "
                f"critical <b>{bc['critical']}</b> · high <b>{bc['high']}</b> · "
                f"medium <b>{bc['medium']}</b> · low <b>{bc['low']}</b></p>"
                + self._n02_nav() +
                "<form method='post' action='/project_n02/seed'>"
                "<button type='submit'>Re-seed synthetic workbook</button></form></div>"
                "<div class='card'><h3>Workbook sections</h3><ul>"
                "<li><b>Scales</b> — likelihood × impact scales with per-level rationale, "
                "band thresholds, and the prioritization rule.</li>"
                "<li><b>Risk register</b> — every entry traces to an asset + threat + "
                "validated S01/S02 control (or an explicit accepted gap).</li>"
                "<li><b>Remediation plan</b> — synthetic cost/effort per remediation, "
                "ordered by the documented reproducible rule.</li>"
                "<li><b>Residual-risk memo</b> — register recomputed after planned "
                "remediations, with per-risk deltas and reconciled totals.</li>"
                "</ul></div>")
        return _html(200, "N02 — Risk Workbook", body)

    def n02_scales_page(self):
        doc = risk_service.scales_doc()
        l_rows = "".join(
            f"<tr><td>{s['level']}</td><td>{html.escape(s['label'])}</td>"
            f"<td>{html.escape(s['rationale'])}</td></tr>"
            for s in doc["likelihood_scale"])
        i_rows = "".join(
            f"<tr><td>{s['level']}</td><td>{html.escape(s['label'])}</td>"
            f"<td>{html.escape(s['rationale'])}</td></tr>"
            for s in doc["impact_scale"])
        b_rows = "".join(
            f"<tr><td>{b['band']}</td><td>{b['min']}–{b['max']}</td></tr>"
            for b in doc["bands"])
        body = (self._N02_BANNER_HTML + "<div class='card'><h2>Scoring scales</h2>"
                + self._n02_nav() +
                f"<p><b>Scoring rule:</b> {html.escape(doc['scoring_rule'])}</p>"
                "<h3>Likelihood scale (1–5)</h3>"
                "<table><tr><th>Level</th><th>Label</th><th>Rationale</th></tr>"
                + l_rows + "</table>"
                "<h3>Impact scale (1–5, rated per C / I / A)</h3>"
                "<table><tr><th>Level</th><th>Label</th><th>Rationale</th></tr>"
                + i_rows + "</table>"
                "<h3>Risk bands (score = likelihood × impact)</h3>"
                "<table><tr><th>Band</th><th>Score range</th></tr>"
                + b_rows + "</table>"
                "<h3>Remediation prioritization rule</h3>"
                f"<p>{html.escape(doc['prioritization_rule'])}</p></div>")
        return _html(200, "N02 — Scales", body)

    def n02_register_page(self):
        conn = self._conn()
        try:
            if not risk_service.seeded(conn):
                return self._n02_unseeded_page()
            register = risk_service.list_risks(conn)
        finally:
            conn.close()
        rows = ""
        for r in register:
            ctrls = "<br>".join(
                html.escape(c["ref"]) +
                (f" — accepted gap: {html.escape(c['reason'])}"
                 if c["ref"] == "GAP" else "")
                for c in r["controls"])
            rows += (f"<tr><td>{r['risk_id']}</td>"
                     f"<td>{html.escape(r['asset_name'])}</td>"
                     f"<td>{html.escape(r['threat_name'])}</td>"
                     f"<td>{r['likelihood']}×{r['impact']}={r['score']}</td>"
                     f"<td>{r['band']}</td><td>{ctrls}</td>"
                     f"<td>{html.escape(r['treatment'])}</td></tr>")
        body = (self._N02_BANNER_HTML + "<div class='card'><h2>Risk register</h2>"
                + self._n02_nav() +
                "<p>Every entry traces to an asset + a threat + ≥1 validated "
                "control reference (<code>GAP</code> = explicit accepted gap with "
                "a written reason).</p>"
                "<table><tr><th>Risk</th><th>Asset</th><th>Threat</th>"
                "<th>L×I=Score</th><th>Band</th><th>Controls</th>"
                "<th>Treatment</th></tr>" + rows + "</table></div>")
        return _html(200, "N02 — Risk Register", body)

    def n02_remediation_page(self):
        conn = self._conn()
        try:
            if not risk_service.seeded(conn):
                return self._n02_unseeded_page()
            plan = risk_service.list_remediations(conn)
        finally:
            conn.close()
        rows = ""
        for i, r in enumerate(plan, 1):
            rows += (f"<tr><td>{i}</td><td>{r['rem_id']}</td>"
                     f"<td>{html.escape(r['title'])}</td>"
                     f"<td>{r['risk_reduction']}</td>"
                     f"<td>{r['effort_hours']}h ({html.escape(r['effort_basis'])})</td>"
                     f"<td>{r['ratio_exact']}</td>"
                     f"<td>{self._fmt_usd(int(Decimal(r['cost_usd']) * 100))} "
                     f"({html.escape(r['cost_basis'])})</td>"
                     f"<td>{', '.join(r['affected_risks'])}</td></tr>")
        body = (self._N02_BANNER_HTML + "<div class='card'><h2>Remediation plan</h2>"
                + self._n02_nav() +
                "<p>Ordered by the documented rule: risk-reduction-per-effort "
                "ratio descending, ties by remediation id. All costs and efforts "
                "are <b>synthetic estimates</b>.</p>"
                "<table><tr><th>#</th><th>ID</th><th>Remediation</th>"
                "<th>Score reduction</th><th>Effort</th><th>Ratio</th>"
                "<th>Cost</th><th>Affected risks</th></tr>" + rows + "</table></div>")
        return _html(200, "N02 — Remediation Plan", body)

    def n02_residual_page(self):
        conn = self._conn()
        try:
            if not risk_service.seeded(conn):
                return self._n02_unseeded_page()
            stmt = risk_service.get_residual_report(conn)
        finally:
            conn.close()
        inh, res = stmt["inherent"], stmt["residual"]
        d_rows = "".join(
            f"<tr><td>{d['risk_id']}</td><td>{d['inherent_score']} ({d['inherent_band']})</td>"
            f"<td>{d['residual_score']} ({d['residual_band']})</td>"
            f"<td>{d['delta']}</td>"
            f"<td>{', '.join(d['applied_remediations']) or '—'}</td></tr>"
            for d in stmt["deltas"])
        body = (self._N02_BANNER_HTML + "<div class='card'><h2>Residual-risk memo</h2>"
                + self._n02_nav() +
                f"<p>{html.escape(stmt['memo'])}</p>"
                f"<p><b>Totals:</b> inherent {inh['total_score']} → residual "
                f"{res['total_score']} (reduction {stmt['total_reduction']}, "
                f"reconciled). Critical {inh['band_counts']['critical']}→"
                f"{res['band_counts']['critical']}, high "
                f"{inh['band_counts']['high']}→{res['band_counts']['high']}, "
                f"medium {inh['band_counts']['medium']}→{res['band_counts']['medium']}, "
                f"low {inh['band_counts']['low']}→{res['band_counts']['low']}.</p>"
                "<h3>Per-risk deltas</h3>"
                "<table><tr><th>Risk</th><th>Inherent</th><th>Residual</th>"
                "<th>Δ</th><th>Applied remediations</th></tr>" + d_rows + "</table></div>")
        return _html(200, "N02 — Residual-Risk Memo", body)

    def n02_seed_submit(self):
        conn = self._conn()
        try:
            summary = risk_service.seed_demo(conn)
        finally:
            conn.close()
        log_system_event("n02.seeded", summary)
        body = (f"<div class='card'><h2>N02 workbook seeded</h2>"
                f"<p>{html.escape(json.dumps(summary))}</p>"
                f"<p><a href='/project_n02'>Back to N02</a></p></div>")
        return _html(200, "N02 — Seeded", body)

    # ---- N03: safeguard — victim-centered, lawful abuse-response framework --
    _N03_BANNER_HTML = (
        "<div class='warn'><b>⚠ SYNTHETIC CASES ONLY — FRAMEWORK DEMONSTRATION, "
        "NOT CASEWORK.</b> Every case is a written synthetic scenario. This "
        "framework <b>refers — it does not pursue</b>: no vigilante "
        "investigation, no contact with suspected offenders, no accessing "
        "private accounts or devices, no distribution of intimate imagery, "
        "and never any accessing, possessing, or reproducing of child sexual "
        "abuse material. Anyone using this for harassment, doxxing, or "
        "vigilante action is misusing it. Suspected child sexual "
        "exploitation: report to the NCMEC CyberTipline; emergencies: 911."
        "</div>")

    def _sg_json(self, data: dict, status: int = 200):
        return _json(status, {
            "synthetic": True,
            "method_demo_only": True,
            "warning": ("SYNTHETIC CASES ONLY. A victim-centered, lawful "
                        "triage-and-referral framework demonstration — not "
                        "casework, not legal advice. It refers; it does not "
                        "pursue, and it performs no outreach."),
            **data,
        })

    def _n03_nav(self):
        return ("<p><a href='/project_n03'>Framework</a> · "
                "<a href='/project_n03/playbooks'>Playbooks</a> · "
                "<a href='/project_n03/cases'>Cases</a> · "
                "<a href='/project_n03/preservation'>Preservation checklist</a> · "
                "<a href='/project_n03/reporting'>Reporting guide</a> · "
                "<a href='/project_n03/referrals'>Referral directory</a></p>")

    def n03_page(self):
        playbooks = sg_service.list_playbooks()
        rows = "".join(
            f"<li><a href='/project_n03/playbooks/{p['category']}'>"
            f"{html.escape(p['title'])}</a> — {p['step_count']} steps"
            + (" <b>(refer immediately — no investigation)</b>" if p['no_investigation'] else "")
            + "</li>"
            for p in playbooks)
        body = (self._N03_BANNER_HTML +
                "<div class='card'><h2>N03 — Investigating Cyberpredators &amp; "
                "Online Abuse: Victim-Centered, Lawful</h2>"
                "<p>A triage-and-referral <em>framework</em> practiced on synthetic "
                "cases: <b>intake → safety triage → playbook → preserve / report / "
                "refer → referral → close</b>.</p><ul>"
                "<li><b>Victim-centered:</b> safety planning first; evidence-"
                "preservation guidance for victims; trauma-informed documentation.</li>"
                "<li><b>Lawful:</b> platform reporting flows and referral paths "
                "(NCMEC CyberTipline, FBI IC3, local law enforcement, victim-support "
                "orgs). This framework <b>refers — it does not pursue</b>.</li>"
                "<li><b>Closed action vocabulary:</b> the only recordable actions are "
                "<code>preserve</code>, <code>report</code>, <code>refer</code>, "
                "<code>safety_plan</code>, <code>document</code>, "
                "<code>escalate_to_authorities</code> — structurally enforced.</li>"
                "<li><b>Attribution discipline:</b> findings are "
                "<code>lead</code> / <code>verified</code> / <code>unknown</code>; "
                "“unknown” is an honest finding.</li>"
                "</ul><h3>Per-category response playbooks</h3><ul>" + rows + "</ul>"
                "<form method='post' action='/project_n03/demo'>"
                "<button type='submit'>Run guided demo (synthetic case, end to end)</button>"
                "</form>" + self._n03_nav() + "</div>")
        return _html(200, "N03 — Safeguard Framework", body)

    def n03_playbooks_page(self):
        playbooks = sg_service.list_playbooks()
        rows = "".join(
            f"<div class='card'><h3><a href='/project_n03/playbooks/{p['category']}'>"
            f"{html.escape(p['title'])}</a></h3>"
            f"<p>{html.escape(p['understand'])}</p>"
            f"<p>{p['step_count']} steps · "
            + ("<b>refer immediately — no investigation</b>" if p['no_investigation']
               else "preserve → report → refer") + "</p></div>"
            for p in playbooks)
        body = (self._N03_BANNER_HTML + self._n03_nav() +
                "<h2>N03 — Response Playbooks</h2>" + rows)
        return _html(200, "N03 — Playbooks", body)

    def n03_playbook_page(self, category: str):
        try:
            pb = sg_service.get_playbook(category)
        except sg_service.SafeguardError as exc:
            return _json(404, _error_envelope("not_found", str(exc)))
        steps = "".join(
            f"<li><b>[{html.escape(s['action'])}]</b> {html.escape(s['title'])}"
            f"<br>{html.escape(s['detail'])}"
            f"<br><em>Authority: {html.escape(s['authority'])}</em></li>"
            for s in pb["steps"])
        noinv = ("<p><b>Refer immediately — no investigation.</b> This playbook "
                 "contains no investigation steps by design.</p>"
                 if pb["no_investigation"] else "")
        body = (self._N03_BANNER_HTML + self._n03_nav() +
                f"<div class='card'><h2>{html.escape(pb['title'])}</h2>" + noinv +
                f"<p>{html.escape(sg_service.CATEGORIES[category]['understand'])}</p>"
                f"<ol>{steps}</ol>"
                "<p><a href='/project_n03/playbooks'>All playbooks</a></p></div>")
        return _html(200, f"N03 — {pb['title']}", body)

    def n03_cases_page(self):
        conn = self._conn()
        try:
            cases = sg_service.list_cases(conn)
        finally:
            conn.close()
        rows = "".join(
            f"<li><a href='/project_n03/cases/{c['id']}'>{html.escape(c['case_ref'])}</a> "
            f"— {html.escape(sg_service.CATEGORIES[c['category']]['title'])} "
            f"<em>({html.escape(c['stage'])})</em></li>"
            for c in cases) or "<li><em>No cases yet — run the demo below.</em></li>"
        body = (self._N03_BANNER_HTML + self._n03_nav() +
                "<div class='card'><h2>N03 — Synthetic Cases</h2><ul>" + rows + "</ul>"
                "<form method='post' action='/project_n03/demo'>"
                "<button type='submit'>Run guided demo (synthetic case, end to end)</button>"
                "</form><p>Programmatic intake: <code>POST /api/safeguard/cases</code> "
                "with <code>case_ref</code>, <code>category</code>, "
                "<code>reporter_role</code>, <code>summary</code> (non-graphic), "
                "optional <code>immediate_danger</code>, <code>involves_minor</code>.</p>"
                "</div>")
        return _html(200, "N03 — Cases", body)

    def n03_case_page(self, case_id: str):
        conn = self._conn()
        try:
            detail = sg_service.get_case_detail(conn, int(case_id))
        except sg_service.SafeguardError as exc:
            conn.close()
            return _json(404, _error_envelope("not_found", str(exc)))
        finally:
            conn.close()
        guidance = "".join(f"<li>{html.escape(g)}</li>" for g in detail["guidance"])
        checks = "".join(
            f"<li><b>[{html.escape(i['action'])}]</b> {html.escape(i['title'])} — "
            f"<em>{html.escape(i['status'])}</em>"
            + (f" ({html.escape(i['note'])})" if i["note"] else "") + "</li>"
            for i in detail["checklist"])
        refs = "".join(
            f"<li><b>{html.escape(r['org_name'])}</b> — {html.escape(r['purpose'])}"
            f"<br><em>Bring: {html.escape('; '.join(r['what_to_provide']))}</em></li>"
            for r in detail["referrals"]) or "<li><em>None yet.</em></li>"
        findings = "".join(
            f"<li>[{html.escape(f['claim_type'])}/{html.escape(f['status'])}] "
            f"{html.escape(f['statement'])}"
            + (f" <em>(confidence: {html.escape(f['confidence'])})</em>" if f["confidence"] else "")
            + (f" <em>[evidence: {html.escape(f['evidence_ref'])}]</em>" if f["evidence_ref"] else "")
            + "</li>"
            for f in detail["findings"]) or "<li><em>None yet.</em></li>"
        body = (self._N03_BANNER_HTML + self._n03_nav() +
                f"<div class='card'><h2>Case {html.escape(detail['case_ref'])}</h2>"
                f"<p>Category: <b>{html.escape(detail['category_title'])}</b> · "
                f"Stage: <em>{html.escape(detail['stage'])}</em> · "
                f"Safety: <em>{html.escape(detail['safety_status'])}</em> · "
                "Synthetic: <b>yes</b></p>"
                f"<p>{html.escape(detail['summary'])}</p>"
                f"<h3>Safety guidance</h3><ul>{guidance}</ul>"
                f"<h3>Checklist (preserve → report → refer)</h3><ul>{checks}</ul>"
                f"<h3>Referrals</h3><ul>{refs}</ul>"
                f"<h3>Findings (lead / verified / unknown)</h3><ul>{findings}</ul>"
                "<p><a href='/project_n03/cases'>All cases</a></p></div>")
        return _html(200, f"N03 — Case {detail['case_ref']}", body)

    def n03_preservation_page(self, environ):
        q = self._q08_query(environ)
        category = q.get("category") or None
        if category and category not in sg_service.CATEGORIES:
            return _json(404, _error_envelope("not_found", f"Unknown category {category!r}"))
        items = sg_service.preservation_checklist(category)
        lis = "".join(
            f"<li><b>{html.escape(i['item'])}</b><br>{html.escape(i['detail'])}"
            f"<br><em>Authority: {html.escape(i['authority'])}</em></li>"
            for i in items)
        opts = "".join(
            f"<option value='{c}'{' selected' if c == category else ''}>"
            f"{html.escape(sg_service.CATEGORIES[c]['title'])}</option>"
            for c in sg_service.CATEGORIES)
        body = (self._N03_BANNER_HTML + self._n03_nav() +
                "<div class='card'><h2>N03 — Evidence-Preservation Checklist</h2>"
                "<p>For victims: what to save, and how, <em>before</em> reporting.</p>"
                "<form method='get' action='/project_n03/preservation'>"
                f"<select name='category'><option value=''>General</option>{opts}</select>"
                "<button type='submit'>Show checklist</button></form>"
                f"<ol>{lis}</ol></div>")
        return _html(200, "N03 — Preservation Checklist", body)

    def n03_reporting_page(self):
        rows = "".join(
            f"<div class='card'><h3>{html.escape(g['platform'])}</h3>"
            f"<p><b>Where:</b> {html.escape(g['where'])}</p>"
            f"<p><b>Report:</b> {html.escape(g['what'])}</p>"
            f"<p><em>Authority: {html.escape(g['authority'])}</em></p></div>"
            for g in sg_service.reporting_guide())
        body = (self._N03_BANNER_HTML + self._n03_nav() +
                "<h2>N03 — Platform Reporting Guide</h2>"
                "<p>Where to report on each major platform, plus the two "
                "law-enforcement reporting channels. Flow names are described "
                "as documented in each platform's public help center.</p>" + rows)
        return _html(200, "N03 — Reporting Guide", body)

    def n03_referrals_page(self):
        rows = "".join(
            f"<div class='card'><h3>{html.escape(e['name'])}</h3>"
            f"<p>{html.escape(e['purpose'])}</p>"
            f"<p><b>Bring:</b> {html.escape('; '.join(e['what_to_provide']))}</p>"
            f"<p><em>{html.escape(e['note'])}</em></p></div>"
            for e in sg_service.referral_directory())
        body = (self._N03_BANNER_HTML + self._n03_nav() +
                "<h2>N03 — Referral Directory (template)</h2>"
                "<p>Where to refer each case — and what to bring. This is a "
                "guidance template, not a contact integration: the framework "
                "performs no outreach.</p>" + rows)
        return _html(200, "N03 — Referral Directory", body)

    def n03_demo_submit(self):
        conn = self._conn()
        try:
            demo = sg_service.run_demo(conn)
        finally:
            conn.close()
        body = (self._N03_BANNER_HTML +
                "<div class='card'><h2>N03 guided demo complete (synthetic)</h2>"
                f"<p>Case <a href='/project_n03/cases/{demo['case_id']}'>"
                f"{html.escape(demo['case_ref'])}</a> ran preserve → report → refer "
                f"end to end: {len(demo['steps_completed'])} checklist steps, "
                f"referral to {html.escape(demo['referral_org'])}, "
                f"{demo['findings']} findings, stage <em>{html.escape(demo['stage'])}</em>.</p>"
                "<p><a href='/project_n03/cases'>All cases</a> · "
                "<a href='/project_n03'>Back to N03</a></p></div>")
        return _html(200, "N03 — Demo", body)

    # ---- N03 JSON API (synthetic, bannered) --------------------------------
    def api_sg_playbooks(self):
        return self._sg_json({"playbooks": sg_service.list_playbooks()})

    def api_sg_playbook(self, category: str):
        try:
            pb = sg_service.get_playbook(category)
        except sg_service.SafeguardError as exc:
            return _json(404, _error_envelope("not_found", str(exc)))
        payload = dict(pb)
        payload["category"] = category
        payload["understand"] = sg_service.CATEGORIES[category]["understand"]
        return self._sg_json({"playbook": payload})

    def api_sg_cases(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be a JSON object."))
        conn = self._conn()
        try:
            case = sg_service.intake_case(
                conn,
                case_ref=data.get("case_ref", ""),
                category=data.get("category", ""),
                reporter_role=data.get("reporter_role", ""),
                summary=data.get("summary", ""),
                immediate_danger=bool(data.get("immediate_danger", False)),
                involves_minor=bool(data.get("involves_minor", False)),
            )
        except sg_service.SafeguardError as exc:
            return _json(404, _error_envelope("not_found", str(exc)))
        finally:
            conn.close()
        return self._sg_json({"case": case}, status=201)

    def api_sg_cases_list(self):
        conn = self._conn()
        try:
            cases = sg_service.list_cases(conn)
        finally:
            conn.close()
        return self._sg_json({"cases": cases})

    def api_sg_case_detail(self, case_id: str):
        conn = self._conn()
        try:
            detail = sg_service.get_case_detail(conn, int(case_id))
        except sg_service.SafeguardError as exc:
            return _json(404, _error_envelope("not_found", str(exc)))
        finally:
            conn.close()
        return self._sg_json({"case": detail})

    def api_sg_checklist_item(self, environ, case_id: str, step_id: str):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be a JSON object."))
        status = data.get("status", "done")
        note = data.get("note", "") or data.get("reason", "")
        conn = self._conn()
        try:
            if status == "skipped":
                item = sg_service.skip_checklist_item(conn, int(case_id), step_id, note)
            else:
                item = sg_service.complete_checklist_item(conn, int(case_id), step_id, note)
        except sg_service.SafeguardError as exc:
            return _json(404, _error_envelope("not_found", str(exc)))
        finally:
            conn.close()
        return self._sg_json({"item": item})

    def api_sg_referrals(self, environ, case_id: str):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be a JSON object."))
        conn = self._conn()
        try:
            ref = sg_service.generate_referral(
                conn, int(case_id), data.get("org_key", ""),
                note=data.get("note", ""))
        except sg_service.SafeguardError as exc:
            return _json(404, _error_envelope("not_found", str(exc)))
        finally:
            conn.close()
        return self._sg_json({"referral": ref}, status=201)

    def api_sg_findings(self, environ, case_id: str):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be a JSON object."))
        conn = self._conn()
        try:
            finding = sg_service.add_finding(
                conn, int(case_id),
                statement=data.get("statement", ""),
                claim_type=data.get("claim_type", ""),
                status=data.get("status", ""),
                evidence_ref=data.get("evidence_ref", ""),
                confidence=data.get("confidence"),
            )
        except sg_service.SafeguardError as exc:
            return _json(404, _error_envelope("not_found", str(exc)))
        finally:
            conn.close()
        return self._sg_json({"finding": finding}, status=201)

    def api_sg_preservation(self, environ):
        q = self._q08_query(environ)
        category = q.get("category") or None
        if category and category not in sg_service.CATEGORIES:
            return _json(404, _error_envelope("not_found",
                                              f"Unknown category {category!r}"))
        return self._sg_json({"checklist": sg_service.preservation_checklist(category),
                              "category": category})

    def api_sg_reporting_guide(self):
        return self._sg_json({"guide": sg_service.reporting_guide()})

    def api_sg_referral_directory(self):
        return self._sg_json({"directory": sg_service.referral_directory()})

    def api_sg_demo(self):
        conn = self._conn()
        try:
            demo = sg_service.run_demo(conn)
        finally:
            conn.close()
        return self._sg_json({"demo": demo}, status=201)

    # ---- N02 JSON API (synthetic workbook, bannered) ----------------------
    def _risk_or_404(self, conn):
        if not risk_service.seeded(conn):
            return None
        return True

    def api_risk_assets(self):
        conn = self._conn()
        try:
            if self._risk_or_404(conn) is None:
                return _json(404, _error_envelope("not_found", "N02 workbook not seeded"))
            return self._risk_json({"assets": risk_service.list_assets(conn)})
        finally:
            conn.close()

    def api_risk_threats(self):
        conn = self._conn()
        try:
            if self._risk_or_404(conn) is None:
                return _json(404, _error_envelope("not_found", "N02 workbook not seeded"))
            return self._risk_json({"threats": risk_service.list_threats(conn)})
        finally:
            conn.close()

    def api_risk_scales(self):
        return self._risk_json({"scales": risk_service.scales_doc()})

    def api_risk_register(self):
        conn = self._conn()
        try:
            if self._risk_or_404(conn) is None:
                return _json(404, _error_envelope("not_found", "N02 workbook not seeded"))
            register = risk_service.list_risks(conn)
            return self._risk_json({
                "register": register,
                "totals": risk_service.register_totals(register),
                "audit_violations": risk_service.register_audit(register),
            })
        finally:
            conn.close()

    def api_risk_controls(self):
        return self._risk_json({
            "registry": risk_service.CONTROL_REGISTRY,
            "count": len(risk_service.CONTROL_REGISTRY),
        })

    def api_risk_remediations(self):
        conn = self._conn()
        try:
            if self._risk_or_404(conn) is None:
                return _json(404, _error_envelope("not_found", "N02 workbook not seeded"))
            return self._risk_json({
                "remediations": risk_service.list_remediations(conn),
                "prioritization_rule": risk_service.PRIORITIZATION_RULE,
            })
        finally:
            conn.close()

    def api_risk_residual(self):
        conn = self._conn()
        try:
            if self._risk_or_404(conn) is None:
                return _json(404, _error_envelope("not_found", "N02 workbook not seeded"))
            return self._risk_json(risk_service.get_residual_report(conn))
        finally:
            conn.close()

    def api_risk_seed(self):
        conn = self._conn()
        try:
            summary = risk_service.seed_demo(conn)
        finally:
            conn.close()
        log_system_event("n02.seeded", summary)
        return self._risk_json({"seeded": summary})

    # ---- S05 JSON API (educational demo surface, bannered) -----------------
    def api_crypto_pitfalls(self):
        return self._crypto_json({"pitfalls": crypto_service.PITFALLS})

    def api_crypto_hash(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be JSON."))
        msg = data.get("message_hex")
        if not isinstance(msg, str):
            return _json(422, _error_envelope("validation_failed",
                                             "'message_hex' (hex string) required."))
        try:
            digest = crypto_service.sha256_hex(bytes.fromhex(msg))
        except ValueError:
            return _json(422, _error_envelope("validation_failed",
                                             "'message_hex' is not valid hex."))
        return self._crypto_json({"algorithm": "SHA-256", "digest_hex": digest})

    def api_crypto_hmac(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be JSON."))
        try:
            key = crypto_service.validate_key(
                bytes.fromhex(data.get("key_hex", "")), purpose="api-hmac")
            message = bytes.fromhex(data.get("message_hex", ""))
        except (ValueError, crypto_service.WeakKeyError) as exc:
            return _json(422, _error_envelope("validation_failed", str(exc)))
        return self._crypto_json({"algorithm": "HMAC-SHA256",
                                  "tag_hex": crypto_service.hmac_sha256_hex(key, message)})

    def api_crypto_password(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be JSON."))
        password = data.get("password")
        if not isinstance(password, str) or not password:
            return _json(422, _error_envelope("validation_failed",
                                              "'password' (non-empty string) required."))
        try:
            iterations = int(data.get("iterations",
                                      crypto_service.DEFAULT_PBKDF2_ITERATIONS))
        except (ValueError, TypeError):
            return _json(422, _error_envelope("validation_failed",
                                              "'iterations' must be an integer."))
        if iterations < 10_000:
            return _json(422, _error_envelope(
                "validation_failed",
                "Refusing a work factor below 10,000 (NIST SP 800-63B floor)."))
        try:
            stored = crypto_service.hash_password(password, iterations=iterations)
        except crypto_service.CryptoError as exc:
            return _json(422, _error_envelope("validation_failed", str(exc)))
        return self._crypto_json({"stored": stored,
                                  "verify": crypto_service.verify_password(password, stored)})

    def _api_envelope_key(self, data):
        """Demo keys for encrypt/decrypt: caller-supplied or freshly generated."""
        key_hex = data.get("key_hex")
        if key_hex:
            try:
                return bytes.fromhex(key_hex), None
            except ValueError:
                raise ValidationError("'key_hex' is not valid hex.")
        key = crypto_service.generate_key()
        return key, key.hex()

    def api_crypto_encrypt(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be JSON."))
        try:
            key, generated_hex = self._api_envelope_key(data)
            plaintext = bytes.fromhex(data.get("plaintext_hex", ""))
            aad = bytes.fromhex(data.get("aad_hex", ""))
        except (ValueError, ValidationError) as exc:
            return _json(422, _error_envelope("validation_failed", str(exc)))
        try:
            env = crypto_service.encrypt(key, plaintext, associated_data=aad)
        except crypto_service.CryptoError as exc:
            return _json(422, _error_envelope("validation_failed", str(exc)))
        payload = {"envelope": env}
        if generated_hex:
            payload["demo_key_hex"] = generated_hex
            payload["demo_key_note"] = "synthetic test-only key generated for this call"
        return self._crypto_json(payload)

    def api_crypto_decrypt(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be JSON."))
        try:
            key = crypto_service.validate_key(
                bytes.fromhex(data.get("key_hex", "")), purpose="api-decrypt")
            envelope = data.get("envelope")
            if not isinstance(envelope, dict):
                raise ValidationError("'envelope' object required.")
            plaintext = crypto_service.decrypt(key, envelope)
        except (ValueError, ValidationError) as exc:
            return _json(422, _error_envelope("validation_failed", str(exc)))
        except crypto_service.CryptoError as exc:
            return _json(422, _error_envelope("auth_failed", str(exc)))
        return self._crypto_json({"plaintext_hex": plaintext.hex()})

    def api_crypto_keys(self):
        conn = self._conn()
        try:
            inventory = crypto_service.key_inventory(conn)
        finally:
            conn.close()
        return self._crypto_json({"keys": inventory})

    def api_crypto_rotate(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError:
            data = {}
        actor = data.get("actor") or "api"
        conn = self._conn()
        try:
            old_v, new_v = crypto_service.rotate_key(conn, actor)
        except crypto_service.CryptoError as exc:
            return _json(422, _error_envelope("key_error", str(exc)))
        finally:
            conn.close()
        return self._crypto_json({"rotated_from": old_v, "rotated_to": new_v})

    def api_crypto_destroy(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be JSON."))
        try:
            version = int(data.get("key_version"))
        except (ValueError, TypeError):
            return _json(422, _error_envelope("validation_failed",
                                              "'key_version' (integer) required."))
        conn = self._conn()
        try:
            crypto_service.destroy_key(conn, version, data.get("actor") or "api")
        except crypto_service.CryptoError as exc:
            return _json(422, _error_envelope("key_error", str(exc)))
        finally:
            conn.close()
        return self._crypto_json({"destroyed": version})

    def api_crypto_cert_design(self):
        return self._crypto_json(
            {"certificate_validation": crypto_service.describe_cert_validation_design()})

    # ---- S03 pages ---------------------------------------------------------
    _S03_BANNER_HTML = (
        "<div class='card' style='border-left:4px solid #b00'>"
        "<strong>Synthetic data only — method demonstration, not casework.</strong> "
        "The &ldquo;disk image&rdquo; is a generated directory tree plus a manifest, "
        "never a real device. No real people, systems, or PII are involved. "
        "Nothing here images, accesses, or examines a real person's device, "
        "and no encryption or access control is bypassed.</div>")

    def _for_json(self, data: dict, status: int = 200):
        return _json(status, {
            "synthetic": True,
            "method_demo_only": True,
            "warning": ("SYNTHETIC DATA ONLY. Demonstrates forensic method on "
                        "generated fixtures — not casework experience, not a "
                        "real device, no production use."),
            **data,
        })

    def _for_conflict(self, exc: Exception):
        return _json(409, _error_envelope("conflict", str(exc)))

    def s03_page(self):
        body = (self._S03_BANNER_HTML +
                "<div class='card'><h2>S03 — Digital Forensic Applications</h2>"
                "<p>A repeatable, defensible evidence workflow practiced on "
                "<em>synthetic</em> fixtures: intake with a synthetic authorization "
                "record → hashed acquisition → artifact examination → timeline "
                "analysis with hypothesis testing → a report that separates "
                "facts from inference.</p><ul>"
                "<li><b>REAL (implemented + tested):</b> case intake, SHA-256 "
                "acquisition with start/end hash capture, file/MAC-time listing, "
                "log parsing, deleted-file carving, merged timelines scored "
                "against ground truth, hash-chained custody at every handoff, "
                "reports that reject inferences without confidence levels.</li>"
                "<li><b>SIMULATED:</b> the &ldquo;disk image&rdquo; — a generated "
                "directory tree + manifest, never a real device.</li>"
                "<li><b>SYNTHETIC:</b> every case, artifact, and ground-truth "
                "record is invented fixture data.</li>"
                "<li><b>NOT claimed:</b> no casework experience, no real devices, "
                "no production deployment, no real users.</li>"
                "</ul><p><a href='/project_s03/cases'>Cases →</a></p>"
                "<form method='post' action='/project_s03/demo'>"
                "<button type='submit'>Run guided demo (synthetic case, end to end)</button>"
                "</form></div>")
        return _html(200, "S03 — Digital Forensic Applications", body)

    def s03_cases_page(self):
        conn = self._conn()
        try:
            cases = for_service.list_cases(conn)
        finally:
            conn.close()
        rows = "".join(
            f"<li><a href='/project_s03/cases/{c['id']}'>{html.escape(c['case_ref'])}"
            f"</a> — {html.escape(c['title'])} <em>({html.escape(c['status'])})</em></li>"
            for c in cases) or "<li><em>No cases yet — run the demo below.</em></li>"
        body = (self._S03_BANNER_HTML +
                "<div class='card'><h2>S03 — Cases</h2><ul>" + rows + "</ul>"
                "<form method='post' action='/project_s03/demo'>"
                "<button type='submit'>Run guided demo (synthetic case, end to end)</button>"
                "</form><p>Programmatic intake: "
                "<code>POST /api/forensics/cases</code> with "
                "<code>title</code>, <code>description</code>, "
                "<code>authorizer_name</code>, <code>authorization_ref</code>, "
                "<code>handling_plan</code> (≥3 steps).</p>"
                "<p><a href='/project_s03'>Back to S03</a></p></div>")
        return _html(200, "S03 — Cases", body)

    def s03_case_page(self, case_id: str):
        conn = self._conn()
        try:
            case = for_service.get_case(conn, int(case_id))
            acqs = [dict(r) for r in conn.execute(
                "SELECT id, method, source_label, started_at, finished_at, "
                "start_hash, manifest_hash, file_count, total_bytes, status "
                "FROM forensics_acquisitions WHERE case_id = ? ORDER BY id",
                (case["id"],))]
            arts = [dict(r) for r in conn.execute(
                "SELECT id, kind, ref_path, sha256 FROM forensics_artifacts "
                "WHERE acquisition_id IN (SELECT id FROM forensics_acquisitions "
                "WHERE case_id = ?) ORDER BY id", (case["id"],))]
            timeline = for_service.get_timeline(conn, case["id"])
            hyps = for_service.list_hypotheses(conn, case["id"])
            chain = for_service.verify_chain(conn, case["id"])
            rep = conn.execute(
                "SELECT id, created_at FROM forensics_reports WHERE case_id = ? "
                "ORDER BY id DESC LIMIT 1", (case["id"],)).fetchone()
        except for_service.ForensicsError as exc:
            conn.close()
            return _json(404, _error_envelope("not_found", str(exc)))
        finally:
            conn.close()
        plan = "".join(f"<li>{html.escape(s)}</li>" for s in case["handling_plan"])
        acq_rows = "".join(
            f"<li>Acquisition #{a['id']}: {a['file_count']} files, "
            f"{a['total_bytes']} bytes, manifest "
            f"<code>{html.escape(a['manifest_hash'][:16])}…</code> "
            f"(<a href='/api/forensics/cases/{case['id']}/acquisitions/{a['id']}/verify'>"
            "verify integrity</a>)</li>" for a in acqs) or "<li><em>None yet.</em></li>"
        art_rows = "".join(
            f"<li>#{a['id']} [{html.escape(a['kind'])}] {html.escape(a['ref_path'])}</li>"
            for a in arts) or "<li><em>None yet.</em></li>"
        tl_rows = "".join(
            f"<li><code>{html.escape(e['ts'])}</code> "
            f"[{html.escape(e['event_type'])}] {html.escape(e['summary'])}</li>"
            for e in timeline) or "<li><em>None yet.</em></li>"
        hyp_rows = "".join(
            f"<li>H{h['id']} [{html.escape(h['status'])}]: {html.escape(h['statement'])}"
            f"<br>Supporting: {html.escape(', '.join(h['supporting']))}"
            f"<br>Contradicting: {html.escape(', '.join(h['contradicting']))}</li>"
            for h in hyps) or "<li><em>None yet.</em></li>"
        chain_line = ("<b>VERIFIED</b>" if chain["ok"]
                      else f"<b>BROKEN</b> at step {html.escape(str(chain['step']))}")
        body = (self._S03_BANNER_HTML +
                f"<div class='card'><h2>{html.escape(case['case_ref'])} — "
                f"{html.escape(case['title'])}</h2>"
                f"<p><em>Stage: {html.escape(case['status'])}</em></p>"
                f"<p>{html.escape(case['description'])}</p>"
                "<h3>Synthetic authorization record</h3>"
                f"<p>Authorizer: {html.escape(case['authorizer_name'])} "
                f"({html.escape(case['authorization_ref'])})</p>"
                "<h3>Handling plan</h3><ol>" + plan + "</ol>"
                "<h3>Acquisitions</h3><ul>" + acq_rows + "</ul>"
                "<h3>Artifacts</h3><ul>" + art_rows + "</ul>"
                "<h3>Timeline</h3><ul>" + tl_rows + "</ul>"
                "<h3>Hypotheses</h3><ul>" + hyp_rows + "</ul>"
                f"<h3>Chain of custody</h3><p>{chain_line} "
                f"({chain.get('entries', 0)} chained handoffs)</p>"
                + (f"<h3>Report</h3><p>Report #{rep['id']} drafted "
                   f"({html.escape(rep['created_at'])}). "
                   f"<a href='/api/forensics/cases/{case['id']}/report'>Latest report JSON</a></p>"
                   if rep else "<h3>Report</h3><p><em>None yet.</em></p>")
                + "<p><a href='/project_s03/cases'>Back to cases</a></p></div>")
        return _html(200, f"S03 — {html.escape(case['case_ref'])}", body)

    def _run_s03_demo_workflow(self, conn):
        """Generate a synthetic case and run intake→acquire→examine→timeline."""
        fixture_name = f"demo-{uuid.uuid4().hex[:8]}"
        case_dir = os.path.join(SYNTHETIC_CASES_DIR, fixture_name)
        fx = for_service.generate_synthetic_case(case_dir)
        case = for_service.open_case(
            conn,
            title="Suspicious installer download (synthetic demo)",
            description=("Demo case: a synthetic workstation user downloads an "
                         "installer, runs it, and deletes a notes file. All "
                         "data is generated fixture material."),
            authorizer_name="Synthetic Authorizer (demo)",
            authorization_ref="AUTH-DEMO-0001",
            handling_plan=[
                "Intake: record the request and the synthetic authorization.",
                "Acquire the synthetic image read-only with hash capture.",
                "Examine: extract file metadata, parse logs, carve deleted files.",
                "Analyze: build a merged timeline; test hypotheses.",
                "Report: separate facts from inference with confidence levels.",
            ],
        )
        acq = for_service.run_acquisition(
            conn, case["id"], fx["tree"],
            source_label=f"synthetic-fixture:{fixture_name}")
        with open(fx["meta_path"], encoding="utf-8") as fh:
            meta = json.load(fh)
        files = for_service.extract_file_listing(conn, acq["id"], meta)
        with open(os.path.join(fx["tree"], "var", "log", "app.log"),
                  encoding="utf-8") as fh:
            log_text = fh.read()
        logs = for_service.extract_log_events(conn, acq["id"], log_text)
        with open(fx["blob_path"], "rb") as fh:
            blob = fh.read()
        with open(fx["freelist_path"], encoding="utf-8") as fh:
            free_list = json.load(fh)
        carved = for_service.carve_deleted(conn, acq["id"], blob, free_list)
        events = for_service.events_from_fixture(case_dir)
        timeline = for_service.record_timeline(conn, case["id"], events)
        with open(fx["ground_truth_path"], encoding="utf-8") as fh:
            ground_truth = json.load(fh)["events"]
        score = for_service.score_timeline(timeline, ground_truth)
        chain = for_service.verify_chain(conn, case["id"])
        return {
            "case_id": case["id"],
            "case_ref": case["case_ref"],
            "acquisition_id": acq["id"],
            "file_count": acq["file_count"],
            "manifest_hash": acq["manifest_hash"],
            "artifacts": {"files": len(files), "log_events": len(logs),
                          "carved": len(carved)},
            "timeline_events": len(timeline),
            "timeline_score": score["score"],
            "timeline_matched": f"{score['matched']}/{score['total']}",
            "chain_ok": chain["ok"],
            "stage": for_service.get_case(conn, case["id"])["status"],
        }

    def s03_demo_submit(self, environ):
        conn = self._conn()
        try:
            demo = self._run_s03_demo_workflow(conn)
        finally:
            conn.close()
        items = "".join(
            f"<li><b>{html.escape(k)}:</b> {html.escape(str(v))}</li>"
            for k, v in demo.items() if k not in ("case_id",))
        body = (self._S03_BANNER_HTML +
                "<div class='card'><h2>S03 guided demo (synthetic data)</h2>"
                "<p>Full workflow ran on a freshly generated synthetic fixture:</p><ul>"
                + items + "</ul>"
                f"<p><a href='/project_s03/cases/{demo['case_id']}'>Open the demo case →</a> "
                "<a href='/project_s03/cases'>All cases →</a></p></div>")
        return _html(200, "S03 — Demo", body)

    # ---- S03 API -----------------------------------------------------------
    def api_for_cases(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be a JSON object."))
        conn = self._conn()
        try:
            case = for_service.open_case(
                conn,
                title=data.get("title", ""),
                description=data.get("description", ""),
                authorizer_name=data.get("authorizer_name", ""),
                authorization_ref=data.get("authorization_ref", ""),
                handling_plan=data.get("handling_plan", []),
            )
        finally:
            conn.close()
        return self._for_json({"case": case}, status=201)

    def api_for_cases_list(self):
        conn = self._conn()
        try:
            cases = for_service.list_cases(conn)
        finally:
            conn.close()
        return self._for_json({"cases": cases})

    def api_for_case_detail(self, case_id: str):
        conn = self._conn()
        try:
            case = for_service.get_case(conn, int(case_id))
            acqs = [dict(r) for r in conn.execute(
                "SELECT id, method, source_label, started_at, finished_at, "
                "start_hash, manifest_hash, file_count, total_bytes, status "
                "FROM forensics_acquisitions WHERE case_id = ? ORDER BY id",
                (case["id"],))]
        except for_service.ForensicsError as exc:
            conn.close()
            return _json(404, _error_envelope("not_found", str(exc)))
        finally:
            conn.close()
        return self._for_json({"case": case, "acquisitions": acqs})

    def api_for_demo(self, environ):
        conn = self._conn()
        try:
            demo = self._run_s03_demo_workflow(conn)
        finally:
            conn.close()
        return self._for_json({"demo": demo}, status=201)

    def api_for_acquire(self, environ, case_id: str):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be a JSON object."))
        fixture = data.get("fixture", "")
        if not (isinstance(fixture, str) and fixture and "/" not in fixture
                and not fixture.startswith(".")):
            return _json(422, _error_envelope(
                "validation_failed",
                "'fixture' must be a plain directory name under the synthetic-cases dir."))
        source_dir = os.path.join(SYNTHETIC_CASES_DIR, fixture, "tree")
        if not os.path.isdir(source_dir):
            return _json(404, _error_envelope(
                "not_found", f"No synthetic fixture named {fixture!r}."))
        conn = self._conn()
        try:
            acq = for_service.run_acquisition(conn, int(case_id), source_dir,
                                             source_label=f"synthetic-fixture:{fixture}")
        except for_service.ForensicsError as exc:
            conn.close()
            return self._for_conflict(exc)
        finally:
            conn.close()
        return self._for_json({"acquisition": acq}, status=201)

    def api_for_verify(self, case_id: str, acq_id: str):
        conn = self._conn()
        try:
            case = for_service.get_case(conn, int(case_id))
            acq = for_service.get_acquisition(conn, int(acq_id))
            if acq["case_id"] != case["id"]:
                raise for_service.ForensicsError("Acquisition does not belong to this case.")
            label = acq["source_label"]
            source_dir = None
            if label.startswith("synthetic-fixture:"):
                cand = os.path.join(SYNTHETIC_CASES_DIR,
                                    label.split(":", 1)[1], "tree")
                if os.path.isdir(cand):
                    source_dir = cand
            if source_dir is None:
                raise for_service.ForensicsError(
                    "Fixture tree for this acquisition is no longer available.")
            result = for_service.verify_acquisition(conn, acq["id"], source_dir)
        except for_service.ForensicsError as exc:
            conn.close()
            return _json(404, _error_envelope("not_found", str(exc)))
        finally:
            conn.close()
        return self._for_json({"integrity": result})

    def api_for_artifacts(self, case_id: str):
        conn = self._conn()
        try:
            case = for_service.get_case(conn, int(case_id))
            acq = conn.execute(
                "SELECT id FROM forensics_acquisitions WHERE case_id = ? "
                "ORDER BY id DESC LIMIT 1", (case["id"],)).fetchone()
            artifacts = (for_service.list_artifacts(conn, acq["id"])
                         if acq else [])
        except for_service.ForensicsError as exc:
            conn.close()
            return _json(404, _error_envelope("not_found", str(exc)))
        finally:
            conn.close()
        return self._for_json({"artifacts": artifacts})

    def api_for_timeline(self, case_id: str):
        conn = self._conn()
        try:
            case = for_service.get_case(conn, int(case_id))
            timeline = for_service.get_timeline(conn, case["id"])
        except for_service.ForensicsError as exc:
            conn.close()
            return _json(404, _error_envelope("not_found", str(exc)))
        finally:
            conn.close()
        return self._for_json({"timeline": timeline})

    def api_for_hypotheses(self, environ, case_id: str):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be a JSON object."))
        conn = self._conn()
        try:
            hyp = for_service.add_hypothesis(
                conn, int(case_id),
                statement=data.get("statement", ""),
                supporting=data.get("supporting", []),
                contradicting=data.get("contradicting", []),
                status=data.get("status", "open"),
            )
        except for_service.ForensicsError as exc:
            conn.close()
            return _json(404, _error_envelope("not_found", str(exc)))
        finally:
            conn.close()
        return self._for_json({"hypothesis": hyp}, status=201)

    def api_for_report(self, environ, case_id: str):
        if environ.get("REQUEST_METHOD") == "GET":
            conn = self._conn()
            try:
                case = for_service.get_case(conn, int(case_id))
                row = conn.execute(
                    "SELECT * FROM forensics_reports WHERE case_id = ? "
                    "ORDER BY id DESC LIMIT 1", (case["id"],)).fetchone()
                report = for_service.get_report(conn, row["id"]) if row else None
            except for_service.ForensicsError as exc:
                conn.close()
                return _json(404, _error_envelope("not_found", str(exc)))
            finally:
                conn.close()
            return self._for_json({"report": report})
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be a JSON object."))
        conn = self._conn()
        try:
            result = for_service.draft_report(conn, int(case_id),
                                              data.get("findings", []))
        except for_service.ForensicsError as exc:
            conn.close()
            return self._for_conflict(exc)
        finally:
            conn.close()
        return self._for_json({"report": result}, status=201)

    def api_for_chain(self, case_id: str):
        conn = self._conn()
        try:
            case = for_service.get_case(conn, int(case_id))
            chain = for_service.get_chain(conn, case["id"])
            verdict = for_service.verify_chain(conn, case["id"])
        except for_service.ForensicsError as exc:
            conn.close()
            return _json(404, _error_envelope("not_found", str(exc)))
        finally:
            conn.close()
        return self._for_json({"chain": chain, "verification": verdict})

    # ---- S04: forensic evidence management (synthetic case only) ----------
    _S04_BANNER_HTML = (
        "<div class='card' style='border-left:4px solid #b00'>"
        "<strong>Synthetic case only — system demonstration, not legal "
        "authority.</strong> Every case, evidence tag, hash, actor, and "
        "location is invented fixture data. This demonstrates a custody "
        "<em>system</em> (intake → tagging → storage → access → transfer → "
        "disposition, hash-chained and tamper-evident). It is not legal "
        "advice; real admissibility depends on jurisdiction and counsel. "
        "Access controls assume a trusted-admin model.</div>")

    def _cust_json(self, data: dict, status: int = 200):
        return _json(status, {
            "synthetic": True,
            "method_demo_only": True,
            "warning": ("SYNTHETIC CASE ONLY. Demonstrates a chain-of-custody "
                        "system on invented fixtures — not legal authority, "
                        "not legal advice, no production use, no real evidence."),
            **data,
        })

    def _cust_conflict(self, exc: Exception):
        return _json(409, _error_envelope("conflict", str(exc)))

    def s04_page(self):
        conn = self._conn()
        try:
            cases = custody_service.list_cases(conn)
            items = custody_service.list_items(conn)
            incidents = custody_service.list_incidents(conn)
            verdict = custody_service.verify_custody_chain(conn)
        finally:
            conn.close()
        case_rows = "".join(
            f"<li><a href='/project_s04/register'>{html.escape(c['case_ref'])}</a> — "
            f"{html.escape(c['title'])}</li>" for c in cases
        ) or "<li><em>No cases yet — run the seeded demo below.</em></li>"
        inc_line = (f"{len(incidents)} incident(s)" if incidents
                    else "no incidents")
        chain_line = ("<b>VERIFIED</b>" if verdict["ok"]
                      else f"<b>BROKEN</b> ({html.escape(str(verdict.get('reason')))})")
        body = (self._S04_BANNER_HTML +
                "<div class='card'><h2>S04 — Forensic Evidence Management</h2>"
                "<p>End-to-end chain of custody on a synthetic case: intake → "
                "tagging → storage log → access log → transfer log → "
                "disposition. Every entry actor-stamped, timestamped, and "
                "hash-chained. A SHA-256 hash mismatch at any transfer "
                "rejects the transfer and opens a quarantine incident.</p>"
                f"<p>Register: <b>{len(items)} items</b> · Chain: {chain_line} "
                f"({verdict.get('entries', 0)} entries) · {inc_line}</p>"
                "<ul>" + case_rows + "</ul>"
                "<form method='post' action='/project_s04/seed'>"
                "<button type='submit'>Seed synthetic case "
                "(CASE-2026-SYN-047, end to end)</button></form>"
                "<p><a href='/project_s04/register'>Evidence register →</a> · "
                "<a href='/project_s04/incidents'>Incidents →</a> · "
                "<a href='/api/custody/verify'>Chain verification (JSON) →</a></p>"
                "</div>")
        return _html(200, "S04 — Evidence Management", body)

    def s04_register_page(self):
        conn = self._conn()
        try:
            items = custody_service.list_items(conn)
        finally:
            conn.close()
        rows = "".join(
            f"<tr><td><a href='/project_s04/items/{i['id']}'>"
            f"{html.escape(i['tag'])}</a></td>"
            f"<td>{html.escape(i['description'][:60])}</td>"
            f"<td>{html.escape(i['storage_location'])}</td>"
            f"<td><code>{html.escape(i['acquisition_sha256'][:16])}…</code></td>"
            f"<td>{html.escape(i['status'])}</td></tr>"
            for i in items) or "<tr><td colspan='5'><em>Empty — seed the demo case.</em></td></tr>"
        body = (self._S04_BANNER_HTML +
                "<div class='card'><h2>Evidence Register</h2>"
                "<table><tr><th>Tag</th><th>Description</th><th>Location</th>"
                "<th>Acquisition SHA-256</th><th>Status</th></tr>" + rows +
                "</table><p><a href='/project_s04'>Back to S04</a></p></div>")
        return _html(200, "S04 — Evidence Register", body)

    def s04_item_page(self, item_id: str):
        conn = self._conn()
        try:
            trace = custody_service.full_trace(conn, int(item_id))
        except custody_service.CustodyError as exc:
            conn.close()
            return _json(404, _error_envelope("not_found", str(exc)))
        finally:
            conn.close()
        item, entries = trace["item"], trace["custody_entries"]
        verdict = trace["chain_verdict"]
        chain_line = ("<b>VERIFIED</b>" if verdict["ok"]
                      else f"<b>BROKEN</b>: {html.escape(str(verdict['problems']))}")
        ev_rows = "".join(
            f"<li><code>{html.escape(e['created_at'])}</code> "
            f"[seq {e['seq']}] <b>{html.escape(e['event_type'])}</b> — "
            f"{html.escape(e['actor'])} "
            f"(<code>{html.escape(e['entry_hash'][:12])}…</code>)</li>"
            for e in entries) or "<li><em>None.</em></li>"
        tr_rows = "".join(
            f"<li>#{t['id']}: {html.escape(t['sender'])} → "
            f"{html.escape(t['receiver'])} "
            f"(<b>{html.escape(t['status'])}</b>)</li>"
            for t in trace["transfers"]) or "<li><em>None.</em></li>"
        ac_rows = "".join(
            f"<li>{html.escape(a['actor'])} [{html.escape(a['action'])}] — "
            f"{html.escape(a['purpose'][:80])}</li>"
            for a in trace["access"]) or "<li><em>None.</em></li>"
        dp_rows = "".join(
            f"<li>{html.escape(d['disposition']).upper()} by "
            f"{html.escape(d['authorized_by'])} "
            f"({html.escape(d['authorization_ref'])})</li>"
            for d in trace["dispositions"]) or "<li><em>None.</em></li>"
        inc_rows = "".join(
            f"<li>#{i['id']} [{html.escape(i['kind'])}] "
            f"<b>{html.escape(i['status'])}</b> — "
            f"{html.escape(i['detail'][:90])}</li>"
            for i in trace["incidents"]) or "<li><em>None.</em></li>"
        forms = ("<p>Printable forms: "
                 f"<a href='/project_s04/forms/intake?item_id={item['id']}'>Intake</a> · "
                 f"<a href='/project_s04/forms/custody_log?item_id={item['id']}'>Chain-of-custody log</a> · "
                 f"<a href='/project_s04/forms/access_log?item_id={item['id']}'>Access log</a> · "
                 f"<a href='/project_s04/forms/disposition_record?item_id={item['id']}'>Disposition</a></p>")
        body = (self._S04_BANNER_HTML +
                f"<div class='card'><h2>{html.escape(item['tag'])} — "
                f"{html.escape(item['description'][:60])}</h2>"
                f"<p>Status: <b>{html.escape(item['status'])}</b> · "
                f"Location: {html.escape(item['storage_location'])} · "
                f"Acquisition: <code>{html.escape(item['acquisition_sha256'])}</code></p>"
                f"<p>Chain for this item: {chain_line} ({verdict['entries']} entries)</p>"
                f"{forms}"
                "<h3>Custody entries (hash-chained)</h3><ul>" + ev_rows + "</ul>"
                "<h3>Transfers</h3><ul>" + tr_rows + "</ul>"
                "<h3>Access log</h3><ul>" + ac_rows + "</ul>"
                "<h3>Disposition</h3><ul>" + dp_rows + "</ul>"
                "<h3>Incidents</h3><ul>" + inc_rows + "</ul>"
                "<p><a href='/project_s04/register'>Back to register</a></p></div>")
        return _html(200, f"S04 — {item['tag']}", body)

    def s04_form_page(self, form: str, environ: dict):
        query = dict(parse_qsl(environ.get("QUERY_STRING", "") or ""))
        conn = self._conn()
        try:
            if form not in custody_service.FORM_NAMES:
                return _html(404, "Unknown form",
                             self._S04_BANNER_HTML +
                             "<div class='card'><p>Unknown form. Valid forms: "
                             + ", ".join(custody_service.FORM_NAMES) + ".</p></div>")
            if form == "transfer_receipt":
                doc = custody_service.render_form(
                    conn, form, transfer_id=int(query.get("transfer_id", "0") or "0"))
            else:
                doc = custody_service.render_form(
                    conn, form, item_id=int(query.get("item_id", "0") or "0"))
        except (custody_service.CustodyError, ValueError) as exc:
            conn.close()
            return _html(404, "Not found",
                         self._S04_BANNER_HTML +
                         f"<div class='card'><p>{html.escape(str(exc))}</p></div>")
        finally:
            conn.close()
        return 200, [("Content-Type", "text/html; charset=utf-8")], doc.encode("utf-8")

    def s04_incidents_page(self):
        conn = self._conn()
        try:
            incidents = custody_service.list_incidents(conn)
        finally:
            conn.close()
        rows = "".join(
            f"<tr><td>#{i['id']}</td><td>{html.escape(i['kind'])}</td>"
            f"<td>{html.escape(str(i['item_id']) if i['item_id'] else '—')}</td>"
            f"<td>{html.escape(i['detail'][:80])}</td>"
            f"<td><b>{html.escape(i['status'])}</b></td></tr>"
            for i in incidents) or "<tr><td colspan='5'><em>No incidents.</em></td></tr>"
        body = (self._S04_BANNER_HTML +
                "<div class='card'><h2>Custody Incidents</h2>"
                "<p>A hash mismatch at any transfer rejects the transfer and "
                "quarantines the item until the incident is resolved.</p>"
                "<table><tr><th>#</th><th>Kind</th><th>Item</th>"
                "<th>Detail</th><th>Status</th></tr>" + rows +
                "</table><p><a href='/project_s04'>Back to S04</a></p></div>")
        return _html(200, "S04 — Incidents", body)

    def s04_seed_submit(self, environ):
        conn = self._conn()
        try:
            try:
                result = custody_service.seed_synthetic_case(conn)
            except custody_service.CustodyError as exc:
                return _html(409, "Already seeded",
                             self._S04_BANNER_HTML +
                             f"<div class='card'><p>{html.escape(str(exc))}</p>"
                             "<p><a href='/project_s04/register'>Open the register →</a></p></div>")
        finally:
            conn.close()
        body = ("<div class='card'><h2>Synthetic case seeded</h2>"
                f"<p>Case <b>{html.escape(result['case_ref'])}</b>: "
                f"{len(result['item_tags'])} items, "
                f"{len(result['completed_transfers'])} completed transfers, "
                f"1 hash-mismatch drill (incident "
                f"#{result['drill_incident']}, resolved).</p>"
                "<p><a href='/project_s04/register'>Open the register →</a></p></div>")
        return _html(200, "S04 — Seeded", self._S04_BANNER_HTML + body)

    # -- S04 JSON API --------------------------------------------------------
    def api_custody_intake(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be a JSON object."))
        conn = self._conn()
        try:
            item = custody_service.intake_item(
                conn,
                case_id=int(data.get("case_id", 0) or 0),
                tag=data.get("tag", ""),
                description=data.get("description", ""),
                storage_location=data.get("storage_location", ""),
                acquisition_sha256=data.get("acquisition_sha256", ""),
                acquired_by=data.get("acquired_by", ""),
                acquisition_ref=data.get("acquisition_ref", ""),
                media_type=data.get("media_type", "placeholder"),
                notes=data.get("notes", ""),
            )
        except custody_service.CustodyError as exc:
            conn.close()
            return self._cust_conflict(exc)
        finally:
            conn.close()
        return self._cust_json({"item": item}, status=201)

    def api_custody_items_list(self):
        conn = self._conn()
        try:
            items = custody_service.list_items(conn)
        finally:
            conn.close()
        return self._cust_json({"items": items})

    def api_custody_item_detail(self, item_id: str):
        conn = self._conn()
        try:
            trace = custody_service.full_trace(conn, int(item_id))
        except custody_service.CustodyError as exc:
            conn.close()
            return _json(404, _error_envelope("not_found", str(exc)))
        finally:
            conn.close()
        return self._cust_json(trace)

    def api_custody_transfer_initiate(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be a JSON object."))
        conn = self._conn()
        try:
            tr = custody_service.initiate_transfer(
                conn,
                item_id=int(data.get("item_id", 0) or 0),
                sender=data.get("sender", ""),
                receiver=data.get("receiver", ""),
                purpose=data.get("purpose", ""),
                destination_location=data.get("destination_location", ""),
            )
        except custody_service.CustodyError as exc:
            conn.close()
            return self._cust_conflict(exc)
        finally:
            conn.close()
        return self._cust_json({"transfer": tr}, status=201)

    def api_custody_hash_out(self, environ, transfer_id: str):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be a JSON object."))
        conn = self._conn()
        try:
            tr = custody_service.record_hash_out(
                conn, int(transfer_id), hash_out=data.get("hash_out", ""))
        except custody_service.CustodyError as exc:
            conn.close()
            return self._cust_conflict(exc)
        finally:
            conn.close()
        return self._cust_json({"transfer": tr})

    def api_custody_hash_in(self, environ, transfer_id: str):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be a JSON object."))
        conn = self._conn()
        try:
            tr = custody_service.record_hash_in(
                conn, int(transfer_id), hash_in=data.get("hash_in", ""))
        except custody_service.CustodyError as exc:
            conn.close()
            return self._cust_conflict(exc)
        finally:
            conn.close()
        return self._cust_json({"transfer": tr})

    def api_custody_access(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be a JSON object."))
        conn = self._conn()
        try:
            rec = custody_service.log_access(
                conn,
                item_id=int(data.get("item_id", 0) or 0),
                actor=data.get("actor", ""),
                action=data.get("action", ""),
                purpose=data.get("purpose", ""),
            )
        except custody_service.CustodyError as exc:
            conn.close()
            return self._cust_conflict(exc)
        finally:
            conn.close()
        return self._cust_json({"access": rec}, status=201)

    def api_custody_disposition(self, environ):
        try:
            data = self._read_json(environ)
        except ValidationError:
            return _json(422, _error_envelope("validation_failed",
                                              "Body must be a JSON object."))
        conn = self._conn()
        try:
            rec = custody_service.record_disposition(
                conn,
                item_id=int(data.get("item_id", 0) or 0),
                disposition=data.get("disposition", ""),
                authorized_by=data.get("authorized_by", ""),
                authorization_ref=data.get("authorization_ref", ""),
                detail=data.get("detail", ""),
            )
        except custody_service.CustodyError as exc:
            conn.close()
            return self._cust_conflict(exc)
        finally:
            conn.close()
        return self._cust_json({"disposition": rec}, status=201)

    def api_custody_verify(self):
        conn = self._conn()
        try:
            verdict = custody_service.verify_custody_chain(conn)
            dual = custody_service.assert_dual_hash_verified(conn)
            coverage = custody_service.audit_access_coverage(conn)
        finally:
            conn.close()
        return self._cust_json({
            "chain_verification": verdict,
            "dual_hash_verification": dual,
            "access_coverage": coverage,
        })

    def api_custody_incidents(self):
        conn = self._conn()
        try:
            incidents = custody_service.list_incidents(conn)
        finally:
            conn.close()
        return self._cust_json({"incidents": incidents})

    def api_custody_seed(self, environ):
        conn = self._conn()
        try:
            try:
                result = custody_service.seed_synthetic_case(conn)
            except custody_service.CustodyError as exc:
                return self._cust_conflict(exc)
        finally:
            conn.close()
        return self._cust_json(result, status=201)

    # -- helpers ------------------------------------------------------------
    def _read_body(self, environ: dict) -> bytes:
        # Cache on the environ: error handlers may need the body after routing read it.
        if "_mavenu_body" not in environ:
            try:
                length = int(environ.get("CONTENT_LENGTH") or 0)
            except ValueError:
                length = 0
            environ["_mavenu_body"] = (
                environ["wsgi.input"].read(length) if length > 0 else b""
            )
        return environ["_mavenu_body"]

    def _read_json(self, environ: dict) -> dict:
        raw = self._read_body(environ)
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValidationError({"body": "Request body must be valid JSON."})
        if not isinstance(data, dict):
            raise ValidationError({"body": "Request body must be a JSON object."})
        return data

    def _idempotency_key(self, environ: dict, data: dict) -> Optional[str]:
        header = environ.get("HTTP_IDEMPOTENCY_KEY")
        if header:
            return header.strip() or None
        form_key = data.get("idempotency_key")
        return str(form_key).strip() or None if form_key else None

    # -- pages ------------------------------------------------------------------
    def hub(self):
        body = """
<p>Production-style AI automation projects built by Mavenu. Each project is a
working application with automated tests — or it is labeled honestly as planned.</p>
<div class="card"><h2>Project 01 — AI Revenue Operations Engine</h2>
<p>Synthetic home-services leads flow through intake, validation, rule-based
qualification, classifier routing, booking, and human review.</p>
<p><a href="/project01">Open the project</a> · <a href="/project01/dashboard">Dashboard</a></p>
<p><strong>Status:</strong> implemented + tested (Gate A)</p></div>
<div class="card"><h2>Project 02 — Enterprise Request &amp; Approval Automation</h2>
<p><strong>Status:</strong> implemented + tested (Gate B)</p>
<p>Request intake flows through validation, role-based multi-step approval
routing (manager → finance over a threshold), deterministic SLA-breach
escalation, and an actor-stamped audit trail. A portfolio simulation on the
custom Python stack — not a Power Platform implementation.</p>
<p><a href="/project02">Open the project</a> · <a href="/project02/dashboard">Dashboard</a></p></div>
<div class="card"><h2>Project 03 — AI Document Intelligence</h2>
<p><strong>Status:</strong> planned</p></div>
<div class="card"><h2>Project 04 — SQL Operations Intelligence</h2>
<p><strong>Status:</strong> planned</p></div>
<div class="card"><h2>Project 05 — Automation Reliability &amp; Governance Center</h2>
<p><strong>Status:</strong> planned</p></div>
<div class="card"><h2>Q01 — AI Missed-Call Recovery Engine</h2>
<p><strong>Status:</strong> implemented + tested</p>
<p>Synthetic missed-call events (CSV or JSON webhook shape) are normalized,
scored by a deterministic rule-based urgency engine, and worked through a
prioritized callback queue with per-call outcome tracking. Caller IDs are
masked and hashed — never stored raw.</p>
<p><a href="/project_q01">Open the project</a> · <a href="/project_q01/queue">Callback queue</a> ·
<a href="/project_q01/dashboard">Dashboard</a></p></div>
<div class="card"><h2>Q02 — Estimate Follow-Up Automation</h2>
<p><strong>Status:</strong> implemented + tested</p>
<p>Synthetic estimates move through a code-enforced lifecycle
(<code>draft → sent → viewed → followed_up → accepted | declined |
expired</code>). A configurable cadence (day 2 / 7 / 14) computes due
follow-ups on a frozen clock, renders versioned message templates, and
queues exactly one outbox row per (estimate, step) — idempotency keys make
scheduler replays duplicate-free. v1 sends nothing: a stub adapter writes
a send log instead. Aging, win/loss, and follow-up-effectiveness reports
are computed from the database and reconciled in tests.</p>
<p><a href="/project_q02">Open the project</a> · <a href="/project_q02/outbox">Outbox</a> ·
<a href="/project_q02/reports">Reports</a></p></div>
<div class="card"><h2>Q03 — Customer Reactivation Engine</h2>
<p><strong>Status:</strong> implemented + tested</p>
<p>Synthetic customer job histories are scored for dormancy with a
documented, deterministic RFM formula, segmented
(<code>active / cooling / dormant / churned</code>), and worked through
per-segment win-back sequences into an idempotent outbox queue. Suppression
flags (do-not-contact, recent complaint, active job) are honored
absolutely — checked at queue time and re-checked at send time. A
holdout-based attribution report compares treated vs. control return
rates, labeled explicitly as a synthetic-data illustration. v1 sends
nothing: a stub adapter writes a send log instead.</p>
<p><a href="/project_q03">Open the project</a> · <a href="/project_q03/segments">Segments</a> ·
<a href="/project_q03/outbox">Outbox</a> · <a href="/project_q03/attribution">Attribution</a> ·
<a href="/project_q03/suppression">Suppression audit</a></p></div>
<div class="card"><h2>Q04 — Conversational Booking Agent</h2>
<p><strong>Status:</strong> implemented + tested</p>
<p>A scripted (deterministic, rule-driven — not a language model) booking
agent fills slots in order — service → location → preferred window →
contact — and only offers availability returned by the booking adapter,
never invented times. Every turn carries a confidence score; below
threshold, on suspicious or contradictory input, or at the turn cap, the
conversation hands off to a human with the full masked transcript and
extracted slots. Bookings are written only after the adapter confirms.
Caller PII is masked at write time.</p>
<p><a href="/project_q04">Open the project</a> · <a href="/project_q04/handoffs">Handoff queue</a> ·
<a href="/project_q04/bookings">Bookings</a></p></div>
<div class="card"><h2>Q05 — Invoice Reconciliation &amp; Exception Reporter</h2>
<p><strong>Status:</strong> implemented + tested</p>
<p>Synthetic invoice and payment CSVs are ingested with schema validation,
row-level error reporting, and CSV-formula sanitization. A deterministic
two-pass matcher (exact invoice-ID pass, then scored fuzzy pass with a
documented threshold) pairs payments to invoices — every match carries its
reasons. Below-threshold candidates are never silently auto-matched: they
go to a human-review exception with their score breakdowns. Unmatched
invoices/payments, partial payments, overpayments, and duplicates land in
an exception queue (<code>open → investigating → resolved |
written_off</code>, code-enforced, actor-stamped) with a suggested next
action each. Aging and reconciliation reports reconcile to source rows.
Money is computed with Decimal, never float. Write-offs need a human.</p>
<p><a href="/project_q05">Open the project</a> · <a href="/project_q05/exceptions">Exception queue</a> ·
<a href="/project_q05/reports">Reports</a></p></div>
<div class="card"><h2>Q06 — Data Quality &amp; Entity Resolution Service</h2>
<p><strong>Status:</strong> implemented + tested</p>
<p>Synthetic contact CSVs from multiple sources are ingested, normalized
with deterministic idempotent cleaners, blocked on cheap equality keys
(phone digits, lowercased email, ZIP+surname) instead of an O(n²) scan,
and scored pairwise by a transparent weighted formula with documented
thresholds. Pairs land in <strong>match / review / no-match</strong>
bands. Match-band pairs get merge <em>proposals</em> — never automatic
merges: a named human confirms, every merge stores full pre-merge images
of both records with per-field provenance, and any merge is exactly
reversible. The human stays in the loop by design.</p>
<p><a href="/project_q06">Open the project</a> · <a href="/project_q06/pairs">Pair review</a> ·
<a href="/project_q06/merges">Merge proposals</a></p></div>"""
        return _html(200, "Mavenu Automation Portfolio", body)

    def project_page(self, errors: Optional[dict] = None, values: Optional[dict] = None):
        values = values or {}
        err_html = ""
        if errors:
            items = "".join(f"<li><strong>{k}</strong>: {v}</li>" for k, v in errors.items())
            err_html = f'<div class="error-list"><ul>{items}</ul></div>'
        options = "".join(
            f'<option value="{s}" {"selected" if values.get("service") == s else ""}>{s}</option>'
            for s in SERVICES
        )
        key = uuid.uuid4().hex
        body = f"""
<p>Submit a synthetic lead. Server-side validation, duplicate protection, and
workflow routing run on every submission. Low-confidence classifications go to
human review — never silently dropped.</p>
{err_html}
<form method="post" action="/project01/leads">
<input type="hidden" name="idempotency_key" value="{key}">
<label>Name <input name="name" value="{values.get("name","")}" required></label>
<label>Phone <input name="phone" value="{values.get("phone","")}" placeholder="10 digits"></label>
<label>Email <input name="email" value="{values.get("email","")}" placeholder="optional"></label>
<label>Service <select name="service">{options}</select></label>
<label>ZIP <input name="zip" value="{values.get("zip","")}" placeholder="5 digits" required></label>
<label>Urgency <select name="urgency">
<option value="standard">standard</option><option value="priority">priority</option></select></label>
<label>Notes <textarea name="notes" rows="3">{values.get("notes","")}</textarea></label>
<p><button type="submit">Submit lead</button></p>
</form>
<p>Prefer the API? <code>POST /api/leads</code> with JSON and an
<code>Idempotency-Key</code> header. See <code>projects/project01/DEMO.md</code>.</p>"""
        return _html(200, "Project 01 — AI Revenue Operations Engine", body)

    def form_submit(self, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        key = self._idempotency_key(environ, data)
        conn = self._conn()
        try:
            result = lead_service.submit_lead(
                conn, data, idempotency_key=key, classifier=self.classifier,
                booking_adapter=self.booking_adapter, actor="public-form",
                review_threshold=self.settings.review_confidence_threshold,
            )
        finally:
            conn.close()
        pid = result["body"]["public_id"]
        return 303, [("Location", f"/project01/leads/{pid}")], b""

    def lead_detail(self, public_id: str):
        conn = self._conn()
        try:
            lead = lead_service.get_lead(conn, public_id)
            if lead is None:
                return _html(404, "Not found", "<p>No such lead.</p>")
            events = lead_service.lead_events(conn, lead["id"])
        finally:
            conn.close()
        allowed = sorted(LEAD_WORKFLOW.allowed_from(lead["state"]))
        trans_opts = "".join(f'<option value="{s}">{s}</option>' for s in allowed)
        trans_form = (
            f"""<form method="post" action="/project01/leads/{lead['public_id']}">
<label>Reviewer action <select name="to_state">{trans_opts}</select></label>
<label>Reviewer name <input name="actor" value="reviewer"></label>
<p><button type="submit">Apply transition</button></p></form>"""
            if allowed else "<p><em>Terminal state — no further transitions.</em></p>"
        )
        rows = "".join(
            f"<tr><td>{k}</td><td>{'' if v is None else v}</td></tr>"
            for k, v in lead.items() if k != "id"
        )
        timeline = "".join(
            f"<li><code>{e['created_at']}</code> <strong>{e['event_type']}</strong> "
            f"by {e['actor']}"
            + (f" ({e['from_state']} → {e['to_state']})" if e["from_state"] or e["to_state"] else "")
            + (f" — <code>{e['detail']}</code>" if e["detail"] else "")
            + "</li>"
            for e in events
        )
        body = f"""
<p><span class="state">{lead['state']}</span></p>
<div class="card"><h2>Lead record</h2><table>{rows}</table></div>
<div class="card"><h2>Reviewer actions</h2>{trans_form}</div>
<div class="card"><h2>Audit timeline</h2><ul class="timeline">{timeline}</ul></div>"""
        return _html(200, f"Lead {lead['public_id']}", body)

    def lead_transition_form(self, public_id: str, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        to_state = data.get("to_state", "")
        actor = data.get("actor", "reviewer") or "reviewer"
        conn = self._conn()
        try:
            try:
                lead_service.transition_lead(conn, public_id, to_state, f"reviewer:{actor}")
            except Exception as exc:
                conn.close()
                return _html(400, "Transition failed",
                             f'<p class="errors">{exc}</p><p><a href="/project01/leads/{public_id}">Back</a></p>')
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return 303, [("Location", f"/project01/leads/{public_id}")], b""

    def dashboard(self):
        conn = self._conn()
        try:
            s = lead_service.stats(conn)
            recent = lead_service.list_leads(conn, limit=20)
        finally:
            conn.close()
        cells = "".join(
            f"<tr><td><span class='state'>{st}</span></td><td>{c}</td></tr>"
            for st, c in sorted(s["by_state"].items())
        )
        rows = "".join(
            f"<tr><td><a href=\"/project01/leads/{l['public_id']}\">{l['public_id']}</a></td>"
            f"<td>{l['name']}</td><td>{l['service']}</td>"
            f"<td><span class='state'>{l['state']}</span></td><td>{l['created_at']}</td></tr>"
            for l in recent
        )
        body = f"""
<div class="card"><h2>Totals (reconciled with the database)</h2>
<table><tr><th>State</th><th>Count</th></tr>{cells}
<tr><th>Total</th><th>{s['total']}</th></tr></table></div>
<div class="card"><h2>Recent leads</h2>
<table><tr><th>ID</th><th>Name</th><th>Service</th><th>State</th><th>Created</th></tr>
{rows}</table></div>"""
        return _html(200, "Project 01 — Operations Dashboard", body)

    # -- JSON API -----------------------------------------------------------------
    def api_create_lead(self, environ: dict):
        data = self._read_json(environ)
        key = self._idempotency_key(environ, data)
        data.pop("idempotency_key", None)
        conn = self._conn()
        try:
            result = lead_service.submit_lead(
                conn, data, idempotency_key=key, classifier=self.classifier,
                booking_adapter=self.booking_adapter, actor="api",
                review_threshold=self.settings.review_confidence_threshold,
            )
        finally:
            conn.close()
        status = 200 if result["replayed"] else result["status"]
        payload = dict(result["body"])
        if result["replayed"]:
            payload["replayed"] = True
        return _json(status, payload)

    def api_get_lead(self, public_id: str):
        conn = self._conn()
        try:
            lead = lead_service.get_lead(conn, public_id)
            if lead is None:
                return _json(404, _error_envelope("not_found", f"No lead {public_id!r}."))
            events = lead_service.lead_events(conn, lead["id"])
        finally:
            conn.close()
        lead["events"] = events
        lead["allowed_transitions"] = sorted(LEAD_WORKFLOW.allowed_from(lead["state"]))
        return _json(200, lead)

    def api_transition(self, public_id: str, environ: dict):
        data = self._read_json(environ)
        to_state = data.get("to_state", "")
        actor = data.get("actor", "api") or "api"
        conn = self._conn()
        try:
            lead = lead_service.transition_lead(conn, public_id, to_state, actor)
        except KeyError as exc:
            conn.close()
            return _json(404, _error_envelope("not_found", str(exc)))
        except Exception as exc:
            conn.close()
            return _json(409, _error_envelope("invalid_transition", str(exc)))
        conn.close()
        return _json(200, {"public_id": lead["public_id"], "state": lead["state"]})

    # -- Project 02: HTML pages ---------------------------------------------------
    def _p02_settings(self):
        # Routing/decision settings: accepted by submit_for_review(),
        # resubmit(), record_decision(), and sweep_sla().
        return {
            "finance_threshold_cents": self.settings.finance_threshold_cents,
            "sla_hours": self.settings.approval_sla_hours,
        }

    def _p02_intake_settings(self):
        # Intake settings: accepted by submit_request().
        return {
            "finance_threshold_cents": self.settings.finance_threshold_cents,
            "idempotency_ttl_hours": self.settings.idempotency_ttl_hours,
        }

    def p02_form_page(self, errors: Optional[dict] = None, values: Optional[dict] = None):
        values = values or {}
        err_html = ""
        if errors:
            items = "".join(f"<li><strong>{k}</strong>: {v}</li>" for k, v in errors.items())
            err_html = f'<div class="error-list"><ul>{items}</ul></div>'
        type_options = "".join(
            f'<option value="{t}" {"selected" if values.get("request_type") == t else ""}>{t}</option>'
            for t in REQUEST_TYPES
        )
        key = uuid.uuid4().hex
        body = f"""
<p><strong>Portfolio simulation</strong> — this form feeds a custom Python
workflow engine, not Power Platform, SharePoint, or UiPath. Submit a synthetic
request: server-side validation runs, then the requester submits it into a
role-based approval chain (manager, plus finance over
${self.settings.finance_threshold_cents / 100:,.0f}). Approvals stalled past the
{self.settings.approval_sla_hours}-hour SLA escalate to a director.</p>
{err_html}
<form method="post" action="/project02/requests">
<input type="hidden" name="idempotency_key" value="{key}">
<label>Request type <select name="request_type">{type_options}</select></label>
<label>Title <input name="title" value="{values.get("title","")}" required></label>
<label>Amount (dollars) <input name="amount" value="{values.get("amount","")}"
placeholder="e.g. 2500 — required for purchase/travel/vendor/budget"></label>
<label>Cost center <input name="cost_center" value="{values.get("cost_center","")}"
placeholder="OPS410" required></label>
<label>Justification (min 20 chars) <textarea name="justification" rows="3">{values.get("justification","")}</textarea></label>
<label>Requester name <input name="requester_name" value="{values.get("requester_name","")}" required></label>
<label>Requester email <input name="requester_email" value="{values.get("requester_email","")}" required></label>
<p><button type="submit">Create request</button></p>
</form>
<p>Prefer the API? <code>POST /api/requests</code> with JSON and an
<code>Idempotency-Key</code> header. See <code>projects/project02/DEMO.md</code>.</p>"""
        return _html(200, "Project 02 — Enterprise Request & Approval Automation", body)

    def p02_form_submit(self, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        key = self._idempotency_key(environ, data)
        conn = self._conn()
        try:
            result = request_service.submit_request(
                conn, data, idempotency_key=key, actor="public-form",
                **self._p02_intake_settings(),
            )
        finally:
            conn.close()
        pid = result["body"]["public_id"]
        return 303, [("Location", f"/project02/requests/{pid}")], b""

    def p02_detail(self, public_id: str):
        conn = self._conn()
        try:
            request = request_service.get_request(conn, public_id)
            if request is None:
                return _html(404, "Not found", "<p>No such request.</p>")
            events = request_service.request_events(conn, request["id"])
        finally:
            conn.close()
        import json as _json_mod
        chain = _json_mod.loads(request["approval_chain"])
        cur_role = (
            chain[request["current_step"]]
            if request["state"] in ("in_review", "escalated") and chain
            else None
        )
        chain_html = (
            "<ol>" + "".join(
                f"<li>{'&#8594; ' if i == request['current_step'] and request['state'] in ('in_review','escalated') else ''}"
                f"<strong>{r}</strong>{' (current)' if i == request['current_step'] and request['state'] in ('in_review','escalated') else ''}</li>"
                for i, r in enumerate(chain)
            ) + "</ol>" if chain else "<p><em>Chain is built when the request is submitted.</em></p>"
        )
        if cur_role:
            decision_form = f"""
<form method="post" action="/project02/requests/{request['public_id']}">
<label>Your name <input name="actor" value="reviewer"></label>
<label>Your role <select name="role">
<option value="{cur_role}">{cur_role} (owns this step)</option>
<option value="manager">manager</option><option value="finance">finance</option>
<option value="director">director</option></select></label>
<label>Decision <select name="decision">
<option value="approve">approve</option><option value="reject">reject</option>
<option value="request_changes">request changes</option></select></label>
<p><button type="submit">Record decision</button></p></form>"""
        else:
            decision_form = "<p><em>No pending approval step in this state.</em></p>"
        submit_form = ""
        if request["state"] == "draft":
            submit_form = f"""
<form method="post" action="/project02/requests/{request['public_id']}">
<input type="hidden" name="decision" value="__submit__">
<label>Your name <input name="actor" value="requester"></label>
<p><button type="submit">Submit for approval</button></p></form>"""
        elif request["state"] == "changes_requested":
            submit_form = f"""
<form method="post" action="/project02/requests/{request['public_id']}">
<input type="hidden" name="decision" value="__resubmit__">
<label>Your name <input name="actor" value="requester"></label>
<p><button type="submit">Resubmit</button></p></form>"""
        elif request["state"] == "approved":
            submit_form = f"""
<form method="post" action="/project02/requests/{request['public_id']}">
<input type="hidden" name="decision" value="__fulfill__">
<label>Your name <input name="actor" value="ops"></label>
<p><button type="submit">Mark fulfilled</button></p></form>"""
        rows = "".join(
            f"<tr><td>{k}</td><td>{'' if v is None else v}</td></tr>"
            for k, v in request.items() if k != "id"
        )
        timeline = "".join(
            f"<li><code>{e['created_at']}</code> <strong>{e['event_type']}</strong> "
            f"by {e['actor']}"
            + (f" as {e['role']}" if e["role"] else "")
            + (f" ({e['from_state']} → {e['to_state']})" if e["from_state"] or e["to_state"] else "")
            + (f" — <code>{e['detail']}</code>" if e["detail"] else "")
            + "</li>"
            for e in events
        )
        body = f"""
<p><span class="state">{request['state']}</span></p>
<div class="card"><h2>Request record</h2><table>{rows}</table></div>
<div class="card"><h2>Approval chain</h2>{chain_html}
{decision_form}{submit_form}</div>
<div class="card"><h2>Audit timeline</h2><ul class="timeline">{timeline}</ul></div>"""
        return _html(200, f"Request {request['public_id']}", body)

    def p02_decision_form(self, public_id: str, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        action = data.get("decision", "")
        actor = data.get("actor", "reviewer") or "reviewer"
        conn = self._conn()
        try:
            s = self._p02_settings()
            try:
                if action == "__submit__":
                    request_service.submit_for_review(conn, public_id, actor, **s)
                elif action == "__resubmit__":
                    request_service.resubmit(conn, public_id, actor, **s)
                elif action == "__fulfill__":
                    request_service.fulfill(conn, public_id, f"ops:{actor}")
                else:
                    role = data.get("role", "")
                    request_service.record_decision(
                        conn, public_id, decision=action, role=role,
                        actor=f"reviewer:{actor}", **s,
                    )
            except Exception as exc:
                conn.close()
                return _html(400, "Action failed",
                             f'<p class="errors">{exc}</p>'
                             f'<p><a href="/project02/requests/{public_id}">Back</a></p>')
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return 303, [("Location", f"/project02/requests/{public_id}")], b""

    def p02_dashboard(self):
        conn = self._conn()
        try:
            s = request_service.request_stats(conn)
            recent = request_service.list_requests(conn, limit=20)
            at_risk = conn.execute(
                """SELECT * FROM requests
                   WHERE state = 'in_review' AND sla_due_at IS NOT NULL
                   ORDER BY sla_due_at ASC LIMIT 10"""
            ).fetchall()
        finally:
            conn.close()
        state_cells = "".join(
            f"<tr><td><span class='state'>{st}</span></td><td>{c}</td></tr>"
            for st, c in sorted(s["by_state"].items())
        )
        type_cells = "".join(
            f"<tr><td>{t}</td><td>{c}</td></tr>" for t, c in sorted(s["by_type"].items())
        )
        risk_rows = "".join(
            f"<tr><td><a href=\"/project02/requests/{r['public_id']}\">{r['public_id']}</a></td>"
            f"<td>{r['title']}</td><td>{r['sla_due_at']}</td></tr>"
            for r in at_risk
        ) or '<tr><td colspan="3"><em>None pending.</em></td></tr>'
        recent_rows = "".join(
            f"<tr><td><a href=\"/project02/requests/{r['public_id']}\">{r['public_id']}</a></td>"
            f"<td>{r['request_type']}</td><td>{r['title']}</td>"
            f"<td><span class='state'>{r['state']}</span></td><td>{r['created_at']}</td></tr>"
            for r in recent
        )
        body = f"""
<div class="card"><h2>Totals (computed from the database)</h2>
<table><tr><th>State</th><th>Count</th></tr>{state_cells}
<tr><th>Total</th><th>{s['total']}</th></tr></table>
<p>By type:</p>
<table><tr><th>Type</th><th>Count</th></tr>{type_cells}</table>
<p>SLA-breached (past due): <strong>{s['sla_breached']}</strong> ·
Escalated: <strong>{s['escalated']}</strong></p></div>
<div class="card"><h2>SLA watch — pending steps by deadline</h2>
<table><tr><th>ID</th><th>Title</th><th>SLA due</th></tr>{risk_rows}</table></div>
<div class="card"><h2>Recent requests</h2>
<table><tr><th>ID</th><th>Type</th><th>Title</th><th>State</th><th>Created</th></tr>
{recent_rows}</table></div>"""
        return _html(200, "Project 02 — Operations Dashboard", body)

    # -- Project 02: JSON API -------------------------------------------------------
    def _p02_error(self, exc: Exception) -> tuple[int, list, bytes]:
        if isinstance(exc, KeyError):
            return _json(404, _error_envelope("not_found", str(exc)))
        if isinstance(exc, (InvalidDecision, ApprovalRoleError, InvalidTransition)):
            return _json(409, _error_envelope("decision_rejected", str(exc)))
        if isinstance(exc, ValidationError):
            return _json(422, _error_envelope("validation_failed",
                                             "The submission failed validation.",
                                             exc.field_errors))
        raise exc

    def api_create_request(self, environ: dict):
        data = self._read_json(environ)
        key = self._idempotency_key(environ, data)
        data.pop("idempotency_key", None)
        conn = self._conn()
        try:
            result = request_service.submit_request(
                conn, data, idempotency_key=key, actor="api", **self._p02_intake_settings()
            )
        except Exception as exc:
            conn.close()
            return self._p02_error(exc)
        conn.close()
        status = 200 if result["replayed"] else result["status"]
        payload = dict(result["body"])
        if result["replayed"]:
            payload["replayed"] = True
        return _json(status, payload)

    def api_get_request(self, public_id: str):
        conn = self._conn()
        try:
            request = request_service.get_request(conn, public_id)
            if request is None:
                return _json(404, _error_envelope("not_found", f"No request {public_id!r}."))
            import json as _json_mod
            request["events"] = request_service.request_events(conn, request["id"])
            request["approval_chain_roles"] = _json_mod.loads(request["approval_chain"])
            request["allowed_transitions"] = sorted(
                REQUEST_WORKFLOW.allowed_from(request["state"])
            )
        finally:
            conn.close()
        return _json(200, request)

    def api_submit_request(self, public_id: str, environ: dict):
        data = self._read_json(environ)
        actor = data.get("actor", "api") or "api"
        conn = self._conn()
        try:
            request = request_service.submit_for_review(
                conn, public_id, actor, **self._p02_settings()
            )
        except Exception as exc:
            conn.close()
            return self._p02_error(exc)
        conn.close()
        return _json(200, {"public_id": request["public_id"], "state": request["state"]})

    def api_decide(self, public_id: str, environ: dict):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            request = request_service.record_decision(
                conn, public_id,
                decision=data.get("decision", ""),
                role=data.get("role", ""),
                actor=data.get("actor", "api") or "api",
                **self._p02_settings(),
            )
        except Exception as exc:
            conn.close()
            return self._p02_error(exc)
        conn.close()
        return _json(200, {"public_id": request["public_id"], "state": request["state"]})

    def api_cancel_request(self, public_id: str, environ: dict):
        data = self._read_json(environ)
        actor = data.get("actor", "api") or "api"
        conn = self._conn()
        try:
            request = request_service.cancel(conn, public_id, actor)
        except Exception as exc:
            conn.close()
            return self._p02_error(exc)
        conn.close()
        return _json(200, {"public_id": request["public_id"], "state": request["state"]})

    def api_fulfill_request(self, public_id: str, environ: dict):
        data = self._read_json(environ)
        actor = data.get("actor", "api") or "api"
        conn = self._conn()
        try:
            request = request_service.fulfill(conn, public_id, actor)
        except Exception as exc:
            conn.close()
            return self._p02_error(exc)
        conn.close()
        return _json(200, {"public_id": request["public_id"], "state": request["state"]})

    def api_resubmit_request(self, public_id: str, environ: dict):
        data = self._read_json(environ)
        actor = data.get("actor", "api") or "api"
        conn = self._conn()
        try:
            request = request_service.resubmit(
                conn, public_id, actor, **self._p02_settings()
            )
        except Exception as exc:
            conn.close()
            return self._p02_error(exc)
        conn.close()
        return _json(200, {"public_id": request["public_id"], "state": request["state"]})

    def api_sla_sweep(self):
        conn = self._conn()
        try:
            escalated = request_service.sweep_sla(conn, sla_hours=self.settings.approval_sla_hours)
        finally:
            conn.close()
        return _json(200, {"escalated": [r["public_id"] for r in escalated]})

    # -- Q01: missed-call recovery — HTML pages --------------------------------
    def q01_form_page(self, errors: Optional[dict] = None, values: Optional[dict] = None):
        values = values or {}
        err_html = ""
        if errors:
            items = "".join(f"<li><strong>{k}</strong>: {v}</li>" for k, v in errors.items())
            err_html = f'<div class="error-list"><ul>{items}</ul></div>'
        key = uuid.uuid4().hex
        body = f"""
<p><strong>Synthetic data only.</strong> Record a missed call either as a
single event or by pasting CSV. Caller IDs are masked and hashed on ingest —
the raw number is never stored. Urgency is scored by a deterministic
rule-based engine (no telephony integration in v1).</p>
{err_html}
<h2>Single event</h2>
<form method="post" action="/project_q01/import">
<input type="hidden" name="idempotency_key" value="{key}">
<label>Timestamp (ISO-8601) <input name="timestamp" value="{values.get("timestamp","")}"
placeholder="2026-10-23T14:30:00" required></label>
<label>Caller ID <input name="caller_id" value="{values.get("caller_id","")}"
placeholder="7015550142 (synthetic only)" required></label>
<label>Ring count <input name="ring_count" value="{values.get("ring_count","")}"></label>
<label>Voicemail transcript (typed/pasted, optional)
<textarea name="transcript" rows="3">{values.get("transcript","")}</textarea></label>
<p><button type="submit">Ingest single call</button></p>
</form>
<h2>CSV batch</h2>
<form method="post" action="/project_q01/import">
<input type="hidden" name="idempotency_key" value="{key}">
<label>Paste CSV (header: timestamp,caller_id,ring_count,duration_seconds,transcript)
<textarea name="csv" rows="6">{values.get("csv","")}</textarea></label>
<p><button type="submit">Import CSV</button></p>
</form>
<p>Prefer the API? <code>POST /api/missed-calls</code> (JSON event) or
<code>POST /api/missed-calls/import</code> (JSON <code>{{"csv": "..."}}</code>),
with an optional <code>Idempotency-Key</code> header. See
<code>projects/project_q01/DEMO.md</code>.</p>"""
        return _html(200, "Q01 — Missed-Call Recovery Engine", body)

    def q01_import_submit(self, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        key = self._idempotency_key(environ, data)
        conn = self._conn()
        try:
            csv_text = (data.get("csv") or "").strip()
            if csv_text:
                result = mc_service.ingest_with_idempotency(
                    conn, csv_text, idempotency_key=key, is_csv=True,
                    source="csv", actor="public-form", scorer=self.urgency_scorer,
                )
            else:
                payload = {k: v for k, v in data.items()
                           if k in ("timestamp", "caller_id", "ring_count",
                                    "duration_seconds", "transcript") and v != ""}
                result = mc_service.ingest_with_idempotency(
                    conn, payload, idempotency_key=key, is_csv=False,
                    source="webhook", actor="public-form", scorer=self.urgency_scorer,
                )
        finally:
            conn.close()
        return 303, [("Location", "/project_q01/queue")], b""

    def q01_queue(self):
        conn = self._conn()
        try:
            queue = mc_service.priority_queue(conn)
        finally:
            conn.close()
        rows = "".join(
            f"<tr><td><a href=\"/project_q01/calls/{c['public_id']}\">{c['public_id']}</a></td>"
            f"<td>{c['caller_id_masked']}</td><td>{c['missed_at']}</td>"
            f"<td>{c['urgency_score']:.3f}</td><td>{c['age_hours']:.1f}h</td>"
            f"<td><strong>{c['priority']:.4f}</strong></td>"
            f"<td>{c['assigned_to'] or '—'}</td>"
            f"<td>{'yes' if c['escalated'] else 'no'}</td></tr>"
            for c in queue
        ) or '<tr><td colspan="8"><em>Queue is empty.</em></td></tr>'
        body = f"""
<p>Pending calls ordered by priority = urgency score × age decay (halves every
24h). Claim a call, then log each callback outcome until it is
<code>booked</code> or <code>lost</code>.</p>
<div class="card"><h2>Callback queue ({len(queue)} pending)</h2>
<table><tr><th>ID</th><th>Caller</th><th>Missed at</th><th>Urgency</th>
<th>Age</th><th>Priority</th><th>Assigned</th><th>Escalated</th></tr>
{rows}</table></div>"""
        return _html(200, "Q01 — Callback Queue", body)

    def q01_detail(self, public_id: str):
        conn = self._conn()
        try:
            call = mc_service.get_call(conn, public_id)
            if call is None:
                return _html(404, "Not found", "<p>No such missed call.</p>")
            events = mc_service.call_events(conn, call["id"])
        finally:
            conn.close()
        allowed = sorted(CALL_WORKFLOW.allowed_from(call["state"]))
        trans_opts = "".join(f'<option value="{s}">{s}</option>' for s in allowed)
        outcome_form = (
            f"""<form method="post" action="/project_q01/calls/{call['public_id']}">
<input type="hidden" name="action" value="outcome">
<label>Log outcome <select name="to_state">{trans_opts}</select></label>
<label>Your name <input name="actor" value="agent"></label>
<p><button type="submit">Log outcome</button></p></form>"""
            if allowed else "<p><em>Terminal state — no further outcomes.</em></p>"
        )
        claim_form = (
            f"""<form method="post" action="/project_q01/calls/{call['public_id']}">
<input type="hidden" name="action" value="claim">
<label>Assign to <input name="assignee" placeholder="e.g. Rosa"></label>
<label>Your name <input name="actor" value="agent"></label>
<p><button type="submit">Claim call</button></p></form>"""
            if call["state"] == "pending" else ""
        )
        rows = "".join(
            f"<tr><td>{k}</td><td>{'' if v is None else v}</td></tr>"
            for k, v in call.items() if k != "id"
        )
        timeline = "".join(
            f"<li><code>{e['created_at']}</code> <strong>{e['event_type']}</strong> "
            f"by {e['actor']}"
            + (f" ({e['from_state']} → {e['to_state']})" if e["from_state"] or e["to_state"] else "")
            + (f" — <code>{e['detail']}</code>" if e["detail"] else "")
            + "</li>"
            for e in events
        )
        body = f"""
<p><span class="state">{call['state']}</span>
 urgency <strong>{call['urgency_score']:.3f}</strong></p>
<div class="card"><h2>Call record (caller ID masked)</h2><table>{rows}</table></div>
<div class="card"><h2>Claim / assign</h2>{claim_form or "<p><em>Only pending calls can be claimed.</em></p>"}</div>
<div class="card"><h2>Outcome</h2>{outcome_form}</div>
<div class="card"><h2>Audit timeline</h2><ul class="timeline">{timeline}</ul></div>"""
        return _html(200, f"Call {call['public_id']}", body)

    def q01_action_form(self, public_id: str, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        action = data.get("action", "")
        actor = data.get("actor", "agent") or "agent"
        conn = self._conn()
        try:
            try:
                if action == "claim":
                    mc_service.claim_call(conn, public_id, data.get("assignee", ""), f"agent:{actor}")
                else:
                    mc_service.log_outcome(conn, public_id, data.get("to_state", ""), f"agent:{actor}")
            except Exception as exc:
                conn.close()
                return _html(400, "Action failed",
                             f'<p class="errors">{exc}</p>'
                             f'<p><a href="/project_q01/calls/{public_id}">Back</a></p>')
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return 303, [("Location", f"/project_q01/calls/{public_id}")], b""

    def q01_dashboard(self):
        conn = self._conn()
        try:
            s = mc_service.dashboard_stats(conn)
            lag = mc_service.ingestion_lag_report(conn)
        finally:
            conn.close()
        cells = "".join(
            f"<tr><td><span class='state'>{st}</span></td><td>{c}</td></tr>"
            for st, c in sorted(s["by_state"].items())
        )
        ttcb = (f"{s['median_time_to_callback_minutes']} min" if s["median_time_to_callback_minutes"] is not None
                else "—")
        body = f"""
<div class="card"><h2>Recovery metrics (computed from the database)</h2>
<table><tr><th>State</th><th>Count</th></tr>{cells}
<tr><th>Total missed calls</th><th>{s['total']}</th></tr></table>
<p>Recovery rate (booked / total): <strong>{s['recovery_rate']:.1%}</strong><br>
Contact rate (connected + booked / total): <strong>{s['contact_rate']:.1%}</strong><br>
Median time to callback: <strong>{ttcb}</strong> (over {s['attempted_calls']} attempted)<br>
Escalated (SLA): <strong>{s['escalated']}</strong> ·
High-urgency pending: <strong>{s['high_urgency_pending']}</strong></p></div>
<div class="card"><h2>Ingestion health</h2>
<p>{lag['message']}</p></div>"""
        return _html(200, "Q01 — Recovery Dashboard", body)

    # -- Q01: JSON API -----------------------------------------------------------
    def _q01_error(self, exc: Exception) -> tuple[int, list, bytes]:
        if isinstance(exc, KeyError):
            return _json(404, _error_envelope("not_found", str(exc)))
        if isinstance(exc, (InvalidTransition, ValueError)):
            return _json(409, _error_envelope("action_rejected", str(exc)))
        if isinstance(exc, ValidationError):
            return _json(422, _error_envelope("validation_failed",
                                             "The submission failed validation.",
                                             exc.field_errors))
        raise exc

    def api_ingest_call(self, environ: dict):
        data = self._read_json(environ)
        key = self._idempotency_key(environ, data)
        data.pop("idempotency_key", None)
        conn = self._conn()
        try:
            result = mc_service.ingest_with_idempotency(
                conn, data, idempotency_key=key, is_csv=False,
                source="webhook", actor="api", scorer=self.urgency_scorer,
            )
        except Exception as exc:
            conn.close()
            return self._q01_error(exc)
        conn.close()
        status = 200 if result["replayed"] else result["status"]
        payload = dict(result["body"])
        if result["replayed"]:
            payload["replayed"] = True
        return _json(status, payload)

    def api_import_csv(self, environ: dict):
        data = self._read_json(environ)
        key = self._idempotency_key(environ, data)
        csv_text = data.get("csv", "")
        if not isinstance(csv_text, str) or not csv_text.strip():
            return _json(422, _error_envelope("validation_failed",
                                             "Field 'csv' must be non-empty text."))
        conn = self._conn()
        try:
            result = mc_service.ingest_with_idempotency(
                conn, csv_text, idempotency_key=key, is_csv=True,
                source="csv", actor="api", scorer=self.urgency_scorer,
            )
        except Exception as exc:
            conn.close()
            return self._q01_error(exc)
        conn.close()
        status = 200 if result["replayed"] else result["status"]
        payload = dict(result["body"])
        if result["replayed"]:
            payload["replayed"] = True
        return _json(status, payload)

    def api_get_call(self, public_id: str):
        conn = self._conn()
        try:
            call = mc_service.get_call(conn, public_id)
            if call is None:
                return _json(404, _error_envelope("not_found", f"No call {public_id!r}."))
            call["events"] = mc_service.call_events(conn, call["id"])
            call["allowed_transitions"] = sorted(CALL_WORKFLOW.allowed_from(call["state"]))
        finally:
            conn.close()
        return _json(200, call)

    def api_q01_queue(self):
        conn = self._conn()
        try:
            queue = mc_service.priority_queue(conn)
        finally:
            conn.close()
        return _json(200, {"pending": len(queue), "queue": queue})

    def api_claim_call(self, public_id: str, environ: dict):
        data = self._read_json(environ)
        actor = data.get("actor", "api") or "api"
        conn = self._conn()
        try:
            call = mc_service.claim_call(conn, public_id, data.get("assignee", ""), actor)
        except Exception as exc:
            conn.close()
            return self._q01_error(exc)
        conn.close()
        return _json(200, {"public_id": call["public_id"], "assigned_to": call["assigned_to"],
                           "state": call["state"]})

    def api_log_outcome(self, public_id: str, environ: dict):
        data = self._read_json(environ)
        actor = data.get("actor", "api") or "api"
        conn = self._conn()
        try:
            call = mc_service.log_outcome(conn, public_id, data.get("to_state", ""), actor)
        except Exception as exc:
            conn.close()
            return self._q01_error(exc)
        conn.close()
        return _json(200, {"public_id": call["public_id"], "state": call["state"]})

    def api_q01_dashboard(self):
        conn = self._conn()
        try:
            return _json(200, mc_service.dashboard_stats(conn))
        finally:
            conn.close()

    def api_q01_sweep(self):
        conn = self._conn()
        try:
            escalated = mc_service.sweep_sla(conn)
        finally:
            conn.close()
        return _json(200, {"escalated": [c["public_id"] for c in escalated]})

    # -- Q02: estimate follow-up automation — HTML pages -----------------------
    def q02_form_page(self, errors: Optional[dict] = None, values: Optional[dict] = None):
        values = values or {}
        err_html = ""
        if errors:
            items = "".join(f"<li><strong>{k}</strong>: {v}</li>" for k, v in errors.items())
            err_html = f'<div class="error-list"><ul>{items}</ul></div>'
        options = "".join(
            f'<option value="{s}" {"selected" if values.get("service_type") == s else ""}>{s}</option>'
            for s in SERVICES
        )
        key = uuid.uuid4().hex
        conn = self._conn()
        try:
            recent = estimate_service.list_estimates(conn, limit=20)
        finally:
            conn.close()
        rows = "".join(
            f"<tr><td><a href=\"/project_q02/estimates/{e['public_id']}\">{e['public_id']}</a></td>"
            f"<td>{e['customer_name']}</td><td>{e['service_type']}</td>"
            f"<td>{e['estimator']}</td><td>${e['amount_cents']/100:,.2f}</td>"
            f"<td><span class='state'>{e['state']}</span></td></tr>"
            for e in recent
        ) or '<tr><td colspan="6"><em>No estimates yet.</em></td></tr>'
        body = f"""
<p><strong>Synthetic data only.</strong> Create an estimate, walk it through
the lifecycle (<code>draft → sent → viewed → followed_up → accepted |
declined | expired</code>), and run the follow-up cadence. The scheduler
queues rendered messages into the outbox — <strong>nothing is ever
sent</strong> (the adapter is a stub).</p>
{err_html}
<h2>New estimate</h2>
<form method="post" action="/project_q02/estimates">
<input type="hidden" name="idempotency_key" value="{key}">
<label>Customer (synthetic) <input name="customer_name"
value="{values.get("customer_name","")}" placeholder="Acme Test Co" required></label>
<label>Service <select name="service">{options}</select></label>
<label>Estimator <input name="estimator" value="{values.get("estimator","")}"
placeholder="Rosa" required></label>
<label>Amount (dollars) <input name="amount" value="{values.get("amount","")}"
placeholder="1250.00" required></label>
<label>Notes <textarea name="notes" rows="2">{values.get("notes","")}</textarea></label>
<p><button type="submit">Create estimate</button></p>
</form>
<div class="card"><h2>Recent estimates</h2>
<table><tr><th>ID</th><th>Customer</th><th>Service</th><th>Estimator</th>
<th>Amount</th><th>State</th></tr>{rows}</table></div>
<div class="card"><h2>Cadence</h2>
<form method="post" action="/project_q02/cadence-run" style="display:inline">
<p><button type="submit">Run cadence now</button></p></form>
<p>Rules (step → days after sent): see <a href="/project_q02/templates">templates</a>
and <code>GET /api/cadence/rules</code>.</p></div>"""
        return _html(200, "Q02 — Estimate Follow-Up Automation", body)

    def q02_create_submit(self, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        key = self._idempotency_key(environ, data)
        payload = {
            "customer_name": data.get("customer_name", ""),
            "service_type": data.get("service", ""),
            "estimator": data.get("estimator", ""),
            "notes": data.get("notes", ""),
        }
        try:
            payload["amount_cents"] = int(round(float(data.get("amount", "0") or "0") * 100))
        except ValueError:
            payload["amount_cents"] = data.get("amount", "")
        conn = self._conn()
        try:
            result = estimate_service.create_with_idempotency(
                conn, payload, idempotency_key=key, actor="public-form",
            )
        finally:
            conn.close()
        pid = result["body"]["public_id"]
        return 303, [("Location", f"/project_q02/estimates/{pid}")], b""

    def q02_detail(self, public_id: str):
        conn = self._conn()
        try:
            estimate = estimate_service.get_estimate(conn, public_id)
            if estimate is None:
                return _html(404, "Not found", "<p>No such estimate.</p>")
            events = estimate_service.estimate_events(conn, estimate["id"])
            outbox_rows = cadence_service.outbox(conn)
            queued = [r for r in outbox_rows if r["estimate_id"] == estimate["id"]]
        finally:
            conn.close()
        allowed = sorted(ESTIMATE_WORKFLOW.allowed_from(estimate["state"]))
        trans_opts = "".join(f'<option value="{s}">{s}</option>' for s in allowed)
        reason_opts = "".join(
            f'<option value="{r}">{r}</option>'
            for r in estimate_service.DECLINE_REASONS
        )
        trans_form = (
            f"""<form method="post" action="/project_q02/estimates/{estimate['public_id']}">
<input type="hidden" name="action" value="transition">
<label>Move to <select name="to_state">{trans_opts}</select></label>
<label>Decline reason (required only when declining)
<select name="decline_reason">{reason_opts}</select></label>
<label>Decline note <input name="decline_note" placeholder="optional"></label>
<label>Your name <input name="actor" value="agent"></label>
<p><button type="submit">Apply transition</button></p></form>"""
            if allowed else "<p><em>Terminal state — no further transitions.</em></p>"
        )
        unsub = (
            f"""<form method="post" action="/project_q02/estimates/{estimate['public_id']}">
<input type="hidden" name="action" value="unsubscribe">
<label>Your name <input name="actor" value="agent"></label>
<p><button type="submit">Mark unsubscribed (stop follow-ups)</button></p></form>"""
            if not estimate["unsubscribed"]
            else "<p><em>Unsubscribed — the cadence skips this estimate.</em></p>"
        )
        rows = "".join(
            f"<tr><td>{k}</td><td>{'' if v is None else v}</td></tr>"
            for k, v in estimate.items() if k != "id"
        )
        ob_rows = "".join(
            f"<tr><td>{r['id']}</td><td>step {r['step_index']}</td>"
            f"<td>{r['template_name']} v{r['template_version']}</td>"
            f"<td><span class='state'>{r['status']}</span></td>"
            f"<td><code>{r['idempotency_key']}</code></td></tr>"
            for r in queued
        ) or '<tr><td colspan="5"><em>No outbox rows for this estimate.</em></td></tr>'
        timeline = "".join(
            f"<li><code>{e['created_at']}</code> <strong>{e['event_type']}</strong> "
            f"by {e['actor']}"
            + (f" ({e['from_state']} → {e['to_state']})" if e["from_state"] or e["to_state"] else "")
            + (f" — <code>{e['detail']}</code>" if e["detail"] else "")
            + "</li>"
            for e in events
        )
        body = f"""
<p><span class="state">{estimate['state']}</span>
 amount <strong>${estimate['amount_cents']/100:,.2f}</strong></p>
<div class="card"><h2>Estimate record</h2><table>{rows}</table></div>
<div class="card"><h2>Lifecycle transition</h2>{trans_form}</div>
<div class="card"><h2>Opt-out</h2>{unsub}</div>
<div class="card"><h2>Outbox rows</h2>
<table><tr><th>ID</th><th>Step</th><th>Template</th><th>Status</th>
<th>Idempotency key</th></tr>{ob_rows}</table></div>
<div class="card"><h2>Audit timeline</h2><ul class="timeline">{timeline}</ul></div>"""
        return _html(200, f"Estimate {estimate['public_id']}", body)

    def q02_action_form(self, public_id: str, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        action = data.get("action", "")
        actor = data.get("actor", "agent") or "agent"
        conn = self._conn()
        try:
            try:
                if action == "unsubscribe":
                    estimate_service.set_unsubscribed(conn, public_id, f"agent:{actor}")
                else:
                    estimate_service.transition_estimate(
                        conn, public_id, data.get("to_state", ""), f"agent:{actor}",
                        decline_reason=data.get("decline_reason", ""),
                        decline_note=data.get("decline_note", ""),
                    )
            except Exception as exc:
                conn.close()
                return _html(400, "Action failed",
                             f'<p class="errors">{exc}</p>'
                             f'<p><a href="/project_q02/estimates/{public_id}">Back</a></p>')
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return 303, [("Location", f"/project_q02/estimates/{public_id}")], b""

    def q02_outbox(self):
        conn = self._conn()
        try:
            rows = cadence_service.outbox(conn)
            log = cadence_service.send_log(conn)
            rules = cadence_service.list_rules(conn)
        finally:
            conn.close()
        rule_line = ", ".join(
            f"step {r['step_index']} → day {r['days_after_sent']:g} ({r['template_name']})"
            for r in rules
        ) or "<em>no active rules</em>"
        ob = "".join(
            f"<tr><td>{r['id']}</td><td>{r['estimate_id']}</td>"
            f"<td>step {r['step_index']}</td><td>{r['template_name']} v{r['template_version']}</td>"
            f"<td><span class='state'>{r['status']}</span></td>"
            f"<td><code>{r['idempotency_key']}</code></td>"
            f"<td>{r['created_at']}</td></tr>"
            for r in rows
        ) or '<tr><td colspan="7"><em>Outbox is empty. Run the cadence.</em></td></tr>'
        lg = "".join(
            f"<tr><td>{r['id']}</td><td>{r['outbox_id']}</td><td>{r['adapter']}</td>"
            f"<td>{r['status']}</td><td>{r['created_at']}</td></tr>"
            for r in log
        ) or '<tr><td colspan="5"><em>No sends logged yet.</em></td></tr>'
        body = f"""
<p>The outbox is <strong>not a mail server</strong>: rows are rendered
follow-ups waiting on the send adapter. v1's adapter is a stub — flushing
writes a send-log row and delivers nothing.</p>
<div class="card"><h2>Active cadence rules</h2><p>{rule_line}</p>
<form method="post" action="/project_q02/cadence-run" style="display:inline">
<p><button type="submit">Run cadence now</button></p></form></div>
<div class="card"><h2>Outbox ({len(rows)} rows)</h2>
<table><tr><th>ID</th><th>Estimate</th><th>Step</th><th>Template</th>
<th>Status</th><th>Idempotency key</th><th>Queued</th></tr>{ob}</table>
<form method="post" action="/project_q02/outbox/flush">
<p><button type="submit">Flush outbox (stub adapter — sends nothing)</button></p></form></div>
<div class="card"><h2>Send log ({len(log)} rows)</h2>
<table><tr><th>ID</th><th>Outbox</th><th>Adapter</th><th>Status</th>
<th>At</th></tr>{lg}</table></div>"""
        return _html(200, "Q02 — Follow-Up Outbox", body)

    def q02_flush_submit(self):
        conn = self._conn()
        try:
            cadence_service.flush_outbox(conn)
        finally:
            conn.close()
        return 303, [("Location", "/project_q02/outbox")], b""

    def q02_cadence_run_submit(self):
        conn = self._conn()
        try:
            cadence_service.run_cadence(conn)
        finally:
            conn.close()
        return 303, [("Location", "/project_q02/outbox")], b""

    def q02_reports(self):
        conn = self._conn()
        try:
            aging = report_service.aging_report(conn)
            wl = report_service.win_loss_report(conn)
            eff = report_service.followup_effectiveness(conn)
        finally:
            conn.close()
        age_rows = "".join(
            f"<tr><td>{b['bucket']} days</td><td>{b['count']}</td>"
            f"<td>${b['amount_cents']/100:,.2f}</td></tr>"
            for b in aging["buckets"]
        )
        svc_rows = "".join(
            f"<tr><td>{s['segment']}</td><td>{s['sent']}</td><td>{s['accepted']}</td>"
            f"<td>{s['declined']}</td><td>{s['expired']}</td>"
            f"<td>{'—' if s['win_rate'] is None else f'{s['win_rate']:.1%}'}</td>"
            f"<td>${s['amount_won_cents']/100:,.2f}</td></tr>"
            for s in wl["by_service_type"]
        ) or '<tr><td colspan="7"><em>No data yet.</em></td></tr>'
        est_rows = "".join(
            f"<tr><td>{s['segment']}</td><td>{s['sent']}</td><td>{s['accepted']}</td>"
            f"<td>{s['declined']}</td><td>{s['expired']}</td>"
            f"<td>{'—' if s['win_rate'] is None else f'{s['win_rate']:.1%}'}</td>"
            f"<td>${s['amount_won_cents']/100:,.2f}</td></tr>"
            for s in wl["by_estimator"]
        ) or '<tr><td colspan="7"><em>No data yet.</em></td></tr>'
        dr_rows = "".join(
            f"<tr><td>{d['reason']}</td><td>{d['count']}</td></tr>"
            for d in wl["decline_reasons"]
        ) or '<tr><td colspan="2"><em>No declines recorded.</em></td></tr>'
        eff_rows = "".join(
            f"<tr><td>{b['followups']}</td><td>{b['estimates']}</td>"
            f"<td>{b['accepted']}</td>"
            f"<td>{'—' if b['accept_rate'] is None else f'{b['accept_rate']:.1%}'}</td></tr>"
            for b in eff["by_followup_count"]
        )
        med = (f"{eff['median_days_sent_to_accepted']} days"
               if eff["median_days_sent_to_accepted"] is not None else "—")
        body = f"""
<p>Computed from the database as of <code>{aging['as_of']}</code>.
Open estimates: <strong>{aging['open_count']}</strong>
(${aging['open_amount_cents']/100:,.2f} at stake).</p>
<div class="card"><h2>Aging — open estimates by days since sent</h2>
<table><tr><th>Bucket</th><th>Count</th><th>Value</th></tr>{age_rows}</table></div>
<div class="card"><h2>Win / loss by service type</h2>
<table><tr><th>Service</th><th>Sent</th><th>Won</th><th>Lost</th><th>Expired</th>
<th>Win rate</th><th>Won value</th></tr>{svc_rows}</table></div>
<div class="card"><h2>Win / loss by estimator</h2>
<table><tr><th>Estimator</th><th>Sent</th><th>Won</th><th>Lost</th><th>Expired</th>
<th>Win rate</th><th>Won value</th></tr>{est_rows}</table></div>
<div class="card"><h2>Decline reasons</h2>
<table><tr><th>Reason</th><th>Count</th></tr>{dr_rows}</table></div>
<div class="card"><h2>Follow-up effectiveness</h2>
<table><tr><th>Follow-ups queued</th><th>Estimates</th><th>Accepted</th>
<th>Accept rate</th></tr>{eff_rows}</table>
<p>Median days sent → accepted: <strong>{med}</strong>
(over {eff['accepted_with_timestamps']} accepted estimates with timestamps).</p></div>"""
        return _html(200, "Q02 — Follow-Up Reports", body)

    def q02_templates(self):
        conn = self._conn()
        try:
            templates = template_service.list_templates(conn)
        finally:
            conn.close()
        rows = "".join(
            f"<tr><td>{t['name']}</td><td>v{t['version']}</td>"
            f"<td>{t['subject']}</td><td><code>{t['variables']}</code></td>"
            f"<td>{t['created_at']}</td></tr>"
            for t in templates
        ) or '<tr><td colspan="5"><em>No templates.</em></td></tr>'
        body = f"""
<p>Templates are <strong>versioned</strong>: saving a template with an
existing name creates a new version and keeps the old ones. Use
<code>{{{{variable}}}}</code> placeholders; renders fail loudly on missing
variables (test with the API's <code>test-send</code> before changing a
live template).</p>
<div class="card"><h2>Active templates</h2>
<table><tr><th>Name</th><th>Version</th><th>Subject</th><th>Variables</th>
<th>Created</th></tr>{rows}</table></div>
<div class="card"><h2>New version</h2>
<form method="post" action="/project_q02/templates">
<label>Name <input name="name" placeholder="followup_step1" required></label>
<label>Subject <input name="subject" placeholder="Following up on {{estimate_id}}" required></label>
<label>Body <textarea name="body" rows="6" required></textarea></label>
<p><button type="submit">Save new version</button></p></form></div>"""
        return _html(200, "Q02 — Message Templates", body)

    def q02_template_submit(self, environ: dict):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        conn = self._conn()
        try:
            try:
                template_service.create_template(
                    conn, data.get("name", ""), data.get("subject", ""),
                    data.get("body", ""), actor="public-form",
                )
            except Exception as exc:
                conn.close()
                return _html(400, "Template save failed",
                             f'<p class="errors">{exc}</p>'
                             f'<p><a href="/project_q02/templates">Back</a></p>')
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return 303, [("Location", "/project_q02/templates")], b""

    # -- Q02: JSON API -----------------------------------------------------------
    def _q02_error(self, exc: Exception) -> tuple[int, list, bytes]:
        if isinstance(exc, KeyError):
            return _json(404, _error_envelope("not_found", str(exc)))
        if isinstance(exc, (InvalidTransition, TemplateRenderError, ValueError)):
            return _json(409, _error_envelope("action_rejected", str(exc)))
        if isinstance(exc, ValidationError):
            return _json(422, _error_envelope("validation_failed",
                                             "The submission failed validation.",
                                             exc.field_errors))
        raise exc

    def api_create_estimate(self, environ: dict):
        data = self._read_json(environ)
        key = self._idempotency_key(environ, data)
        data.pop("idempotency_key", None)
        conn = self._conn()
        try:
            try:
                result = estimate_service.create_with_idempotency(
                    conn, data, idempotency_key=key, actor="api",
                )
            except Exception as exc:
                conn.close()
                return self._q02_error(exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        status = 200 if result["replayed"] else result["status"]
        payload = dict(result["body"])
        if result["replayed"]:
            payload["replayed"] = True
        return _json(status, payload)

    def api_get_estimate(self, public_id: str):
        conn = self._conn()
        try:
            estimate = estimate_service.get_estimate(conn, public_id)
            if estimate is None:
                return _json(404, _error_envelope("not_found", f"No estimate {public_id!r}."))
            estimate["events"] = estimate_service.estimate_events(conn, estimate["id"])
            estimate["allowed_transitions"] = sorted(
                ESTIMATE_WORKFLOW.allowed_from(estimate["state"])
            )
        finally:
            conn.close()
        return _json(200, estimate)

    def api_transition_estimate(self, public_id: str, environ: dict):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            try:
                estimate = estimate_service.transition_estimate(
                    conn, public_id, data.get("to_state", ""),
                    data.get("actor", "api") or "api",
                    decline_reason=data.get("decline_reason"),
                    decline_note=data.get("decline_note"),
                )
            except Exception as exc:
                conn.close()
                return self._q02_error(exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return _json(200, {"public_id": estimate["public_id"], "state": estimate["state"]})

    def api_unsubscribe_estimate(self, public_id: str, environ: dict):
        data = self._read_json(environ)
        actor = data.get("actor", "api") or "api"
        conn = self._conn()
        try:
            try:
                estimate = estimate_service.set_unsubscribed(conn, public_id, actor)
            except Exception as exc:
                conn.close()
                return self._q02_error(exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return _json(200, {"public_id": estimate["public_id"],
                           "unsubscribed": estimate["unsubscribed"]})

    def api_list_templates(self):
        conn = self._conn()
        try:
            return _json(200, {"templates": template_service.list_templates(conn)})
        finally:
            conn.close()

    def api_create_template(self, environ: dict):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            try:
                template = template_service.create_template(
                    conn, data.get("name", ""), data.get("subject", ""),
                    data.get("body", ""), variables=data.get("variables"),
                    actor="api",
                )
            except Exception as exc:
                conn.close()
                return self._q02_error(exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return _json(201, {"name": template["name"], "version": template["version"]})

    def api_template_test_send(self, name: str, environ: dict):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            try:
                rendered = template_service.test_send(
                    conn, name, data.get("context", {}),
                    version=data.get("version"),
                )
            except Exception as exc:
                conn.close()
                return self._q02_error(exc)
        finally:
            conn.close()
        return _json(200, rendered)

    def api_list_rules(self):
        conn = self._conn()
        try:
            return _json(200, {"rules": cadence_service.list_rules(conn)})
        finally:
            conn.close()

    def api_replace_rules(self, environ: dict):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            try:
                rules = cadence_service.replace_rules(
                    conn, data.get("rules", []), actor="api",
                )
            except Exception as exc:
                conn.close()
                return self._q02_error(exc)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return _json(200, {"rules": rules})

    def api_cadence_run(self):
        conn = self._conn()
        try:
            result = cadence_service.run_cadence(conn)
        finally:
            conn.close()
        return _json(200, result)

    def api_cadence_flush(self):
        conn = self._conn()
        try:
            flushed = cadence_service.flush_outbox(conn)
        finally:
            conn.close()
        return _json(200, {"flushed": flushed})

    # -- Project Q03: HTML pages ----------------------------------------------
    def q03_page(self):
        conn = self._conn()
        try:
            report = rx_service.segment_report(conn)
            info = rx_service.rfm_module_info()
        finally:
            conn.close()
        seg_rows = "".join(
            f"<tr><td>{s['segment']}</td><td>{s['customers']}</td>"
            f"<td>{'—' if s['avg_dormancy'] is None else f'{s['avg_dormancy']:.3f}'}</td>"
            f"<td>{s['suppression_flags']}</td><td>{s['plan_steps']} steps</td></tr>"
            for s in report["segments"]
        )
        w = info["weights"]
        n = info["normalization"]
        body = f"""
<p>Past customers are scored for dormancy with a documented, deterministic
RFM formula, segmented, and worked through per-segment win-back sequences
into an idempotent outbox. <strong>All customer data is synthetic.</strong>
Suppression flags (do-not-contact, recent complaint, active job) are
honored absolutely. v1 sends nothing — a stub adapter writes a send log.</p>
<div class="card"><h2>Scoring (deterministic, documented)</h2>
<p><code>dormancy = {w['recency']:.2f} × recency_norm
+ {w['frequency']:.2f} × (1 − frequency_norm)
+ {w['monetary']:.2f} × (1 − monetary_norm)</code></p>
<p>recency window {n['recency_window_days']} days · frequency cap
{n['frequency_cap']} jobs · monetary cap ${n['monetary_cap_cents']/100:,.0f} ·
scorer <code>{info['scorer']}</code></p>
<p>Segments: {", ".join(f"{s['segment']} &lt; {s['score_below']}" for s in info['segments'])}</p>
<form method="post" action="/project_q03/score" style="display:inline">
<p><button type="submit">Score all customers</button></p></form>
<form method="post" action="/project_q03/winback-run" style="display:inline">
<p><button type="submit">Run win-back (queue due touches)</button></p></form></div>
<div class="card"><h2>Segments ({report['total_customers']} customers,
{report['unscored_customers']} unscored)</h2>
<table><tr><th>Segment</th><th>Customers</th><th>Avg dormancy</th>
<th>Suppression flags</th><th>Plan</th></tr>{seg_rows}</table>
<p><a href="/project_q03/segments">Segment detail</a> ·
<a href="/project_q03/outbox">Outbox</a> ·
<a href="/project_q03/attribution">Attribution</a> ·
<a href="/project_q03/suppression">Suppression audit</a></p></div>"""
        return _html(200, "Q03 — Customer Reactivation Engine", body)

    def q03_score_submit(self):
        conn = self._conn()
        try:
            rx_service.score_customers(conn, actor="web")
        finally:
            conn.close()
        return 303, [("Location", "/project_q03")], b""

    def q03_winback_submit(self):
        conn = self._conn()
        try:
            rx_service.run_winback(conn, actor="web")
        finally:
            conn.close()
        return 303, [("Location", "/project_q03/outbox")], b""

    def q03_segments(self):
        conn = self._conn()
        try:
            report = rx_service.segment_report(conn)
            lists = {s["segment"]: rx_service.list_customers(conn, segment=s["segment"])
                     for s in report["segments"]}
        finally:
            conn.close()
        cards = ""
        for s in report["segments"]:
            rows = "".join(
                f"<tr><td><code>{c['public_id']}</code></td>"
                f"<td>{c['customer_name']}</td>"
                f"<td>{c['dormancy_score']:.3f}</td>"
                f"<td>{'yes' if (c['do_not_contact'] or c['complaint_at'] or c['active_job']) else 'no'}</td></tr>"
                for c in lists[s["segment"]]
            ) or '<tr><td colspan="4"><em>No customers in this segment.</em></td></tr>'
            cards += f"""
<div class="card"><h2>{s['segment'].capitalize()} — {s['customers']} customers
(avg dormancy {s['avg_dormancy'] if s['avg_dormancy'] is not None else '—'},
{s['plan_steps']} win-back steps)</h2>
<table><tr><th>ID</th><th>Customer</th><th>Dormancy</th><th>Suppressed</th></tr>
{rows}</table></div>"""
        return _html(200, "Q03 — Segments", cards)

    def q03_outbox(self):
        conn = self._conn()
        try:
            rows = rx_service.outbox(conn)
            log = rx_service.send_log(conn)
        finally:
            conn.close()
        ob = "".join(
            f"<tr><td>{r['id']}</td><td><code>{r['idempotency_key']}</code></td>"
            f"<td>{r['segment']} step {r['step_index']}</td>"
            f"<td><span class='state'>{r['status']}</span></td>"
            f"<td>{r['scheduled_for']}</td></tr>"
            for r in rows
        ) or '<tr><td colspan="5"><em>Outbox is empty. Score customers, then run the win-back.</em></td></tr>'
        lg = "".join(
            f"<tr><td>{r['id']}</td><td>{r['outbox_id']}</td><td>{r['adapter']}</td>"
            f"<td>{r['status']}</td><td>{r['created_at']}</td></tr>"
            for r in log
        ) or '<tr><td colspan="5"><em>No sends logged yet.</em></td></tr>'
        body = f"""
<p>The outbox is <strong>not a messaging system</strong>: rows are rendered
win-back touches waiting on the send adapter. v1's adapter is a stub —
flushing writes a send-log row and delivers nothing. Suppression flags are
re-checked at flush time: a touch queued for a newly-suppressed customer
is marked <code>suppressed</code>, never sent.</p>
<div class="card"><h2>Outbox ({len(rows)} rows)</h2>
<table><tr><th>ID</th><th>Idempotency key</th><th>Plan step</th>
<th>Status</th><th>Scheduled</th></tr>{ob}</table>
<form method="post" action="/project_q03/outbox/flush">
<p><button type="submit">Flush outbox (stub adapter — sends nothing)</button></p></form></div>
<div class="card"><h2>Send log ({len(log)} rows)</h2>
<table><tr><th>ID</th><th>Outbox</th><th>Adapter</th><th>Status</th>
<th>At</th></tr>{lg}</table></div>"""
        return _html(200, "Q03 — Win-Back Outbox", body)

    def q03_flush_submit(self):
        conn = self._conn()
        try:
            rx_service.flush_outbox(conn, actor="web")
        finally:
            conn.close()
        return 303, [("Location", "/project_q03/outbox")], b""

    def q03_attribution(self, environ):
        query = dict(parse_qsl(environ.get("QUERY_STRING", "")))
        run_name = (query.get("run_name") or "").strip()
        window_start = query.get("window_start") or ""
        window_end = query.get("window_end") or ""
        report_html = "<p><em>Enter a holdout run name and window to compute the report.</em></p>"
        if run_name and window_start and window_end:
            conn = self._conn()
            try:
                r = attr_service.attribution_report(
                    conn, run_name, window_start=window_start, window_end=window_end
                )
            finally:
                conn.close()
            t, c = r["treated"], r["control"]
            ci = "—" if r["lift_ci95"] is None else f"[{r['lift_ci95'][0]}, {r['lift_ci95'][1]}]"
            report_html = f"""
<div class="card"><h2>Holdout report — {run_name}</h2>
<p><strong>{r['label']}</strong></p>
<table>
<tr><th>Group</th><th>Total</th><th>Returned</th><th>Return rate</th></tr>
<tr><td>Treated (touched)</td><td>{t['total']}</td><td>{t['returned']}</td>
<td>{'—' if t['return_rate'] is None else f"{t['return_rate']:.2%}"}</td></tr>
<tr><td>Control (holdout)</td><td>{c['total']}</td><td>{c['returned']}</td>
<td>{'—' if c['return_rate'] is None else f"{c['return_rate']:.2%}"}</td></tr>
</table>
<p>Lift (treated − control): <strong>{'—' if r['lift'] is None else f"{r['lift']:.2%}"}</strong>
· 95% CI {ci} · traced reactivation bookings: {t['attributed_bookings']}</p>
<p><em>Method: {r['method']}.</em></p></div>"""
        body = f"""
<p>Bookings are traced to reactivation touches (treated) vs. organic return
(control) via a deterministic holdout split. <strong>All data is synthetic:
the lift and interval below illustrate the arithmetic; they are never a
measured campaign result.</strong></p>
<div class="card"><h2>New holdout split</h2>
<form method="post" action="/project_q03/holdout">
<label>Run name <input name="run_name" value="demo-holdout-1"></label>
<label>Holdout % <input name="holdout_pct" value="20"></label>
<p><button type="submit">Create split over all scored customers</button></p></form></div>
<div class="card"><h2>Report</h2>
<form method="get" action="/project_q03/attribution">
<label>Run name <input name="run_name" value="{run_name}"></label>
<label>Window start (ISO) <input name="window_start" value="{window_start}"></label>
<label>Window end (ISO) <input name="window_end" value="{window_end}"></label>
<p><button type="submit">Compute report</button></p></form></div>
{report_html}"""
        return _html(200, "Q03 — Attribution", body)

    def q03_holdout_submit(self, environ):
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        run_name = (data.get("run_name") or "demo-holdout-1").strip()
        try:
            pct = float(data.get("holdout_pct") or 20) / 100.0
        except ValueError:
            pct = 0.20
        conn = self._conn()
        try:
            customers = rx_service.list_customers(conn, limit=10_000)
            scored = [c["id"] for c in customers if c.get("segment")]
            attr_service.split_holdout(conn, run_name, scored, holdout_pct=pct,
                                       actor="web")
        finally:
            conn.close()
        return 303, [("Location", f"/project_q03/attribution?run_name={run_name}")], b""

    def q03_suppression(self):
        conn = self._conn()
        try:
            audit = rx_service.suppression_audit(conn)
        finally:
            conn.close()
        rows = "".join(
            f"<tr><td><code>{c['public_id']}</code></td><td>{c['customer_name']}</td>"
            f"<td><span class='state'>{c['reason']}</span></td>"
            f"<td>{c['segment'] or '—'}</td>"
            f"<td>{', '.join(f'{k}:{v}' for k, v in c['outbox_by_status'].items()) or '—'}</td></tr>"
            for c in audit["suppressed_customers"]
        ) or '<tr><td colspan="5"><em>No suppressed customers.</em></td></tr>'
        ev = "".join(
            f"<li><code>{e['event_type']}</code> — customer {e['customer_id']} "
            f"({e['actor']}, {e['created_at']})</li>"
            for e in audit["events"][:50]
        ) or "<li><em>No suppression events yet.</em></li>"
        body = f"""
<p>Suppression is absolute: do-not-contact, a complaint within 180 days, or
an active job excludes a customer from every win-back step — checked at
queue time and re-checked at send time. This page is the audit trail:
every flagged customer, its reason, and the events.</p>
<div class="card"><h2>Suppressed customers ({audit['suppressed_count']})</h2>
<table><tr><th>ID</th><th>Customer</th><th>Reason</th><th>Segment</th>
<th>Outbox rows</th></tr>{rows}</table></div>
<div class="card"><h2>Suppression events</h2><ul class="timeline">{ev}</ul></div>"""
        return _html(200, "Q03 — Suppression Audit", body)

    # -- Project Q03: API ------------------------------------------------------
    def api_rx_create_customer(self, environ):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            customer = rx_service.create_customer(
                conn, customer_name=data.get("customer_name", ""), actor="api")
        finally:
            conn.close()
        return _json(201, customer)

    def api_rx_list_customers(self):
        conn = self._conn()
        try:
            return _json(200, {"customers": rx_service.list_customers(conn)})
        finally:
            conn.close()

    def api_rx_get_customer(self, public_id):
        conn = self._conn()
        try:
            customer = rx_service.get_customer_by_public_id(conn, public_id)
            if customer is None:
                return _json(404, _error_envelope("not_found", f"No customer {public_id!r}."))
            customer["jobs"] = rx_service.customer_jobs(conn, customer["id"])
            customer["touches"] = rx_service.touch_history(conn, customer["id"])
            customer["events"] = rx_service.customer_events(conn, customer["id"])
        finally:
            conn.close()
        return _json(200, customer)

    def api_rx_add_job(self, public_id, environ):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            customer = rx_service.get_customer_by_public_id(conn, public_id)
            if customer is None:
                return _json(404, _error_envelope("not_found", f"No customer {public_id!r}."))
            job = rx_service.add_job(
                conn, customer["id"],
                job_ref=data.get("job_ref", ""),
                service_type=data.get("service_type", ""),
                job_date=data.get("job_date", ""),
                amount_cents=data.get("amount_cents", 0),
                booking_source=data.get("booking_source", "organic"),
                actor="api",
            )
        finally:
            conn.close()
        return _json(201, job)

    def api_rx_suppression(self, public_id, environ):
        data = self._read_json(environ)
        conn = self._conn()
        try:
            customer = rx_service.get_customer_by_public_id(conn, public_id)
            if customer is None:
                return _json(404, _error_envelope("not_found", f"No customer {public_id!r}."))
            updated = rx_service.set_suppression(
                conn, customer["id"],
                do_not_contact=data.get("do_not_contact"),
                active_job=data.get("active_job"),
                active_job_ref=data.get("active_job_ref"),
                actor="api",
            )
        finally:
            conn.close()
        return _json(200, updated)

    def api_rx_complaint(self, public_id, environ):
        conn = self._conn()
        try:
            customer = rx_service.get_customer_by_public_id(conn, public_id)
            if customer is None:
                return _json(404, _error_envelope("not_found", f"No customer {public_id!r}."))
            updated = rx_service.record_complaint(conn, customer["id"], actor="api")
        finally:
            conn.close()
        return _json(200, updated)

    def api_rx_score(self):
        conn = self._conn()
        try:
            results = rx_service.score_customers(conn, actor="api")
        finally:
            conn.close()
        return _json(200, {"scored": [
            {"public_id": r["public_id"], "dormancy_score": r["dormancy_score"],
             "segment": r["segment"], "reasons": r["score_reasons"]}
            for r in results
        ]})

    def api_rx_winback(self):
        conn = self._conn()
        try:
            return _json(200, rx_service.run_winback(conn, actor="api"))
        finally:
            conn.close()

    def api_rx_segments(self):
        conn = self._conn()
        try:
            return _json(200, rx_service.segment_report(conn))
        finally:
            conn.close()

    def api_rx_outbox(self):
        conn = self._conn()
        try:
            rows = rx_service.outbox(conn)
            log = rx_service.send_log(conn)
        finally:
            conn.close()
        return _json(200, {"outbox": rows, "send_log": log})

    def api_rx_flush(self):
        conn = self._conn()
        try:
            flushed = rx_service.flush_outbox(conn, actor="api")
        finally:
            conn.close()
        return _json(200, {"flushed": flushed})

    def api_rx_holdout(self, environ):
        data = self._read_json(environ)
        run_name = str(data.get("run_name") or "").strip()
        holdout_pct = float(data.get("holdout_pct", 20)) / 100.0
        conn = self._conn()
        try:
            ids = data.get("customer_ids")
            if ids is None:
                customers = rx_service.list_customers(conn, limit=10_000)
                ids = [c["id"] for c in customers if c.get("segment")]
            assignments = attr_service.split_holdout(
                conn, run_name, ids, holdout_pct=holdout_pct, actor="api")
            groups = attr_service.holdout_groups(conn, run_name)
        finally:
            conn.close()
        return _json(200, {
            "run_name": run_name,
            "treated": len(groups["treated"]),
            "control": len(groups["control"]),
            "assignments": assignments,
        })

    def api_rx_attribution(self, environ):
        query = dict(parse_qsl(environ.get("QUERY_STRING", "")))
        run_name = (query.get("run_name") or "").strip()
        window_start = query.get("window_start") or ""
        window_end = query.get("window_end") or ""
        if not run_name or not window_start or not window_end:
            return _json(422, _error_envelope(
                "validation_failed",
                "Provide run_name, window_start, and window_end query parameters."))
        conn = self._conn()
        try:
            report = attr_service.attribution_report(
                conn, run_name, window_start=window_start, window_end=window_end)
        finally:
            conn.close()
        return _json(200, report)

    def api_rx_suppression_audit(self):
        conn = self._conn()
        try:
            return _json(200, rx_service.suppression_audit(conn))
        finally:
            conn.close()

    def api_rx_scoring_info(self):
        return _json(200, rx_service.rfm_module_info())

    def api_q02_outbox(self):
        conn = self._conn()
        try:
            rows = cadence_service.outbox(conn)
            log = cadence_service.send_log(conn)
        finally:
            conn.close()
        return _json(200, {"outbox": rows, "send_log": log})

    def api_q02_aging(self):
        conn = self._conn()
        try:
            return _json(200, report_service.aging_report(conn))
        finally:
            conn.close()

    def api_q02_win_loss(self):
        conn = self._conn()
        try:
            return _json(200, report_service.win_loss_report(conn))
        finally:
            conn.close()

    def api_q02_effectiveness(self):
        conn = self._conn()
        try:
            return _json(200, report_service.followup_effectiveness(conn))
        finally:
            conn.close()

    def _handle_validation_error(self, exc: ValidationError, environ: dict):
        path = environ.get("PATH_INFO", "")
        ctype = environ.get("CONTENT_TYPE", "")
        if path.startswith("/api/") or "json" in ctype:
            return _json(422, _error_envelope("validation_failed",
                                             "The submission failed validation.",
                                             exc.field_errors))
        if path.startswith("/project02"):
            data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
            _, headers, body = self.p02_form_page(errors=exc.field_errors, values=data)
            return 422, headers, body
        if path.startswith("/project_q01"):
            data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
            _, headers, body = self.q01_form_page(errors=exc.field_errors, values=data)
            return 422, headers, body
        if path.startswith("/project_q02"):
            data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
            _, headers, body = self.q02_form_page(errors=exc.field_errors, values=data)
            return 422, headers, body
        # HTML form: re-render with errors and the user's values preserved.
        data = dict(parse_qsl(self._read_body(environ).decode("utf-8"), keep_blank_values=True))
        _, headers, body = self.project_page(errors=exc.field_errors, values=data)
        return 422, headers, body


def create_app(settings: Optional[Settings] = None) -> App:
    from .config import load_settings
    return App(settings or load_settings())
