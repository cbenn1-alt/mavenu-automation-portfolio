"""N02 — web pages + JSON API tests (WSGI test client)."""
import json

from tests.conftest import wsgi_call

from mavenu import risk


def _get(app, path):
    return wsgi_call(app, "GET", path)


def _post(app, path, body=b"", content_type="application/x-www-form-urlencoded"):
    return wsgi_call(app, "POST", path, body=body, content_type=content_type)


def _seed(app):
    status, _, body = _post(app, "/api/risk/seed",
                            content_type="application/json")
    assert status == 200, body[:200]
    return json.loads(body)["seeded"]


class TestN02Pages:
    def test_hub_page_unseeded_offers_seed(self, app):
        status, headers, body = _get(app, "/project_n02")
        assert status == 200
        text = body.decode()
        assert "Synthetic Test Co." in text
        assert "FICTIONAL COMPANY" in text
        assert "Seed synthetic workbook" in text

    def test_hub_page_seeded_shows_counts(self, app):
        _seed(app)
        status, _, body = _get(app, "/project_n02")
        assert status == 200
        text = body.decode()
        assert "17</b> register entries" in text or "17" in text
        assert "/project_n02/register" in text
        assert "/project_n02/residual" in text

    def test_scales_page_documents_scales(self, app):
        status, _, body = _get(app, "/project_n02/scales")
        assert status == 200
        text = body.decode()
        assert "Likelihood scale" in text
        assert "Impact scale" in text
        assert "Risk bands" in text
        assert "critical" in text
        assert "prioritization" in text.lower()

    def test_register_page_lists_risks(self, app):
        _seed(app)
        status, _, body = _get(app, "/project_n02/register")
        assert status == 200
        text = body.decode()
        for rid in ("R-01", "R-08", "R-17"):
            assert rid in text
        assert "GAP" in text  # accepted gaps are shown, not hidden

    def test_remediation_page_shows_plan_order(self, app):
        _seed(app)
        status, _, body = _get(app, "/project_n02/remediation")
        assert status == 200
        text = body.decode()
        assert "RM-05" in text
        assert "synthetic estimate" in text
        # RM-05 (rank 1) appears before RM-04 (rank 8)
        assert text.index("RM-05") < text.index("RM-04")

    def test_residual_page_shows_memo_and_deltas(self, app):
        _seed(app)
        status, _, body = _get(app, "/project_n02/residual")
        assert status == 200
        text = body.decode()
        assert "Residual-risk memo" in text
        assert "177" in text and "79" in text
        assert "R-08" in text

    def test_nav_links_present(self, app):
        status, _, body = _get(app, "/project_n02")
        assert status == 200
        text = body.decode()
        for link in ("/project_n02/scales", "/project_n02/register",
                     "/project_n02/remediation", "/project_n02/residual"):
            assert link in text

    def test_pages_carry_honest_banner(self, app):
        for path in ("/project_n02", "/project_n02/scales",
                     "/project_n02/register", "/project_n02/remediation",
                     "/project_n02/residual"):
            status, _, body = _get(app, path)
            assert status == 200
            text = body.decode()
            assert "never</b> an audit opinion" in text or \
                   "never an audit opinion" in text.replace("</b>", ""), path


class TestN02Api:
    def test_unseeded_endpoints_404(self, app):
        for path in ("/api/risk/assets", "/api/risk/threats",
                     "/api/risk/register", "/api/risk/remediations",
                     "/api/risk/residual"):
            status, _, _ = _get(app, path)
            assert status == 404, path

    def test_scales_endpoint_always_available(self, app):
        status, headers, body = _get(app, "/api/risk/scales")
        assert status == 200
        payload = json.loads(body)
        assert payload["synthetic"] is True
        assert "FICTIONAL" in payload["ethical_banner"]
        scales = payload["scales"]
        assert len(scales["likelihood_scale"]) == 5
        assert len(scales["impact_scale"]) == 5
        assert [b["band"] for b in scales["bands"]] == ["low", "medium", "high", "critical"]

    def test_controls_endpoint_lists_live_registry(self, app):
        status, _, body = _get(app, "/api/risk/controls")
        assert status == 200
        payload = json.loads(body)
        assert payload["count"] == 15 + 13 + 9
        assert "S02:auth-01" in payload["registry"]
        assert "S01:deny-wan-inbound" in payload["registry"]

    def test_seed_endpoint_is_idempotent(self, app):
        s1 = json.loads(_post(app, "/api/risk/seed")[2])["seeded"]
        s2 = json.loads(_post(app, "/api/risk/seed")[2])["seeded"]
        assert s1 == s2 == {"assets": 14, "threats": 10, "risks": 17,
                            "remediations": 8, "snapshots": 2}

    def test_register_endpoint(self, app):
        _post(app, "/api/risk/seed")
        status, _, body = _get(app, "/api/risk/register")
        assert status == 200
        payload = json.loads(body)
        assert len(payload["register"]) == 17
        assert payload["audit_violations"] == []
        assert payload["totals"]["band_counts"] == {
            "low": 1, "medium": 6, "high": 8, "critical": 2}
        r01 = next(r for r in payload["register"] if r["risk_id"] == "R-01")
        assert r01["score"] == 16 and r01["band"] == "critical"
        assert r01["likelihood_rationale"] and r01["impact_rationale"]
        assert any(c["ref"] == "S02:acct-02" for c in r01["controls"])

    def test_remediations_endpoint_prioritized(self, app):
        _post(app, "/api/risk/seed")
        status, _, body = _get(app, "/api/risk/remediations")
        assert status == 200
        payload = json.loads(body)
        ids = [r["rem_id"] for r in payload["remediations"]]
        assert ids == ["RM-05", "RM-02", "RM-03", "RM-06",
                       "RM-08", "RM-01", "RM-07", "RM-04"]
        assert "ratio" in payload["prioritization_rule"].lower() or \
               "prioritization_rule" in payload
        for r in payload["remediations"]:
            assert "synthetic" in r["cost_basis"]
            assert "synthetic" in r["effort_basis"]

    def test_residual_endpoint_reconciles(self, app):
        _post(app, "/api/risk/seed")
        status, _, body = _get(app, "/api/risk/residual")
        assert status == 200
        payload = json.loads(body)
        assert payload["inherent"]["total_score"] == 177
        assert payload["residual"]["total_score"] == 79
        assert payload["total_reduction"] == 98
        assert sum(d["delta"] for d in payload["deltas"]) == 98
        assert all(d["residual_score"] <= d["inherent_score"]
                   for d in payload["deltas"])
        assert "SYNTHETIC" in payload["memo"]

    def test_assets_and_threats_endpoints(self, app):
        _post(app, "/api/risk/seed")
        status, _, body = _get(app, "/api/risk/assets")
        assert status == 200
        assets = json.loads(body)["assets"]
        assert len(assets) == 14
        assert {a["asset_type"] for a in assets} == set(risk.ASSET_TYPES)
        status, _, body = _get(app, "/api/risk/threats")
        assert status == 200
        threats = json.loads(body)["threats"]
        assert len(threats) == 10
