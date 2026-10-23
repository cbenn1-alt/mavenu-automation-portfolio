"""WSGI web application: portfolio hub + Project 01 pages and JSON API.

Standard library only (wsgiref-style callable). No framework, no assets,
no external requests — the whole UI is rendered server-side.
"""
from __future__ import annotations

import html
import json
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
<a href="/project_q06/pairs">Q06 Pairs</a><a href="/project_q06/merges">Q06 Merges</a><a href="/project_q10">Q10</a>
<a href="/project_q10/dead-letters">Q10 Dead-letters</a></nav>
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
        return _json(404, _error_envelope("not_found", f"No route for {method} {path}"))

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
