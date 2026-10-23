"""Q02 template engine tests: versioning, rendering, validation, performance.

All template content below is synthetic fixture text.
"""
import time
from datetime import datetime, timezone

import pytest

from mavenu import templates as tp
from mavenu.validation import ValidationError

T0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)

CTX = {
    "estimate_id": "EST-000001",
    "customer_name": "Acme Test Co",
    "service_type": "hvac",
    "amount": "$1,250.00",
    "estimator": "Rosa",
}


def test_create_template_extracts_variables(conn):
    t = tp.create_template(
        conn, "hello", "Hi {{customer_name}}", "Estimate {{estimate_id}} is {{amount}}.",
        actor="test", now=T0,
    )
    assert t["version"] == 1
    assert t["is_active"] == 1
    import json
    assert sorted(json.loads(t["variables"])) == ["amount", "customer_name", "estimate_id"]


def test_new_version_deactivates_old_and_preserves_history(conn):
    tp.create_template(conn, "nudge", "v1 {{customer_name}}", "body v1", now=T0)
    v2 = tp.create_template(conn, "nudge", "v2 {{customer_name}}", "body v2 {{amount}}", now=T0)
    assert v2["version"] == 2
    history = tp.template_history(conn, "nudge")
    assert [h["version"] for h in history] == [2, 1]
    assert [h["is_active"] for h in history] == [1, 0]
    # Old version still renders when pinned.
    rendered = tp.render_template(conn, "nudge", {**CTX, "amount": "$9"}, version=1)
    assert rendered["version"] == 1
    assert rendered["subject"] == "v1 Acme Test Co"


def test_render_substitutes_every_variable(conn):
    tp.create_template(conn, "full", "Estimate {{estimate_id}} — {{amount}}",
                       "{{customer_name}}, {{estimator}} here re: {{service_type}}.", now=T0)
    r = tp.render_template(conn, "full", CTX)
    assert r["subject"] == "Estimate EST-000001 — $1,250.00"
    assert r["body"] == "Acme Test Co, Rosa here re: hvac."
    assert "{{" not in r["subject"] and "{{" not in r["body"]


def test_render_fails_on_missing_variable(conn):
    tp.create_template(conn, "needs_all", "{{customer_name}}", "{{amount}} owed.", now=T0)
    with pytest.raises(tp.TemplateRenderError) as exc:
        tp.render_template(conn, "needs_all", {"customer_name": "Acme Test Co"})
    assert "amount" in str(exc.value)


def test_render_fails_on_unknown_template(conn):
    with pytest.raises(tp.TemplateRenderError):
        tp.render_template(conn, "does_not_exist", CTX)


def test_test_send_renders_without_queueing(conn):
    tp.create_template(conn, "ping", "Hi {{customer_name}}", "Amt {{amount}}.", now=T0)
    before = conn.execute("SELECT COUNT(*) c FROM estimate_outbox").fetchone()["c"]
    r = tp.test_send(conn, "ping", CTX)
    after = conn.execute("SELECT COUNT(*) c FROM estimate_outbox").fetchone()["c"]
    assert r["subject"] == "Hi Acme Test Co"
    assert before == after == 0


def test_test_send_fails_on_missing_variable(conn):
    tp.create_template(conn, "ping2", "Hi {{customer_name}}", "Amt {{amount}}.", now=T0)
    with pytest.raises(tp.TemplateRenderError):
        tp.test_send(conn, "ping2", {"customer_name": "Acme Test Co"})


def test_create_rejects_bad_names(conn):
    for bad in ("", "has space", "has-dash", "x" * 81):
        with pytest.raises(ValidationError) as exc:
            tp.create_template(conn, bad, "s", "b")
        assert "name" in exc.value.field_errors


def test_create_rejects_empty_subject_and_body(conn):
    with pytest.raises(ValidationError) as exc:
        tp.create_template(conn, "ok_name", "  ", "body")
    assert "subject" in exc.value.field_errors
    with pytest.raises(ValidationError) as exc:
        tp.create_template(conn, "ok_name", "subject", "   ")
    assert "body" in exc.value.field_errors


def test_create_rejects_bad_variable_list(conn):
    with pytest.raises(ValidationError) as exc:
        tp.create_template(conn, "v", "s {{x}}", "b", variables=["not a var!"])
    assert "variables" in exc.value.field_errors


def test_list_templates_returns_active_versions_only(conn):
    tp.create_template(conn, "a_one", "s {{x}}", "b", now=T0)
    tp.create_template(conn, "a_one", "s2 {{x}}", "b2", now=T0)
    names = {t["name"]: t["version"] for t in tp.list_templates(conn)}
    assert names["a_one"] == 2
    # seeded defaults are present too
    assert names["followup_step1"] == 1


def test_render_p95_under_2ms(conn):
    tp.create_template(
        conn, "perf", "Following up on {{estimate_id}} ({{amount}})",
        "Hi {{customer_name}}, {{estimator}} here about your {{service_type}} estimate.",
        now=T0,
    )
    durations = []
    for _ in range(2000):
        start = time.perf_counter()
        tp.render_template(conn, "perf", CTX)
        durations.append((time.perf_counter() - start) * 1000.0)
    durations.sort()
    p95 = durations[int(0.95 * len(durations))]
    assert p95 < 2.0, f"render p95 {p95:.3f} ms exceeds 2 ms budget"
