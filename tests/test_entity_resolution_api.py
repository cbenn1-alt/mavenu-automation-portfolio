"""Project Q06 — API + page tests (WSGI, stdlib only). All data synthetic."""
import io
import json

from tests.conftest import wsgi_call
from tests.test_entity_resolution import A_ROWS, B_ROWS, make_csv


def wsgi_call_qs(app, method, path, query="", body=b"", content_type="application/json"):
    """wsgi_call variant that sets QUERY_STRING (the conftest client drops it)."""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
        "wsgi.url_scheme": "http",
        "SERVER_NAME": "test",
        "SERVER_PORT": "80",
    }
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    out = b"".join(app(environ, start_response))
    return int(captured["status"].split()[0]), captured["headers"], out


def api(app, method, path, payload=None, query=""):
    body = b""
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    return wsgi_call_qs(app, method, path, query=query, body=body)


def load(app):
    """Upload two sources and run the pipeline through the API."""
    status, _, body = api(app, "POST", "/api/entity-resolution/sources/upload",
                          {"label": "sheet-a", "source_kind": "spreadsheet",
                           "csv": make_csv(A_ROWS[:4]), "actor": "api-test"})
    assert status == 201, body
    status, _, body = api(app, "POST", "/api/entity-resolution/sources/upload",
                          {"label": "form-b", "source_kind": "form",
                           "csv": make_csv(B_ROWS[:4]), "actor": "api-test"})
    assert status == 201, body
    status, _, body = api(app, "POST", "/api/entity-resolution/run",
                          {"actor": "api-test"})
    assert status == 200, body
    return json.loads(body)


def test_api_upload_and_run(app):
    stats = load(app)
    assert stats["pairs_total"] == 4
    assert stats["band_match"] == 4
    assert stats["proposals_created"] == 4
    assert stats["reduction_ratio"] > 0.8


def test_api_upload_rejects_bad_kind(app):
    status, _, body = api(app, "POST", "/api/entity-resolution/sources/upload",
                          {"label": "x", "source_kind": "nope", "csv": make_csv(A_ROWS[:1])})
    assert status == 409
    assert "source_kind" in body.decode()


def test_api_upload_rejects_missing_columns(app):
    status, _, body = api(app, "POST", "/api/entity-resolution/sources/upload",
                          {"label": "x", "source_kind": "spreadsheet", "csv": "name,phone\nA,1\n"})
    assert status == 409
    assert "missing required columns" in body.decode()


def test_api_stats(app):
    load(app)
    status, _, body = api(app, "GET", "/api/entity-resolution/stats")
    assert status == 200
    snap = json.loads(body)
    assert snap["sources"] == 2
    assert snap["active_contacts"] == 8
    assert snap["bands"] == {"match": 4, "review": 0, "no_match": 0}


def test_api_pairs_filter_band(app):
    load(app)
    status, _, body = api(app, "GET", "/api/entity-resolution/pairs", query="band=match")
    assert status == 200
    pairs = json.loads(body)["pairs"]
    assert len(pairs) == 4
    assert all(p["band"] == "match" for p in pairs)
    status, _, body = api(app, "GET", "/api/entity-resolution/pairs", query="band=bogus")
    assert status == 409


def test_api_pair_detail(app):
    load(app)
    status, _, body = api(app, "GET", "/api/entity-resolution/pairs", query="band=match")
    pair_id = json.loads(body)["pairs"][0]["id"]
    status, _, body = api(app, "GET", f"/api/entity-resolution/pairs/{pair_id}")
    assert status == 200
    detail = json.loads(body)
    assert detail["contact_a"]["id"] != detail["contact_b"]["id"]
    assert "components" in json.loads(detail["score_detail_json"])


def test_api_pair_not_found(app):
    load(app)
    status, _, _ = api(app, "GET", "/api/entity-resolution/pairs/99999")
    assert status == 409


def test_api_full_human_merge_loop(app):
    """propose (not needed — auto) -> confirm -> audit -> reverse, all via API."""
    load(app)
    status, _, body = api(app, "GET", "/api/entity-resolution/proposals",
                           query="state=proposed")
    assert status == 200
    proposals = json.loads(body)["proposals"]
    assert len(proposals) == 4
    pid = proposals[0]["id"]

    # system actor is rejected: the human stays in the loop
    status, _, body = api(app, "POST", f"/api/entity-resolution/proposals/{pid}/confirm",
                          {"actor": "system"})
    assert status == 409
    assert "human actor" in body.decode()

    # human confirms
    status, _, body = api(app, "POST", f"/api/entity-resolution/proposals/{pid}/confirm",
                          {"actor": "api-reviewer", "note": "verified by hand"})
    assert status == 200, body
    result = json.loads(body)
    assert result["state"] == "confirmed"
    assert result["audit_id"] > 0

    # audit view shows before/after
    status, _, body = api(app, "GET", f"/api/entity-resolution/proposals/{pid}/audit")
    assert status == 200
    audit = json.loads(body)
    assert audit["merged_by"] == "api-reviewer"
    assert audit["reversed_at"] is None
    assert len(audit["field_provenance"]) == 5

    # proposal detail carries the field plan + audit summary
    status, _, body = api(app, "GET", f"/api/entity-resolution/proposals/{pid}")
    assert status == 200
    assert json.loads(body)["state"] == "confirmed"

    # human reverses
    status, _, body = api(app, "POST", f"/api/entity-resolution/proposals/{pid}/reverse",
                          {"actor": "api-reviewer"})
    assert status == 200
    assert json.loads(body)["state"] == "reversed"
    status, _, body = api(app, "GET", f"/api/entity-resolution/proposals/{pid}/audit")
    assert json.loads(body)["reversed_by"] == "api-reviewer"


def test_api_reject_proposal(app):
    load(app)
    status, _, body = api(app, "GET", "/api/entity-resolution/proposals",
                           query="state=proposed")
    pid = json.loads(body)["proposals"][0]["id"]
    status, _, body = api(app, "POST", f"/api/entity-resolution/proposals/{pid}/reject",
                          {"actor": "api-reviewer", "note": "different people"})
    assert status == 200
    assert json.loads(body)["state"] == "rejected"


def test_api_propose_review_pair(app):
    """Human proposes a merge for a review-band pair through the API."""
    # twins fixture -> review band, no automatic proposal
    from tests.test_entity_resolution import A_ROWS as AR, B_ROWS as BR
    twins_a = [r for r in AR if r[0] == "Emma Carter"]
    twins_b = [r for r in BR if r[0] == "Emily Carter"]
    status, _, _ = api(app, "POST", "/api/entity-resolution/sources/upload",
                       {"label": "t1", "source_kind": "spreadsheet",
                        "csv": make_csv(twins_a), "actor": "api-test"})
    assert status == 201
    status, _, _ = api(app, "POST", "/api/entity-resolution/sources/upload",
                       {"label": "t2", "source_kind": "form",
                        "csv": make_csv(twins_b), "actor": "api-test"})
    assert status == 201
    status, _, _ = api(app, "POST", "/api/entity-resolution/run", {"actor": "api-test"})
    assert status == 200
    status, _, body = api(app, "GET", "/api/entity-resolution/pairs", query="band=review")
    pairs = json.loads(body)["pairs"]
    assert len(pairs) == 1
    pair_id = pairs[0]["id"]

    status, _, body = api(app, "POST", "/api/entity-resolution/proposals",
                          {"pair_id": pair_id, "actor": "api-reviewer",
                           "note": "owner confirmed same person"})
    assert status == 201, body
    pid = json.loads(body)["proposal_id"]
    status, _, body = api(app, "POST", f"/api/entity-resolution/proposals/{pid}/confirm",
                          {"actor": "api-reviewer"})
    assert status == 200


def test_api_propose_no_match_pair_rejected(app):
    load(app)
    # all pairs here are match-band; proposing again hits the duplicate guard
    status, _, body = api(app, "GET", "/api/entity-resolution/pairs", query="band=match")
    pair_id = json.loads(body)["pairs"][0]["id"]
    status, _, body = api(app, "POST", "/api/entity-resolution/proposals",
                          {"pair_id": pair_id, "actor": "api-reviewer"})
    assert status == 409
    assert "already has proposal" in body.decode()


def test_pages_render(app):
    load(app)
    for path in ("/project_q06", "/project_q06/pairs",
                 "/project_q06/pairs?band=match", "/project_q06/merges",
                 "/project_q06/merges?state=proposed"):
        base, _, qs = path.partition("?")
        status, headers, body = wsgi_call_qs(app, "GET", base, query=qs)
        assert status == 200, path
        assert b"SYNTHETIC DEMO DATA" in body
    # pair + proposal detail pages
    status, _, body = api(app, "GET", "/api/entity-resolution/pairs", query="band=match")
    pair_id = json.loads(body)["pairs"][0]["id"]
    status, _, body = wsgi_call_qs(app, "GET", f"/project_q06/pairs/{pair_id}")
    assert status == 200
    status, _, body = api(app, "GET", "/api/entity-resolution/proposals",
                           query="state=proposed")
    pid = json.loads(body)["proposals"][0]["id"]
    status, _, body = wsgi_call_qs(app, "GET", f"/project_q06/merges/{pid}")
    assert status == 200
    assert b"Human decision required" in body
