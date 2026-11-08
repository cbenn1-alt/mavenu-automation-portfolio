"""V14 in-memory duplicate and idempotency controls for fabricated fixtures.

This is an isolated DEVELOPMENT simulator. It does not ingest or modify
customer systems, persistent storage, live maintenance orders or V9 runtime
modules. V10 formal promotion and V11 source approval remain outstanding.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import verify_v11
import verify_v12

PROJECT = Path(__file__).resolve().parents[1]
POLICY_PATH = PROJECT / "docs" / "data" / "IDEMPOTENCY_CONTRACT_V14.json"

IDENTITIES = {
    "asset_records": "asset_id",
    "case_records": "case_id",
    "scripted_review_entries": "case_id",
    "seeded_reference_labels": "case_id",
}
FOREIGN_KEYS = {
    "case_records.asset_id": "asset_records.asset_id",
    "scripted_review_entries.case_id": "case_records.case_id",
    "seeded_reference_labels.case_id": "case_records.case_id",
}


class IngestRejected(ValueError):
    """Fixed, non-sensitive error code, never raw source records."""


def require(condition: Any, code: str) -> None:
    if not condition:
        raise IngestRejected(code)


def canonical(value: Any) -> bytes:
    """Stable content identity for JSON-compatible fabricated values only."""
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (ValueError, TypeError, OverflowError):
        raise IngestRejected("noncanonical_payload") from None


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def validate_policy(policy: dict[str, Any],
                    dictionary: dict[str, Any],
                    v12_contract: dict[str, Any]) -> None:
    require(type(policy) is dict, "policy_not_object")
    require(policy.get("increment") == "V14", "policy_increment_drift")
    require(policy.get("objective") == "Enforce duplicates and idempotency rules",
            "policy_objective_drift")
    require(policy.get("required_proof") == "Repeated-ingest comparison",
            "policy_proof_drift")
    require(policy.get("schema_version") == "1.0.0", "policy_schema_version")
    require(policy.get("contract_state") ==
            "SYNTHETIC_TECHNICAL_DRAFT_NOT_APPROVED", "unsupported_policy_approval")
    for key in ("formal_phase_02_authorized", "customer_data_authorized",
                "human_owner_approval", "production_write_authorized",
                "cross_process_exactly_once_guarantee", "network_ingestion_enabled",
                "customer_record_ids_permitted"):
        require(policy.get(key) is False, "unauthorized_" + key)
    for key in ("named_approver", "approval_signature"):
        require(policy.get(key) is None, "invented_approval_" + key)
    require(policy.get("v10_promotion_recommendation") == "BLOCKED",
            "v10_decision_misrepresented")
    require(policy.get("fixture_set_id") == "SYN-RI-V5-20261107-A",
            "fixture_set_mismatch")
    require(policy.get("v9_frozen_source_commit") ==
            "704123eca45628bf504594af39a66036cc0451c5", "frozen_source_drift")
    require(policy.get("source_dictionary") ==
            "docs/data/SOURCE_FIELD_DICTIONARY_V11.json", "source_contract_drift")
    require(policy.get("schema_contract") ==
            "docs/data/SCHEMA_CONTRACT_V12.json", "schema_contract_drift")
    require(policy.get("identity_fields") == IDENTITIES, "identity_policy_drift")
    require(policy.get("secondary_uniqueness") ==
            {"case_records": ["work_order_ref"]}, "secondary_identity_drift")
    require(policy.get("required_relations") == FOREIGN_KEYS,
            "foreign_key_policy_drift")
    require(policy.get("duplicate_policy") ==
            "identical_record_no_op_conflicting_identity_fail_closed",
            "duplicate_policy_drift")
    require(policy.get("atomicity_policy") ==
            "validate_full_batch_then_commit_in_memory", "atomicity_policy_drift")
    require(policy.get("replay_order_policy") ==
            "input_dataset_and_record_order_cannot_change_final_state_hash",
            "ordering_policy_drift")
    require(policy.get("canonical_encoding") ==
            "json_sorted_keys_compact_ascii_finite_numbers", "canonical_encoding_drift")
    require(policy.get("digest_algorithm") == "SHA-256", "digest_algorithm_drift")
    require(policy.get("persistence") == "NONE", "persistence_claim_drift")
    require(policy.get("expected_reference_records") == 34 and
            policy.get("expected_reference_datasets") == 4,
            "reference_inventory_drift")
    require(dictionary.get("dictionary_status") ==
            "DRAFT_TECHNICALLY_CHECKABLE_NOT_APPROVED",
            "unapproved_dictionary_misrepresented")
    require(v12_contract.get("contract_status") ==
            "TECHNICALLY_CHECKABLE_DRAFT_NOT_APPROVED",
            "unapproved_schema_misrepresented")


class InMemoryIngest:
    """Atomic, per-process synthetic record store; not a deployed ingest API."""

    def __init__(self, policy: dict[str, Any],
                 dictionary: dict[str, Any],
                 v12_contract: dict[str, Any]) -> None:
        validate_policy(policy, dictionary, v12_contract)
        self._field_index = verify_v11.validate_dictionary(dictionary)
        self._groups = verify_v12.validate_contract(v12_contract, dictionary)
        self._rows: dict[str, dict[str, dict[str, Any]]] = {
            name: {} for name in IDENTITIES
        }

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        """Return a defensive copy, with canonical dataset and primary-key order."""
        return {
            name: [copy.deepcopy(rows[key]) for key in sorted(rows)]
            for name, rows in sorted(self._rows.items())
        }

    def state_sha256(self) -> str:
        return sha256(self.snapshot())

    def row_counts(self) -> dict[str, int]:
        return {name: len(rows) for name, rows in sorted(self._rows.items())}

    def _validate_row(self, dataset: str, row: Any) -> None:
        require(type(row) is dict, "source_record_invalid")
        fields = self._field_index[dataset]
        require(set(row) == set(fields), "source_record_invalid")
        for field_name, field in fields.items():
            require(verify_v11._matches(row[field_name], field),
                    "source_record_invalid")
        # Single-row semantic policies are inherited from the V11 draft and
        # V13 controls, without assuming these limits are industrial standards.
        if dataset == "case_records":
            require(row["synthetic"] is True and
                    row["review_state"] == "fixture_only", "source_record_invalid")
        elif dataset in ("asset_records", "seeded_reference_labels"):
            require(row["synthetic"] is True, "source_record_invalid")

    @staticmethod
    def _validate_references(rows: dict[str, dict[str, dict[str, Any]]]) -> None:
        assets = set(rows["asset_records"])
        cases = set(rows["case_records"])
        used_work_orders: set[str] = set()
        for case in rows["case_records"].values():
            ref = case["work_order_ref"]
            require(ref not in used_work_orders, "duplicate_work_order_reference")
            used_work_orders.add(ref)
            require(case["asset_id"] in assets, "unknown_asset_reference")
        for name in ("scripted_review_entries", "seeded_reference_labels"):
            for row in rows[name].values():
                require(row["case_id"] in cases, "unknown_case_reference")
        # Reference annotations may be loaded incrementally; complete
        # case-to-label coverage is NOT required for partial staged ingestion.

    def ingest(self, batch: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        """All-or-nothing batch insert or exact replay, with fail-closed conflicts.

        A failure leaves the previous state bit-for-bit unchanged.
        Each batch must be referentially valid by commit; use one batch to
        ingest related records in any dataset ordering, or load parents first.
        """
        require(type(batch) is dict and set(batch).issubset(IDENTITIES),
                "batch_shape_invalid")
        staged = copy.deepcopy(self._rows)
        inserted = 0
        duplicates = 0
        for dataset in sorted(batch):
            records = batch[dataset]
            require(type(records) is list, "batch_shape_invalid")
            primary_key = IDENTITIES[dataset]
            for row in records:
                self._validate_row(dataset, row)
                key = row[primary_key]
                existing = staged[dataset].get(key)
                if existing is None:
                    staged[dataset][key] = copy.deepcopy(row)
                    inserted += 1
                elif canonical(existing) == canonical(row):
                    duplicates += 1
                else:
                    raise IngestRejected("identity_conflict")
        self._validate_references(staged)
        new_state = {
            name: {key: staged[name][key] for key in sorted(staged[name])}
            for name in sorted(staged)
        }
        # No change is committed until validation and canonicalization pass.
        digest = sha256({name: list(rows.values()) for name, rows in new_state.items()})
        self._rows = new_state
        return {
            "inserted": inserted,
            "duplicates": duplicates,
            "total_records": sum(len(rows) for rows in self._rows.values()),
            "state_sha256": digest,
            "persistent_storage": False,
            "customer_data_used": False,
            "real_operational_actions": False,
        }


def source_batch(sources: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Create a deep-copied batch from the unchanged synthetic fixtures."""
    result: dict[str, list[dict[str, Any]]] = {}
    for name, (file, records_key, count) in verify_v11.SOURCE_BINDINGS.items():
        document = sources[file]
        require(document.get("fixture_set_id") == "SYN-RI-V5-20261107-A",
                "source_fixture_set_drift")
        rows = document.get(records_key)
        require(type(rows) is list and len(rows) == count,
                "source_fixture_count_drift")
        result[name] = copy.deepcopy(rows)
    return result


def load_ingest_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any],
                                  dict[str, dict[str, Any]]]:
    try:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise IngestRejected("policy_unavailable") from None
    dictionary = verify_v11.read_json(verify_v11.DICTIONARY_PATH)
    contract = verify_v11.read_json(verify_v12.CONTRACT_PATH)
    sources = verify_v11.load_sources()
    return policy, dictionary, contract, sources
