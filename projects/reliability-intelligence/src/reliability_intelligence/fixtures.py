"""V6 read-only, version-pinned synthetic fixtures and scripted reviewer-role inputs.

All paths are hard-coded under the checked-in repository fixtures directory.
Manifest SHA-1 values are *Git blob object IDs* (including Git's blob header),
not plain-file SHA-1 hashes. They protect against accidental fixture changes,
but are not a digital signature or a substitute for secure supply-chain review.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures"
FIXTURE_SET_ID = "SYN-RI-V5-20261107-A"
ASSET_ID = re.compile(r"SYN-ASSET-[0-9]{3}\Z")
CASE_ID = re.compile(r"SYN-CASE-[0-9]{3}\Z")
WORK_ORDER_ID = re.compile(r"SYN-WO-[0-9]{3}\Z")
EVIDENCE_ID = re.compile(r"SYN-EV-[0-9]{3}\Z")
CASE_FIELDS = frozenset((
    "case_id", "asset_id", "work_order_ref", "occurred_at_utc", "failure_code",
    "downtime_hours", "repair_cost_usd", "evidence_refs", "synthetic", "review_state",
))
ASSET_FIELDS = frozenset(("asset_id", "asset_class", "cohort", "synthetic"))
ALLOWED_CODES = frozenset((
    "bearing_wear", "belt_slip", "seal_leak", "sensor_fault", "motor_trip", "valve_stick",
))
ALLOWED_CLASSES = frozenset((
    "bearing_drive", "belt_conveyor", "transfer_pump",
    "sensor_module", "electric_motor", "control_valve",
))
REFERENCE_LABELS = frozenset((
    "single_event", "repeat_history_candidate", "missing_evidence",
))


class InvalidFixture(ValueError):
    """The local fixture is missing, altered, mislabeled or malformed."""


def _git_blob_id(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def _load_json_file(path: Path, expected_blob_id: str) -> dict[str, Any]:
    if not isinstance(expected_blob_id, str) or not re.fullmatch("[0-9a-f]{40}", expected_blob_id):
        raise InvalidFixture("Invalid fixture integrity reference")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise InvalidFixture("Fixture file unavailable") from error
    if not raw or len(raw) > 65536 or _git_blob_id(raw) != expected_blob_id:
        raise InvalidFixture("Fixture content integrity mismatch")
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidFixture("Malformed fixture JSON") from error
    if not isinstance(data, dict):
        raise InvalidFixture("Fixture root must be an object")
    return data


def _manifest() -> dict[str, Any]:
    try:
        manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidFixture("Fixture manifest unavailable") from error
    if not isinstance(manifest, dict):
        raise InvalidFixture("Fixture manifest malformed")
    required = {
        "fixture_set_id": FIXTURE_SET_ID,
        "manifest_schema_version": "1.0.0",
        "synthetic_only": True,
        "customer_data_used": False,
        "production_authorized": False,
        "independent_domain_validation": False,
        "case_file": "cases.json",
        "reference_labels_file": "reference_labels.json",
        "assets_count": 6,
        "cases_count": 12,
        "demo_review_script_file": "demo_review_script.json",
        "source_systems": [],
    }
    for key, expected in required.items():
        if key not in manifest or type(manifest[key]) is not type(expected) or manifest[key] != expected:
            raise InvalidFixture("Invalid manifest field: " + key)
    for name in ("case_git_blob_sha1", "reference_labels_git_blob_sha1",
                 "demo_review_script_git_blob_sha1"):
        value = manifest.get(name)
        if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{40}", value):
            raise InvalidFixture("Missing version-pinned file digest")
    return manifest


def _ident(value: Any, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _number(value: Any, upper: float) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= upper


def validate_fixture_data(dataset: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Fail closed for unsafe IDs, bad semantics, duplicates and record drift."""
    if not isinstance(dataset, dict) or set(dataset) != {
        "fixture_set_id", "synthetic_only", "source_system", "data_kind", "assets", "records"
    }:
        raise InvalidFixture("Unexpected fixture dataset fields")
    if (dataset["fixture_set_id"] != FIXTURE_SET_ID or dataset["synthetic_only"] is not True
        or dataset["source_system"] != "NONE"
        or dataset["data_kind"] != "artificial_illustrative_maintenance_records"):
        raise InvalidFixture("Non-synthetic or inconsistent fixture source")
    assets = dataset["assets"]
    records = dataset["records"]
    if not isinstance(assets, list) or not isinstance(records, list):
        raise InvalidFixture("Assets and records must be lists")
    if len(assets) != manifest["assets_count"] or len(records) != manifest["cases_count"]:
        raise InvalidFixture("Fixture count does not match manifest")
    asset_ids: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict) or set(asset) != ASSET_FIELDS:
            raise InvalidFixture("Unexpected asset fields")
        if not _ident(asset["asset_id"], ASSET_ID) or asset["asset_id"] in asset_ids:
            raise InvalidFixture("Invalid or duplicate asset ID")
        if asset["synthetic"] is not True:
            raise InvalidFixture("Asset not explicitly marked synthetic")
        if asset["asset_class"] not in ALLOWED_CLASSES:
            raise InvalidFixture("Unrecognized asset class")
        if asset["cohort"] not in {"Assembly Test Line", "Utility Test Zone", "Mock Workshop"}:
            raise InvalidFixture("Non-synthetic asset cohort")
        asset_ids.add(asset["asset_id"])
    case_ids: set[str] = set()
    wo_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != CASE_FIELDS:
            raise InvalidFixture("Unexpected record fields")
        cid = record["case_id"]
        wid = record["work_order_ref"]
        if not _ident(cid, CASE_ID) or cid in case_ids:
            raise InvalidFixture("Invalid or duplicate case ID")
        if not _ident(wid, WORK_ORDER_ID) or wid in wo_ids:
            raise InvalidFixture("Invalid or duplicate work-order reference")
        if record["asset_id"] not in asset_ids:
            raise InvalidFixture("Unknown asset reference")
        if record["synthetic"] is not True or record["review_state"] != "fixture_only":
            raise InvalidFixture("Attempt to include active or non-synthetic record")
        if record["failure_code"] not in ALLOWED_CODES:
            raise InvalidFixture("Invalid failure code")
        value = record["occurred_at_utc"]
        if not isinstance(value, str):
            raise InvalidFixture("Missing UTC event timestamp")
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as error:
            raise InvalidFixture("Malformed UTC timestamp") from error
        if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
            raise InvalidFixture("Noncanonical UTC timestamp")
        if not _number(record["downtime_hours"], 240) or not _number(record["repair_cost_usd"], 1000000):
            raise InvalidFixture("Unbounded or invalid illustrative numeric field")
        refs = record["evidence_refs"]
        if not isinstance(refs, list) or len(refs) > 3 or len(refs) != len(set(str(x) for x in refs)):
            raise InvalidFixture("Invalid evidence reference array")
        if not all(_ident(ref, EVIDENCE_ID) for ref in refs):
            raise InvalidFixture("Non-synthetic evidence reference")
        case_ids.add(cid)
        wo_ids.add(wid)
    return dataset


def load_fixture_set() -> dict[str, Any]:
    """Verify manifest and Git-object integrity, then validate every synthetic record."""
    manifest = _manifest()
    dataset = _load_json_file(FIXTURE_DIR / "cases.json", manifest["case_git_blob_sha1"])
    return validate_fixture_data(dataset, manifest)


def validate_reference_labels(labels: dict[str, Any], dataset: dict[str, Any]) -> dict[str, Any]:
    """Internal-only demonstration labels; never used to decide a live case."""
    if not isinstance(labels, dict) or set(labels) != {
        "fixture_set_id", "synthetic_only", "labels_authored_for_demonstration",
        "independently_validated", "records"
    }:
        raise InvalidFixture("Malformed reference-label set")
    if (labels["fixture_set_id"] != FIXTURE_SET_ID or labels["synthetic_only"] is not True
        or labels["labels_authored_for_demonstration"] is not True
        or labels["independently_validated"] is not False):
        raise InvalidFixture("Reference-label provenance is invalid")
    records = labels["records"]
    if not isinstance(records, list) or len(records) != len(dataset["records"]):
        raise InvalidFixture("Reference-label count mismatch")
    source_ids = {r["case_id"] for r in dataset["records"]}
    seen: set[str] = set()
    for row in records:
        if not isinstance(row, dict) or set(row) != {"case_id", "expected_review_label", "synthetic"}:
            raise InvalidFixture("Reference label has unexpected fields")
        cid = row["case_id"]
        if (cid not in source_ids or cid in seen or row["synthetic"] is not True
            or row["expected_review_label"] not in REFERENCE_LABELS):
            raise InvalidFixture("Invalid or duplicate reference label")
        seen.add(cid)
    if seen != source_ids:
        raise InvalidFixture("Reference labels do not cover all cases")
    return labels


def load_reference_labels() -> dict[str, Any]:
    """For isolated tests only. NOT imported by services, API, or UI."""
    dataset = load_fixture_set()
    manifest = _manifest()
    labels = _load_json_file(FIXTURE_DIR / "reference_labels.json",
                             manifest["reference_labels_git_blob_sha1"])
    return validate_reference_labels(labels, dataset)


SCRIPT_DISPOSITIONS = frozenset(("acknowledge", "investigate_history", "request_evidence", "defer"))
SCRIPT_REASONS = {
    "acknowledge": "routine_synthetic_review",
    "investigate_history": "repeat_history_flag",
    "request_evidence": "missing_evidence_reference",
    "defer": "further_demo_review",
}
REVIEWER_ID = re.compile(r"SYN-REVIEWER-[0-9]{3}\Z")


def validate_demo_review_script(script: dict[str, Any], dataset: dict[str, Any]) -> dict[str, Any]:
    """Validate four fictional dispositions; no actual human review is implied."""
    if not isinstance(script, dict) or set(script) != {
        "fixture_set_id", "scripted_only", "human_execution", "purpose", "entries"
    }:
        raise InvalidFixture("Unexpected synthetic review-script fields")
    if (script["fixture_set_id"] != FIXTURE_SET_ID
        or script["scripted_only"] is not True
        or script["human_execution"] is not False
        or not isinstance(script["purpose"], str)
        or "not an actual approval" not in script["purpose"]):
        raise InvalidFixture("Scripted human-role provenance invalid")
    rows = script["entries"]
    if not isinstance(rows, list) or len(rows) != 4:
        raise InvalidFixture("Expected four controlled synthetic dispositions")
    allowed_cases = {row["case_id"] for row in dataset["records"]}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "case_id", "reviewer_id", "disposition", "reason_code"
        }:
            raise InvalidFixture("Unexpected reviewer-script fields")
        cid = row["case_id"]
        decision = row["disposition"]
        if not _ident(cid, CASE_ID) or cid not in allowed_cases or cid in seen:
            raise InvalidFixture("Unknown or duplicate scripted case")
        if not _ident(row["reviewer_id"], REVIEWER_ID):
            raise InvalidFixture("Reviewer identity must be fictional")
        if decision not in SCRIPT_DISPOSITIONS or row["reason_code"] != SCRIPT_REASONS[decision]:
            raise InvalidFixture("Scripted disposition or reason not allowed")
        seen.add(cid)
    return script


def load_demo_review_script() -> dict[str, Any]:
    """Load pinned, wholly invented reviewer-role inputs; never persist changes."""
    manifest = _manifest()
    dataset = load_fixture_set()
    script = _load_json_file(
        FIXTURE_DIR / "demo_review_script.json",
        manifest["demo_review_script_git_blob_sha1"],
    )
    return validate_demo_review_script(script, dataset)
