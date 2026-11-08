"""Project P03 — AI Document Intelligence & Exception Management: service layer.

Owns: document ingest (JSON / CSV / single text) with row-level error
reporting; deterministic field extraction (see extraction.py) with
per-field confidence + provenance; validation rules; the exception queue
(open -> investigating -> resolved | written_off, enforced by
EXCEPTION_WORKFLOW) with actor-stamped transition history; human review
of low-confidence and missing fields; and the extraction reports
(summary, review backlog, exception aging).

The core honesty rule of this project: extraction PROPOSES, a human
DISPOSES. A field extracted below the accept threshold (0.80) stays
``proposed`` — there is no auto-accept path for it. A document reaches
``accepted`` only when every spec field is accepted. A human may accept
a proposed field, correct any proposed/missing/rejected field with a
validated value, or reject a proposed field; correcting a field is the
only way a missing field becomes accepted.

Money: amounts arrive as Decimal, are stored as integer cents, and are
rendered back as Decimal. float is NEVER used for amounts anywhere in
this module.

ALL DATA IS SYNTHETIC DEMONSTRATION DATA. See the module README in
projects/project03/ for the honest-status banner.
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Optional

from .db import utcnow_iso
from .extraction import (
    DEFAULT_ACCEPT_THRESHOLD,
    DOC_TYPES,
    ExtractedField,
    extract_fields,
    document_confidence,
    field_names,
    validate_corrected_value,
    validate_document,
)
from .reconcile import cents_to_decimal, sanitize_cell
from .workflow import DOC_WORKFLOW, EXCEPTION_WORKFLOW, InvalidTransition

ACCEPT_THRESHOLD = DEFAULT_ACCEPT_THRESHOLD


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def _now_or(now: Optional[datetime]) -> datetime:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now


def _batch_label(now: datetime) -> str:
    return f"doc:{now.isoformat(timespec='seconds')}"


def _validate_doc_meta(doc_id: str, doc_type: str, text: str) -> dict[str, str]:
    """Field-level validation for one document's metadata. Returns errors."""
    errors: dict[str, str] = {}
    if not doc_id:
        errors["doc_id"] = "doc_id is required."
    if doc_type not in DOC_TYPES:
        errors["doc_type"] = f"doc_type must be one of {', '.join(DOC_TYPES)}."
    if not text or not text.strip():
        errors["text"] = "document text is required."
    return errors


def _insert_document(
    conn: sqlite3.Connection,
    doc_id: str,
    doc_type: str,
    source_format: str,
    text: str,
    batch: str,
    moment: datetime,
    actor: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO docintel_documents
            (doc_id, doc_type, source_format, source_text, state,
             actor, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'ingested', ?, ?, ?)
        """,
        (doc_id, doc_type, source_format, text, actor,
         moment.isoformat(timespec="seconds"), moment.isoformat(timespec="seconds")),
    )
    return cur.lastrowid


def _raise_duplicate_exception(
    conn: sqlite3.Connection,
    doc_id: str,
    row_id: int,
    lineno: int,
    batch: str,
    moment: datetime,
    *,
    actor: str,
) -> int:
    return _upsert_open_exception(
        conn,
        kind="duplicate_document",
        ref_type="document",
        ref_id=row_id,
        ref_public_id=doc_id,
        field_name=None,
        detail={
            "doc_id": doc_id,
            "repeat_row": lineno,
            "batch": batch,
            "reason": "doc_id appeared twice in one ingest batch",
        },
        suggested_action=(
            f"Verify {doc_id} was not ingested twice. The repeat row was "
            "NOT stored (no double-counting). If the two copies differ, "
            "keep the correct one and reject the other."
        ),
        moment=moment,
        actor=actor,
    )


def _ingest_items(
    conn: sqlite3.Connection,
    items: list[dict],
    source_format: str,
    *,
    actor: str = "system",
    now: Optional[datetime] = None,
) -> dict:
    """Shared ingest core for JSON/CSV/text. ``items`` are 1-based-row dicts
    with doc_id / doc_type / text. Returns {inserted, skipped_idempotent,
    sanitized, errors, batch}.

    Sanitization note: doc_id and doc_type (metadata) go through
    sanitize_cell — the document TEXT is content, not a spreadsheet cell,
    and is stored as-is so extraction sees exactly what was submitted.
    """
    moment = _now_or(now)
    batch = _batch_label(moment)
    kind = f"ingest_{source_format}"
    result: dict[str, Any] = {
        "kind": kind,
        "inserted": 0,
        "skipped_idempotent": 0,
        "sanitized": 0,
        "errors": [],
        "batch": batch,
    }
    seen_in_batch: dict[str, int] = {}
    for lineno, item in enumerate(items, start=1):
        doc_id, s1 = sanitize_cell(item.get("doc_id"))
        doc_type, s2 = sanitize_cell(item.get("doc_type"))
        text = item.get("text")
        text = "" if text is None else str(text)
        result["sanitized"] += sum(1 for s in (s1, s2) if s)
        errors = _validate_doc_meta(doc_id, doc_type, text)
        if errors:
            result["errors"].append({"row": lineno, **errors})
            continue
        if doc_id in seen_in_batch:
            # Same doc_id twice in one batch: probable double-ingest.
            # Skip the row, raise a visible exception.
            _raise_duplicate_exception(
                conn, doc_id, seen_in_batch[doc_id], lineno, batch, moment, actor=actor
            )
            continue
        existing = conn.execute(
            "SELECT id FROM docintel_documents WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        if existing:
            result["skipped_idempotent"] += 1
            continue
        row_id = _insert_document(
            conn, doc_id, doc_type, source_format, text, batch, moment, actor
        )
        seen_in_batch[doc_id] = row_id
        result["inserted"] += 1
    conn.commit()
    _record_run(conn, kind, result, actor, moment)
    _log(actor, f"docintel.{kind}", {
        "batch": batch, "inserted": result["inserted"],
        "skipped": result["skipped_idempotent"],
        "sanitized": result["sanitized"], "errors": len(result["errors"]),
    })
    return result


def ingest_json(
    conn: sqlite3.Connection,
    json_text: str,
    *,
    actor: str = "system",
    now: Optional[datetime] = None,
) -> dict:
    """Ingest a JSON array of {doc_id, doc_type, text} documents."""
    moment = _now_or(now)
    try:
        parsed = json.loads(json_text or "")
    except json.JSONDecodeError as exc:
        result = {
            "kind": "ingest_json",
            "inserted": 0, "skipped_idempotent": 0, "sanitized": 0,
            "errors": [{"row": 0, "fatal": f"Invalid JSON: {exc}"}],
            "batch": _batch_label(moment),
        }
        _record_run(conn, "ingest_json", result, actor, moment)
        return result
    if not isinstance(parsed, list):
        result = {
            "kind": "ingest_json",
            "inserted": 0, "skipped_idempotent": 0, "sanitized": 0,
            "errors": [{"row": 0, "fatal": "JSON must be an array of documents."}],
            "batch": _batch_label(moment),
        }
        _record_run(conn, "ingest_json", result, actor, moment)
        return result
    return _ingest_items(conn, parsed, "json", actor=actor, now=moment)


def ingest_csv(
    conn: sqlite3.Connection,
    csv_text: str,
    *,
    actor: str = "system",
    now: Optional[datetime] = None,
) -> dict:
    """Ingest a CSV with columns doc_id, doc_type, text. Row-level errors
    never abort the batch; a missing header is fatal."""
    moment = _now_or(now)
    reader = csv.DictReader(io.StringIO(csv_text or ""))
    if not reader.fieldnames:
        result = {
            "kind": "ingest_csv",
            "inserted": 0, "skipped_idempotent": 0, "sanitized": 0,
            "errors": [{"row": 0, "fatal": "CSV must have a header row."}],
            "batch": _batch_label(moment),
        }
        _record_run(conn, "ingest_csv", result, actor, moment)
        return result
    missing = [c for c in ("doc_id", "doc_type", "text") if c not in reader.fieldnames]
    if missing:
        result = {
            "kind": "ingest_csv",
            "inserted": 0, "skipped_idempotent": 0, "sanitized": 0,
            "errors": [{"row": 0, "fatal": f"Missing required columns: {', '.join(missing)}."}],
            "batch": _batch_label(moment),
        }
        _record_run(conn, "ingest_csv", result, actor, moment)
        return result
    return _ingest_items(conn, list(reader), "csv", actor=actor, now=moment)


def ingest_text(
    conn: sqlite3.Connection,
    doc_id: str,
    doc_type: str,
    text: str,
    *,
    actor: str = "system",
    now: Optional[datetime] = None,
) -> dict:
    """Ingest a single document given directly (no batch file)."""
    return _ingest_items(
        conn, [{"doc_id": doc_id, "doc_type": doc_type, "text": text}],
        "text", actor=actor, now=now,
    )


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def _store_fields(
    conn: sqlite3.Connection,
    doc_row_id: int,
    extracted: dict[str, Optional[ExtractedField]],
    moment: datetime,
    actor: str,
) -> None:
    for field_name, field in extracted.items():
        if field is None:
            conn.execute(
                """
                INSERT INTO docintel_fields
                    (document_id, field_name, status, actor, created_at, updated_at)
                VALUES (?, ?, 'missing', ?, ?, ?)
                """,
                (doc_row_id, field_name, actor,
                 moment.isoformat(timespec="seconds"), moment.isoformat(timespec="seconds")),
            )
            continue
        status = "accepted" if field.confidence >= ACCEPT_THRESHOLD else "proposed"
        conn.execute(
            """
            INSERT INTO docintel_fields
                (document_id, field_name, value_text, value_cents, confidence,
                 rule_id, source_line, raw_matched_text, status,
                 actor, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_row_id, field_name, field.value, field.value_cents,
                str(field.confidence), field.rule_id, field.source_line,
                field.raw_text, status, actor,
                moment.isoformat(timespec="seconds"), moment.isoformat(timespec="seconds"),
            ),
        )


def _raise_extraction_exceptions(
    conn: sqlite3.Connection,
    doc_row: sqlite3.Row,
    extracted: dict[str, Optional[ExtractedField]],
    failures: list[dict],
    moment: datetime,
    actor: str,
) -> int:
    """Raise the open exceptions for one extraction. Returns the count
    raised. Zero extracted fields means an unparseable document: one
    document-level exception, and no per-field missing exceptions."""
    count = 0
    extracted_count = sum(1 for f in extracted.values() if f is not None)
    if extracted_count == 0:
        _upsert_open_exception(
            conn,
            kind="unparseable_document",
            ref_type="document",
            ref_id=doc_row["id"],
            ref_public_id=doc_row["doc_id"],
            field_name=None,
            detail={"doc_type": doc_row["doc_type"], "extracted_fields": 0,
                    "reason": "no extraction rule fired for any field"},
            suggested_action=(
                f"No field could be extracted from {doc_row['doc_id']}. Check "
                "that the document type is right and the text is complete, "
                "then re-ingest a corrected copy — or reject the document."
            ),
            moment=moment,
            actor=actor,
        )
        return 1
    for field_name, field in extracted.items():
        if field is None:
            _upsert_open_exception(
                conn,
                kind="missing_field",
                ref_type="document",
                ref_id=doc_row["id"],
                ref_public_id=doc_row["doc_id"],
                field_name=field_name,
                detail={"field": field_name,
                        "reason": "no extraction rule fired for this field"},
                suggested_action=(
                    f"Field '{field_name}' was not found in {doc_row['doc_id']}. "
                    "Correct it by supplying the value, or reject the document."
                ),
                moment=moment,
                actor=actor,
            )
            count += 1
        elif field.confidence < ACCEPT_THRESHOLD:
            _upsert_open_exception(
                conn,
                kind="low_confidence",
                ref_type="document",
                ref_id=doc_row["id"],
                ref_public_id=doc_row["doc_id"],
                field_name=field_name,
                detail={
                    "field": field_name,
                    "confidence": str(field.confidence),
                    "threshold": str(ACCEPT_THRESHOLD),
                    "rule_id": field.rule_id,
                    "raw_text": field.raw_text,
                    "value": field.value,
                },
                suggested_action=(
                    f"Field '{field_name}' was extracted at confidence "
                    f"{field.confidence} (below the {ACCEPT_THRESHOLD} threshold) "
                    f"as {field.value!r}. Accept it if correct, or correct it."
                ),
                moment=moment,
                actor=actor,
            )
            count += 1
    for failure in failures:
        _upsert_open_exception(
            conn,
            kind="validation_failed",
            ref_type="document",
            ref_id=doc_row["id"],
            ref_public_id=doc_row["doc_id"],
            field_name=failure["field"],
            detail={
                "field": failure["field"],
                "rule_id": failure["rule_id"],
                "message": failure["message"],
            },
            suggested_action=(
                f"Validation rule '{failure['rule_id']}' failed for field "
                f"'{failure['field']}': {failure['message']} Correct the "
                "field, or reject the document."
            ),
            moment=moment,
            actor=actor,
        )
        count += 1
    return count


def _set_doc_state(
    conn: sqlite3.Connection,
    doc_row: sqlite3.Row,
    to_state: str,
    actor: str,
    detail: str,
    moment: datetime,
) -> None:
    DOC_WORKFLOW.check(doc_row["state"], to_state)
    conn.execute(
        "UPDATE docintel_documents SET state = ?, actor = ?, updated_at = ? WHERE id = ?",
        (to_state, actor, moment.isoformat(timespec="seconds"), doc_row["id"]),
    )
    conn.execute(
        """
        INSERT INTO docintel_doc_events
            (document_id, from_state, to_state, actor, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (doc_row["id"], doc_row["state"], to_state, actor, detail,
         moment.isoformat(timespec="seconds")),
    )


def extract_document(
    conn: sqlite3.Connection,
    doc_id: str,
    *,
    actor: str = "system",
    now: Optional[datetime] = None,
) -> dict:
    """Run extraction on one ingested document. Returns the extraction
    report {doc_id, doc_type, fields_extracted, fields_missing,
    fields_proposed, exceptions_raised, state, doc_confidence}.

    Only documents in state 'ingested' can be extracted — re-extracting
    would wipe human corrections. Raises KeyError for an unknown doc_id
    and ValueError when the document is not in 'ingested' state."""
    moment = _now_or(now)
    row = conn.execute(
        "SELECT * FROM docintel_documents WHERE doc_id = ?", (doc_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"No document with doc_id {doc_id!r}.")
    if row["state"] != "ingested":
        raise ValueError(
            f"Document {doc_id!r} is in state {row['state']!r}; only "
            "'ingested' documents can be extracted."
        )
    extracted = extract_fields(row["doc_type"], row["source_text"])
    failures = validate_document(
        row["doc_type"], extracted, today=moment.date()
    )
    _store_fields(conn, row["id"], extracted, moment, actor)
    exceptions_raised = _raise_extraction_exceptions(
        conn, row, extracted, failures, moment, actor
    )
    extracted_count = sum(1 for f in extracted.values() if f is not None)
    missing_count = len(extracted) - extracted_count
    proposed_count = sum(
        1 for f in extracted.values()
        if f is not None and f.confidence < ACCEPT_THRESHOLD
    )
    doc_conf = document_confidence(extracted)
    needs_review = (
        proposed_count > 0 or missing_count > 0 or bool(failures)
    )
    to_state = "needs_review" if needs_review else "accepted"
    conn.execute(
        "UPDATE docintel_documents SET doc_confidence = ? WHERE id = ?",
        (str(doc_conf) if doc_conf is not None else None, row["id"]),
    )
    _set_doc_state(conn, row, to_state, actor,
                   "extraction complete" if not needs_review else
                   "extraction complete; human review required", moment)
    conn.commit()
    _log(actor, "docintel.extract", {
        "doc_id": doc_id, "state": to_state,
        "extracted": extracted_count, "missing": missing_count,
        "proposed": proposed_count, "exceptions": exceptions_raised,
    })
    return {
        "doc_id": doc_id,
        "doc_type": row["doc_type"],
        "fields_extracted": extracted_count,
        "fields_missing": missing_count,
        "fields_proposed": proposed_count,
        "exceptions_raised": exceptions_raised,
        "state": to_state,
        "doc_confidence": str(doc_conf) if doc_conf is not None else None,
    }


def extract_all(
    conn: sqlite3.Connection,
    *,
    actor: str = "system",
    now: Optional[datetime] = None,
) -> dict:
    """Extract every document still in 'ingested' state. Returns aggregate
    stats {documents, accepted, needs_review, exceptions_raised}."""
    moment = _now_or(now)
    rows = conn.execute(
        "SELECT doc_id FROM docintel_documents WHERE state = 'ingested' ORDER BY id"
    ).fetchall()
    stats: dict[str, Any] = {
        "kind": "extract",
        "documents": 0,
        "accepted": 0,
        "needs_review": 0,
        "exceptions_raised": 0,
    }
    for row in rows:
        report = extract_document(conn, row["doc_id"], actor=actor, now=moment)
        stats["documents"] += 1
        stats[report["state"]] += 1
        stats["exceptions_raised"] += report["exceptions_raised"]
    _record_run(conn, "extract", stats, actor, moment)
    return stats


# ---------------------------------------------------------------------------
# Human review of fields
# ---------------------------------------------------------------------------

def _field_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "document_id": row["document_id"],
        "field_name": row["field_name"],
        "value_text": row["value_text"],
        "value_cents": row["value_cents"],
        "confidence": row["confidence"],
        "rule_id": row["rule_id"],
        "source_line": row["source_line"],
        "raw_matched_text": row["raw_matched_text"],
        "status": row["status"],
        "corrected": bool(row["corrected"]),
        "corrected_value_text": row["corrected_value_text"],
        "actor": row["actor"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_document(conn: sqlite3.Connection, doc_id: str) -> dict:
    """One document with its fields. Raises KeyError for an unknown doc_id."""
    row = conn.execute(
        "SELECT * FROM docintel_documents WHERE doc_id = ?", (doc_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"No document with doc_id {doc_id!r}.")
    fields = [
        _field_dict(r)
        for r in conn.execute(
            "SELECT * FROM docintel_fields WHERE document_id = ? ORDER BY id",
            (row["id"],),
        ).fetchall()
    ]
    return {
        "id": row["id"],
        "doc_id": row["doc_id"],
        "doc_type": row["doc_type"],
        "source_format": row["source_format"],
        "state": row["state"],
        "doc_confidence": row["doc_confidence"],
        "actor": row["actor"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "fields": fields,
    }


def list_documents(
    conn: sqlite3.Connection,
    *,
    state: Optional[str] = None,
    doc_type: Optional[str] = None,
) -> list[dict]:
    sql = "SELECT * FROM docintel_documents"
    clauses, params = [], []
    if state:
        clauses.append("state = ?")
        params.append(state)
    if doc_type:
        clauses.append("doc_type = ?")
        params.append(doc_type)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at, id"
    docs = []
    for row in conn.execute(sql, params).fetchall():
        docs.append({
            "id": row["id"],
            "doc_id": row["doc_id"],
            "doc_type": row["doc_type"],
            "source_format": row["source_format"],
            "state": row["state"],
            "doc_confidence": row["doc_confidence"],
            "actor": row["actor"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })
    return docs


def _recompute_doc_state(
    conn: sqlite3.Connection,
    doc_row: sqlite3.Row,
    actor: str,
    moment: datetime,
) -> str:
    """After a field review or an exception resolution, move a needs_review
    document to accepted when every spec field is accepted AND no
    validation_failed exception is still open — and only then. A document
    whose validation exception was resolved directly by a human (without
    correcting the field) is accepted on that human's authority: the
    resolution is actor-stamped in the audit trail, and the field value
    is preserved as-is. Returns the new state."""
    # Re-fetch: the caller may hold a stale row (e.g. review_field's doc
    # was already moved to 'accepted' by the validation-resolution step
    # inside this same call — a second transition would write a duplicate
    # audit row).
    current = conn.execute(
        "SELECT * FROM docintel_documents WHERE id = ?", (doc_row["id"],)
    ).fetchone()
    if current is None:
        return doc_row["state"]
    statuses = [
        r["status"]
        for r in conn.execute(
            "SELECT status FROM docintel_fields WHERE document_id = ?",
            (current["id"],),
        ).fetchall()
    ]
    open_validation = conn.execute(
        """
        SELECT COUNT(*) AS c FROM docintel_exceptions
        WHERE ref_public_id = ? AND kind = 'validation_failed' AND state = 'open'
        """,
        (current["doc_id"],),
    ).fetchone()["c"]
    if (
        current["state"] == "needs_review"
        and statuses
        and all(s == "accepted" for s in statuses)
        and open_validation == 0
    ):
        _set_doc_state(conn, current, "accepted", actor,
                       "all fields resolved by human review", moment)
        return "accepted"
    return current["state"]


def review_field(
    conn: sqlite3.Connection,
    doc_id: str,
    field_name: str,
    action: str,
    *,
    actor: str,
    corrected_value: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Human review of one field. Actions:
    - accept:  proposed -> accepted (only for a proposed field; there
               must be an extracted value to accept).
    - correct: proposed | missing | rejected -> accepted, with a validated
               corrected value (money via Decimal, dates ISO, term positive,
               payment_method in the enum). The original extraction stays
               in provenance; the correction is stamped.
    - reject:  proposed -> rejected (field excluded; the document stays in
               needs_review until the field is corrected or the document
               itself is rejected).
    Illegal actions raise ValueError. Returns the updated field dict."""
    moment = _now_or(now)
    doc = conn.execute(
        "SELECT * FROM docintel_documents WHERE doc_id = ?", (doc_id,)
    ).fetchone()
    if doc is None:
        raise KeyError(f"No document with doc_id {doc_id!r}.")
    if doc["doc_type"] not in DOC_TYPES or field_name not in field_names(doc["doc_type"]):
        raise KeyError(f"No field {field_name!r} on document {doc_id!r}.")
    row = conn.execute(
        "SELECT * FROM docintel_fields WHERE document_id = ? AND field_name = ?",
        (doc["id"], field_name),
    ).fetchone()
    if row is None:
        raise KeyError(f"No field {field_name!r} on document {doc_id!r}.")
    status = row["status"]
    if action not in ("accept", "correct", "reject"):
        raise ValueError(f"Unknown review action {action!r}.")
    if action == "accept":
        if status != "proposed":
            raise ValueError(
                f"Cannot accept field {field_name!r} in status {status!r}: "
                "only a proposed (below-threshold) field can be accepted."
            )
        new_status, corrected, new_value, new_cents = "accepted", 0, None, row["value_cents"]
        detail = f"accepted extracted value {row['value_text']!r}"
    elif action == "correct":
        if status == "accepted":
            # Accepted fields are locked — with one exception: a field the
            # system itself flagged as invalid (an open validation_failed
            # exception) must be correctable, or the document could never
            # be fixed. A high-confidence extraction can still fail a
            # validation rule (e.g. payment_method 'crypto' at 0.95).
            open_validation = conn.execute(
                """
                SELECT id FROM docintel_exceptions
                WHERE kind = 'validation_failed' AND ref_public_id = ?
                  AND field_name = ? AND state = 'open'
                """,
                (doc_id, field_name),
            ).fetchone()
            if not open_validation:
                raise ValueError(
                    f"Cannot correct field {field_name!r} in status 'accepted': "
                    "accepted fields are locked unless an open "
                    "validation_failed exception flags the value."
                )
        elif status not in ("proposed", "missing", "rejected"):
            raise ValueError(
                f"Cannot correct field {field_name!r} in status {status!r}."
            )
        try:
            new_value, new_cents = validate_corrected_value(
                doc["doc_type"], field_name, corrected_value
            )
        except ValueError as exc:
            raise ValueError(f"Corrected value rejected: {exc}") from exc
        new_status, corrected = "accepted", 1
        detail = f"corrected to {new_value!r}"
    else:  # reject
        if status != "proposed":
            raise ValueError(
                f"Cannot reject field {field_name!r} in status {status!r}: "
                "only a proposed (below-threshold) field can be rejected."
            )
        # Keep the extracted value on the row (provenance); the rejected
        # status is what excludes it from totals.
        new_status, corrected, new_value, new_cents = "rejected", 0, None, row["value_cents"]
        detail = f"rejected extracted value {row['value_text']!r}"
    conn.execute(
        """
        UPDATE docintel_fields
        SET status = ?, corrected = ?, corrected_value_text = ?,
            value_cents = ?, actor = ?, updated_at = ?
        WHERE id = ?
        """,
        (new_status, corrected, new_value, new_cents, actor,
         moment.isoformat(timespec="seconds"), row["id"]),
    )
    if action == "correct":
        # The corrected value becomes the field's value.
        conn.execute(
            "UPDATE docintel_fields SET value_text = ? WHERE id = ?",
            (new_value, row["id"]),
        )
    conn.execute(
        """
        INSERT INTO docintel_field_events
            (field_id, document_id, field_name, action, from_status,
             to_status, actor, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (row["id"], doc["id"], field_name, action, status, new_status,
         actor, detail, moment.isoformat(timespec="seconds")),
    )
    # A corrected/accepted field may resolve the document's open
    # low_confidence / missing_field exception for that field, and may
    # make a validation rule pass again (e.g. correcting payment_method
    # from 'crypto' to 'card' clears the payment_method_known failure).
    if action in ("accept", "correct"):
        for kind in ("low_confidence", "missing_field"):
            exc = conn.execute(
                """
                SELECT id FROM docintel_exceptions
                WHERE kind = ? AND ref_public_id = ? AND field_name = ?
                  AND state = 'open'
                """,
                (kind, doc_id, field_name),
            ).fetchone()
            if exc:
                _resolve_exception(
                    conn, exc["id"], actor=actor,
                    detail=f"field {field_name!r} {action}ed by {actor}", moment=moment,
                )
        _resolve_stale_validation_exceptions(conn, doc, actor, moment)
    new_state = _recompute_doc_state(conn, doc, actor, moment)
    conn.commit()
    _log(actor, "docintel.field_review", {
        "doc_id": doc_id, "field": field_name, "action": action,
        "from_status": status, "to_status": new_status, "doc_state": new_state,
    })
    updated = conn.execute(
        "SELECT * FROM docintel_fields WHERE id = ?", (row["id"],)
    ).fetchone()
    return _field_dict(updated)


def _resolve_stale_validation_exceptions(
    conn: sqlite3.Connection,
    doc_row: sqlite3.Row,
    actor: str,
    moment: datetime,
) -> None:
    """After a field review, re-run validation over the document's current
    field values (accepted/proposed only — rejected fields are excluded)
    and resolve any open validation_failed exception whose rule now passes."""
    fields = {
        r["field_name"]: r
        for r in conn.execute(
            "SELECT * FROM docintel_fields WHERE document_id = ?", (doc_row["id"],)
        ).fetchall()
    }
    current: dict[str, Optional[ExtractedField]] = {}
    for name, r in fields.items():
        if r["status"] in ("accepted", "proposed") and r["value_text"] is not None:
            current[name] = ExtractedField(
                value=r["value_text"],
                value_cents=r["value_cents"],
                confidence=Decimal(r["confidence"]) if r["confidence"] else Decimal("0"),
                rule_id=r["rule_id"] or "",
                source_line=r["source_line"] or 0,
                raw_text=r["raw_matched_text"] or "",
            )
        else:
            current[name] = None
    failures = validate_document(doc_row["doc_type"], current, today=moment.date())
    still_failing = {(f["rule_id"], f["field"]) for f in failures}
    for exc in conn.execute(
        """
        SELECT * FROM docintel_exceptions
        WHERE ref_public_id = ? AND kind = 'validation_failed' AND state = 'open'
        """,
        (doc_row["doc_id"],),
    ).fetchall():
        detail = json.loads(exc["detail_json"])
        if (detail.get("rule_id"), detail.get("field")) not in still_failing:
            _resolve_exception(
                conn, exc["id"], actor=actor,
                detail="validation rule now passes after field review", moment=moment,
            )


def field_history(conn: sqlite3.Connection, doc_id: str, field_name: str) -> list[dict]:
    doc = conn.execute(
        "SELECT id FROM docintel_documents WHERE doc_id = ?", (doc_id,)
    ).fetchone()
    if doc is None:
        raise KeyError(f"No document with doc_id {doc_id!r}.")
    rows = conn.execute(
        """
        SELECT * FROM docintel_field_events
        WHERE document_id = ? AND field_name = ? ORDER BY id
        """,
        (doc["id"], field_name),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "action": r["action"],
            "from_status": r["from_status"],
            "to_status": r["to_status"],
            "actor": r["actor"],
            "detail": r["detail"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def reject_document(
    conn: sqlite3.Connection,
    doc_id: str,
    *,
    actor: str,
    detail: str = "",
    now: Optional[datetime] = None,
) -> dict:
    """Human rejection of a whole document (terminal). Raises KeyError for
    an unknown doc_id and InvalidTransition for a terminal document."""
    moment = _now_or(now)
    row = conn.execute(
        "SELECT * FROM docintel_documents WHERE doc_id = ?", (doc_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"No document with doc_id {doc_id!r}.")
    _set_doc_state(conn, row, "rejected", actor, detail or "rejected by human review", moment)
    conn.commit()
    return get_document(conn, doc_id)


def doc_history(conn: sqlite3.Connection, doc_id: str) -> list[dict]:
    doc = conn.execute(
        "SELECT id FROM docintel_documents WHERE doc_id = ?", (doc_id,)
    ).fetchone()
    if doc is None:
        raise KeyError(f"No document with doc_id {doc_id!r}.")
    rows = conn.execute(
        "SELECT * FROM docintel_doc_events WHERE document_id = ? ORDER BY id",
        (doc["id"],),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "from_state": r["from_state"],
            "to_state": r["to_state"],
            "actor": r["actor"],
            "detail": r["detail"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Exception queue (mirrors reconcile.py's queue on docintel tables)
# ---------------------------------------------------------------------------

def _upsert_open_exception(
    conn: sqlite3.Connection,
    *,
    kind: str,
    ref_type: str,
    ref_id: int,
    ref_public_id: str,
    field_name: Optional[str],
    detail: Mapping[str, Any],
    suggested_action: str,
    moment: datetime,
    actor: str = "system",
) -> int:
    """Create an open exception, or return the existing open one (idempotent)."""
    if field_name is None:
        existing = conn.execute(
            """
            SELECT id FROM docintel_exceptions
            WHERE kind = ? AND ref_type = ? AND ref_public_id = ?
              AND field_name IS NULL AND state = 'open'
            """,
            (kind, ref_type, ref_public_id),
        ).fetchone()
    else:
        existing = conn.execute(
            """
            SELECT id FROM docintel_exceptions
            WHERE kind = ? AND ref_type = ? AND ref_public_id = ?
              AND field_name = ? AND state = 'open'
            """,
            (kind, ref_type, ref_public_id, field_name),
        ).fetchone()
    if existing:
        return existing["id"]
    cur = conn.execute(
        """
        INSERT INTO docintel_exceptions
            (kind, ref_type, ref_id, ref_public_id, field_name, detail_json,
             suggested_action, state, actor, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
        """,
        (
            kind,
            ref_type,
            ref_id,
            ref_public_id,
            field_name,
            json.dumps(dict(detail), sort_keys=True),
            suggested_action,
            actor,
            moment.isoformat(timespec="seconds"),
            moment.isoformat(timespec="seconds"),
        ),
    )
    exc_id = cur.lastrowid
    _log_exception_event(conn, exc_id, None, "open", actor, "exception raised", moment)
    return exc_id


def _log_exception_event(
    conn: sqlite3.Connection,
    exception_id: int,
    from_state: Optional[str],
    to_state: str,
    actor: str,
    detail: str,
    moment: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO docintel_exception_events
            (exception_id, from_state, to_state, actor, detail, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            exception_id,
            from_state,
            to_state,
            actor,
            detail,
            moment.isoformat(timespec="seconds"),
        ),
    )
    _log(actor, "docintel.exception_transition", {
        "exception_id": exception_id, "from_state": from_state,
        "to_state": to_state,
    })


def _resolve_exception(
    conn: sqlite3.Connection,
    exception_id: int,
    *,
    actor: str,
    detail: str,
    moment: datetime,
) -> None:
    """Resolve an open exception on a human's behalf, walking the legal
    path open -> investigating -> resolved. A direct open -> resolved
    move is not a legal transition (EXCEPTION_WORKFLOW), so field review
    resolves through both steps with the reviewer as the actor."""
    row = conn.execute(
        "SELECT state FROM docintel_exceptions WHERE id = ?", (exception_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"No exception with id {exception_id}.")
    if row["state"] == "open":
        transition_exception(
            conn, exception_id, "investigating", actor=actor,
            detail="under review", now=moment,
        )
    transition_exception(
        conn, exception_id, "resolved", actor=actor, detail=detail, now=moment,
    )


def transition_exception(
    conn: sqlite3.Connection,
    exception_id: int,
    to_state: str,
    *,
    actor: str,
    detail: str = "",
    now: Optional[datetime] = None,
) -> dict:
    """Move an exception through the state machine. Illegal moves raise
    InvalidTransition. The transition is actor-stamped in the audit trail."""
    moment = _now_or(now)
    row = conn.execute(
        "SELECT * FROM docintel_exceptions WHERE id = ?", (exception_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"No exception with id {exception_id}.")
    EXCEPTION_WORKFLOW.check(row["state"], to_state)
    conn.execute(
        "UPDATE docintel_exceptions SET state = ?, actor = ?, updated_at = ? WHERE id = ?",
        (to_state, actor, moment.isoformat(timespec="seconds"), exception_id),
    )
    _log_exception_event(conn, exception_id, row["state"], to_state, actor, detail, moment)
    # Resolving a validation_failed exception may complete the document:
    # re-check whether its document can now become accepted.
    if row["kind"] == "validation_failed" and to_state in ("resolved", "written_off"):
        doc = conn.execute(
            "SELECT * FROM docintel_documents WHERE doc_id = ?",
            (row["ref_public_id"],),
        ).fetchone()
        if doc is not None:
            _recompute_doc_state(conn, doc, actor, moment)
    conn.commit()
    updated = conn.execute(
        "SELECT * FROM docintel_exceptions WHERE id = ?", (exception_id,)
    ).fetchone()
    return _exception_dict(updated)


def _exception_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "ref_type": row["ref_type"],
        "ref_id": row["ref_id"],
        "ref_public_id": row["ref_public_id"],
        "field_name": row["field_name"],
        "detail": json.loads(row["detail_json"]),
        "suggested_action": row["suggested_action"],
        "state": row["state"],
        "actor": row["actor"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_exceptions(
    conn: sqlite3.Connection,
    *,
    state: Optional[str] = None,
    kind: Optional[str] = None,
) -> list[dict]:
    sql = "SELECT * FROM docintel_exceptions"
    clauses, params = [], []
    if state:
        clauses.append("state = ?")
        params.append(state)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at, id"
    return [_exception_dict(r) for r in conn.execute(sql, params).fetchall()]


def exception_history(conn: sqlite3.Connection, exception_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT * FROM docintel_exception_events
        WHERE exception_id = ? ORDER BY id
        """,
        (exception_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "from_state": r["from_state"],
            "to_state": r["to_state"],
            "actor": r["actor"],
            "detail": r["detail"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def extraction_summary(conn: sqlite3.Connection) -> dict:
    """Every total is computed from source rows. Money values are Decimal;
    counts are ints. The caller can verify the field identity against the
    docintel_fields table:
        fields_total == accepted + proposed + rejected + missing
    Money total is the sum of value_cents over ACCEPTED money fields —
    the trusted total; proposed/rejected values are never counted."""
    doc_count = conn.execute("SELECT COUNT(*) AS c FROM docintel_documents").fetchone()["c"]
    docs_by_state: dict[str, int] = {}
    for r in conn.execute(
        "SELECT state, COUNT(*) AS c FROM docintel_documents GROUP BY state"
    ).fetchall():
        docs_by_state[r["state"]] = r["c"]
    docs_by_type: dict[str, int] = {}
    for r in conn.execute(
        "SELECT doc_type, COUNT(*) AS c FROM docintel_documents GROUP BY doc_type"
    ).fetchall():
        docs_by_type[r["doc_type"]] = r["c"]
    fields_by_status: dict[str, int] = {}
    for r in conn.execute(
        "SELECT status, COUNT(*) AS c FROM docintel_fields GROUP BY status"
    ).fetchall():
        fields_by_status[r["status"]] = r["c"]
    fields_total = conn.execute("SELECT COUNT(*) AS c FROM docintel_fields").fetchone()["c"]
    accepted_money_cents = conn.execute(
        """
        SELECT COALESCE(SUM(value_cents), 0) AS t FROM docintel_fields
        WHERE status = 'accepted' AND value_cents IS NOT NULL
        """
    ).fetchone()["t"]
    exception_counts: dict[str, int] = {}
    for r in conn.execute(
        "SELECT state, COUNT(*) AS c FROM docintel_exceptions GROUP BY state"
    ).fetchall():
        exception_counts[r["state"]] = r["c"]
    exception_kinds: dict[str, int] = {}
    for r in conn.execute(
        "SELECT kind, COUNT(*) AS c FROM docintel_exceptions GROUP BY kind"
    ).fetchall():
        exception_kinds[r["kind"]] = r["c"]
    return {
        "document_count": doc_count,
        "documents_by_state": docs_by_state,
        "documents_by_type": docs_by_type,
        "fields_total": fields_total,
        "fields_by_status": fields_by_status,
        "accepted_money_cents": int(accepted_money_cents),
        "accepted_money": cents_to_decimal(int(accepted_money_cents)),
        "exceptions_by_state": exception_counts,
        "exceptions_by_kind": exception_kinds,
    }


EXCEPTION_AGING_BUCKETS = ("0-7 days", "8-30 days", "31+ days")


def exception_aging(
    conn: sqlite3.Connection, *, now: Optional[datetime] = None
) -> dict:
    """Open (and investigating) exceptions by age since creation."""
    today = _now_or(now).date()
    buckets: dict[str, dict] = {
        b: {"exception_count": 0, "kinds": {}} for b in EXCEPTION_AGING_BUCKETS
    }
    for r in conn.execute(
        "SELECT kind, created_at FROM docintel_exceptions "
        "WHERE state IN ('open', 'investigating')"
    ).fetchall():
        created = datetime.fromisoformat(r["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age_days = (today - created.date()).days
        bucket = (
            "0-7 days" if age_days <= 7 else ("8-30 days" if age_days <= 30 else "31+ days")
        )
        buckets[bucket]["exception_count"] += 1
        kinds = buckets[bucket]["kinds"]
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    return {"as_of": today.isoformat(), "buckets": buckets}


def review_backlog(conn: sqlite3.Connection) -> list[dict]:
    """Documents in needs_review with their unresolved fields and open
    exception kinds — the human work queue, oldest first."""
    backlog = []
    for doc in conn.execute(
        "SELECT * FROM docintel_documents WHERE state = 'needs_review' ORDER BY created_at, id"
    ).fetchall():
        unresolved = [
            r["field_name"]
            for r in conn.execute(
                "SELECT field_name FROM docintel_fields "
                "WHERE document_id = ? AND status != 'accepted' ORDER BY id",
                (doc["id"],),
            ).fetchall()
        ]
        kinds = sorted({
            r["kind"]
            for r in conn.execute(
                "SELECT kind FROM docintel_exceptions "
                "WHERE ref_public_id = ? AND state = 'open'",
                (doc["doc_id"],),
            ).fetchall()
        })
        backlog.append({
            "doc_id": doc["doc_id"],
            "doc_type": doc["doc_type"],
            "doc_confidence": doc["doc_confidence"],
            "unresolved_fields": unresolved,
            "open_exception_kinds": kinds,
        })
    return backlog


# ---------------------------------------------------------------------------
# Run log + structured stdout logging
# ---------------------------------------------------------------------------

def _record_run(
    conn: sqlite3.Connection,
    kind: str,
    stats: Mapping[str, Any],
    actor: str,
    moment: datetime,
) -> None:
    serializable = {
        k: (str(v) if isinstance(v, Decimal) else v) for k, v in stats.items()
    }
    conn.execute(
        "INSERT INTO docintel_runs (kind, stats_json, actor, created_at) "
        "VALUES (?, ?, ?, ?)",
        (kind, json.dumps(serializable, sort_keys=True), actor,
         moment.isoformat(timespec="seconds")),
    )
    conn.commit()


def _log(actor: str, event: str, detail: Mapping[str, Any]) -> None:
    print(
        json.dumps(
            {"ts": utcnow_iso(), "event": event, "actor": actor, "detail": dict(detail)},
            sort_keys=True,
        ),
        file=sys.stdout,
        flush=True,
    )
