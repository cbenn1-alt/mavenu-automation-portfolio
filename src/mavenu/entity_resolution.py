"""Project Q06 — Data Quality & Entity Resolution Service.

Pipeline: ingest -> normalize -> block -> score -> (human-gated) merge.

- **Ingest** (``ingest_source``): multiple CSV sources with header
  validation, row-level errors, CSV-formula sanitization, and idempotent
  inserts on (source label, source row).
- **Normalize** (``normalize_all``): deterministic cleaners from
  ``normalize.py`` recomputed over every contact. Idempotent by
  construction.
- **Block** (``build_blocks``): cheap equality keys — phone digits,
  lowercased email, zip+surname — so candidate pairs come from block
  co-occurrence instead of an O(n^2) all-pairs scan. Rebuilt from active
  contacts on every run.
- **Score** (``run_resolution`` + ``DeterministicDemoScorer``): weighted
  feature scorer behind the replaceable ``PairScorer`` protocol.
  Documented weights (see ``WEIGHTS``); documented thresholds
  (``MATCH_THRESHOLD`` / ``REVIEW_THRESHOLD``); match / review / no-match
  bands. A generational-suffix conflict (Jr vs Sr, or suffix present on
  only one side) applies a documented penalty so father/son records land
  in review, never in auto-merge territory.
- **Merge** (``propose_merge`` / ``confirm_merge`` / ``reject_proposal`` /
  ``reverse_merge``): the human gate. A resolve run only ever creates
  proposals in state ``proposed`` — **there is no code path that
  auto-confirms a merge**; ``confirm_merge`` requires a non-blank,
  non-"system" human actor. Every confirmed merge stores full pre-merge
  row images of winner and loser plus per-field provenance, so any merge
  is exactly reversible (``reverse_merge`` restores both rows byte-for-byte
  as stored).

ALL DATA IS SYNTHETIC DEMONSTRATION DATA. Real deployments must hash
blocking keys (see projects/project_q06/SECURITY.md) — this module stores
normalized values in the clear because the fixtures are fictional.
"""
from __future__ import annotations

import csv
import inspect
import io
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any, Mapping, Optional, Protocol

from . import normalize as norm
from .db import utcnow_iso

SCORER_VERSION = "q06-scorer/1"

# ---------------------------------------------------------------------------
# Documented scoring policy
# ---------------------------------------------------------------------------

#: Feature weights. They sum to 1.00; the total is a weighted sum of
#: per-feature similarities, each in 0.00..1.00.
WEIGHTS: dict[str, Decimal] = {
    "name": Decimal("0.45"),     # difflib ratio on name_key (token-sorted)
    "phone": Decimal("0.25"),    # 1.0 iff both phone_digits non-empty and equal
    "email": Decimal("0.15"),    # 1.0 iff both email_norm non-empty and equal
    "address": Decimal("0.10"),  # difflib ratio on address_norm
    "zip": Decimal("0.05"),      # 1.0 iff both zip_norm non-empty and equal
}

#: >= MATCH_THRESHOLD: merge PROPOSAL is created (never auto-confirmed).
MATCH_THRESHOLD = Decimal("0.85")
#: >= REVIEW_THRESHOLD (and < MATCH_THRESHOLD): human review band.
REVIEW_THRESHOLD = Decimal("0.60")
#: < REVIEW_THRESHOLD: no-match band — the pair is recorded, never proposed.

#: Penalty applied when the two records disagree on a generational suffix
#: (Jr/Sr/II/III/IV/V present on one side only, or different suffixes).
#: Documented adversarial guard: father/son records must not auto-merge.
SUFFIX_CONFLICT_PENALTY = Decimal("0.20")
_GENERATIONAL_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

#: Bands, in order of confidence.
BANDS = ("match", "review", "no_match")


class MergeError(Exception):
    """Domain error for the merge gate (bad state, bad actor, missing row)."""


# ---------------------------------------------------------------------------
# Scoring protocol
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PairScore:
    total: Decimal                  # 0.00..1.00, quantized to 2 decimals
    components: dict[str, str]      # component name -> Decimal as text
    reasons: list[str]              # human-readable, one per component
    scorer: str                     # scorer name + version


class PairScorer(Protocol):
    name: str

    def score(self, a: Mapping[str, Any], b: Mapping[str, Any]) -> PairScore:
        """Score two normalized contact rows. Pure function of inputs."""
        ...


class DeterministicDemoScorer:
    """Rule-based demonstration scorer.

    Pure function of its inputs: identical rows always produce an
    identical score (asserted by tests). NOT a trained model — a
    transparent weighted formula with documented weights. Replace with a
    real model-backed implementation of ``PairScorer`` when one exists.
    """

    name = "deterministic-demo-v1"

    def score(self, a: Mapping[str, Any], b: Mapping[str, Any]) -> PairScore:
        components: dict[str, str] = {}
        reasons: list[str] = []

        name_ratio = _ratio(str(a.get("name_key") or ""), str(b.get("name_key") or ""))
        name_part = (Decimal(str(name_ratio)) * WEIGHTS["name"]).quantize(Decimal("0.01"))
        components["name"] = str(name_part)
        reasons.append(
            f"name similarity {name_ratio:.2f} x weight {WEIGHTS['name']} = {name_part}"
        )

        phone_hit = _exact_hit(a.get("phone_digits"), b.get("phone_digits"))
        phone_part = WEIGHTS["phone"] if phone_hit else Decimal("0.00")
        components["phone"] = str(phone_part)
        reasons.append(
            "phone digits identical" if phone_hit else "phone digits differ or missing"
        )

        email_hit = _exact_hit(a.get("email_norm"), b.get("email_norm"))
        email_part = WEIGHTS["email"] if email_hit else Decimal("0.00")
        components["email"] = str(email_part)
        reasons.append(
            "email identical" if email_hit else "email differs or missing"
        )

        addr_ratio = _ratio(str(a.get("address_norm") or ""), str(b.get("address_norm") or ""))
        addr_part = (Decimal(str(addr_ratio)) * WEIGHTS["address"]).quantize(Decimal("0.01"))
        components["address"] = str(addr_part)
        reasons.append(
            f"address similarity {addr_ratio:.2f} x weight {WEIGHTS['address']} = {addr_part}"
        )

        zip_hit = _exact_hit(a.get("zip_norm"), b.get("zip_norm"))
        zip_part = WEIGHTS["zip"] if zip_hit else Decimal("0.00")
        components["zip"] = str(zip_part)
        reasons.append("zip identical" if zip_hit else "zip differs or missing")

        penalty = Decimal("0.00")
        if _suffix_conflict(str(a.get("name_key") or ""), str(b.get("name_key") or "")):
            penalty = SUFFIX_CONFLICT_PENALTY
            reasons.append(
                f"generational-suffix conflict: penalty -{SUFFIX_CONFLICT_PENALTY} "
                "(Jr/Sr style records must not auto-merge)"
            )
        components["suffix_penalty"] = str(-penalty)

        total = (name_part + phone_part + email_part + addr_part + zip_part - penalty)
        total = max(Decimal("0.00"), min(Decimal("1.00"), total)).quantize(Decimal("0.01"))
        return PairScore(
            total=total,
            components=components,
            reasons=reasons,
            scorer=f"{self.name}/{SCORER_VERSION}",
        )


def _ratio(left: str, right: str) -> float:
    """difflib similarity ratio in 0.0..1.0; 0.0 when either side is empty."""
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _exact_hit(left: Any, right: Any) -> bool:
    l, r = str(left or ""), str(right or "")
    return bool(l) and l == r


def _suffix_conflict(key_a: str, key_b: str) -> bool:
    """True when the generational-suffix sets differ (incl. one-sided)."""
    sa = {t for t in key_a.split() if t in _GENERATIONAL_SUFFIXES}
    sb = {t for t in key_b.split() if t in _GENERATIONAL_SUFFIXES}
    return sa != sb


def decide(total: Decimal) -> str:
    """Route a pair total into its band. Boundary-tested."""
    if total >= MATCH_THRESHOLD:
        return "match"
    if total >= REVIEW_THRESHOLD:
        return "review"
    return "no_match"


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

CONTACT_COLUMNS = ("name", "phone", "email", "address", "zip", "notes")
SOURCE_KINDS = ("spreadsheet", "form", "phone", "other")


def _now_or(now: Optional[datetime]) -> datetime:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _log(actor: str, event: str, detail: Mapping[str, Any]) -> None:
    print(
        json.dumps(
            {"ts": utcnow_iso(), "event": event, "actor": actor, "detail": dict(detail)},
            sort_keys=True,
        ),
        file=sys.stdout,
        flush=True,
    )


def _record_event(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: int,
    event_type: str,
    actor: str,
    from_state: Optional[str],
    to_state: Optional[str],
    detail: Mapping[str, Any],
    moment: datetime,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO er_events
            (entity_type, entity_id, event_type, actor, from_state, to_state,
             detail_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity_type, entity_id, event_type, actor, from_state, to_state,
            json.dumps(dict(detail), sort_keys=True),
            moment.isoformat(timespec="seconds"),
        ),
    )
    return cur.lastrowid


def _normalized_columns(raw: Mapping[str, str]) -> dict[str, str]:
    """Recompute every normalized column from raw values (pure function)."""
    return {
        "name_norm": norm.normalize_name(raw["name"]),
        "name_key": norm.name_key(raw["name"]),
        "phone_digits": norm.phone_digits(raw["phone"]),
        "email_norm": norm.normalize_email(raw["email"]),
        "address_norm": norm.normalize_address(raw["address"]),
        "zip_norm": norm.normalize_zip(raw["zip"]),
    }


def ingest_source(
    conn: sqlite3.Connection,
    *,
    label: str,
    source_kind: str,
    csv_text: str,
    actor: str = "system",
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Ingest one CSV source of contacts.

    Header validation is fatal (missing columns abort the whole ingest);
    row problems are collected as row-level errors and never abort the
    batch. Inserts are idempotent on (source label, source row): re-ingesting
    the same CSV inserts zero new rows.
    """
    moment = _now_or(now)
    label = (label or "").strip()
    if not label:
        raise ValueError("source label is required")
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"source_kind must be one of {SOURCE_KINDS}")

    reader = csv.DictReader(io.StringIO(csv_text or ""))
    headers = [h.strip() if h else "" for h in (reader.fieldnames or [])]
    missing = [c for c in CONTACT_COLUMNS if c not in headers]
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")

    cur = conn.execute(
        "INSERT OR IGNORE INTO er_sources (label, source_kind, ingested_at) "
        "VALUES (?, ?, ?)",
        (label, source_kind, moment.isoformat(timespec="seconds")),
    )
    source_id = cur.lastrowid or conn.execute(
        "SELECT id FROM er_sources WHERE label = ?", (label,)
    ).fetchone()["id"]

    inserted = 0
    skipped_idempotent = 0
    sanitized_cells = 0
    errors: list[dict[str, Any]] = []

    for lineno, row in enumerate(reader, start=1):
        try:
            raw: dict[str, str] = {}
            for col in CONTACT_COLUMNS:
                cell, was_sanitized = norm.sanitize_cell(row.get(col))
                if was_sanitized:
                    sanitized_cells += 1
                raw[col] = cell
            if not raw["name"]:
                raise ValueError("name is required")
            normalized = _normalized_columns(raw)
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO er_contacts
                    (source_id, source_row,
                     raw_name, raw_phone, raw_email, raw_address, raw_zip, raw_notes,
                     name_norm, name_key, phone_digits, email_norm, address_norm, zip_norm,
                     created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id, lineno,
                    raw["name"], raw["phone"], raw["email"], raw["address"],
                    raw["zip"], raw["notes"],
                    normalized["name_norm"], normalized["name_key"],
                    normalized["phone_digits"], normalized["email_norm"],
                    normalized["address_norm"], normalized["zip_norm"],
                    moment.isoformat(timespec="seconds"),
                ),
            )
            if cur.rowcount:
                inserted += 1
                _record_event(
                    conn, "contact", cur.lastrowid, "contact.ingested", actor,
                    None, "active",
                    {"source": label, "source_row": lineno}, moment,
                )
            else:
                skipped_idempotent += 1
        except ValueError as exc:
            errors.append({"row": lineno, "error": str(exc)})

    stats: dict[str, Any] = {
        "kind": "ingest",
        "source": label,
        "source_kind": source_kind,
        "inserted": inserted,
        "skipped_idempotent": skipped_idempotent,
        "sanitized_cells": sanitized_cells,
        "errors": errors,
    }
    conn.execute(
        "INSERT INTO er_runs (kind, stats_json, actor, created_at) VALUES (?, ?, ?, ?)",
        ("ingest", json.dumps(stats, sort_keys=True), actor,
         moment.isoformat(timespec="seconds")),
    )
    conn.commit()
    _log(actor, "entity_resolution.ingest", {k: v for k, v in stats.items() if k != "errors"})
    return stats


# ---------------------------------------------------------------------------
# Normalize stage
# ---------------------------------------------------------------------------

def normalize_all(conn: sqlite3.Connection) -> int:
    """Recompute normalized columns for every contact. Returns row count.

    Idempotent: normalized columns are a pure function of the raw columns,
    so re-running changes nothing (asserted by tests).
    """
    rows = conn.execute(
        "SELECT id, raw_name, raw_phone, raw_email, raw_address, raw_zip "
        "FROM er_contacts"
    ).fetchall()
    for r in rows:
        n = _normalized_columns({
            "name": r["raw_name"], "phone": r["raw_phone"], "email": r["raw_email"],
            "address": r["raw_address"], "zip": r["raw_zip"],
        })
        conn.execute(
            """
            UPDATE er_contacts
            SET name_norm = ?, name_key = ?, phone_digits = ?,
                email_norm = ?, address_norm = ?, zip_norm = ?
            WHERE id = ?
            """,
            (n["name_norm"], n["name_key"], n["phone_digits"],
             n["email_norm"], n["address_norm"], n["zip_norm"], r["id"]),
        )
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------
# Block stage
# ---------------------------------------------------------------------------

def block_keys_for(row: Mapping[str, Any]) -> list[str]:
    """Cheap equality keys for one normalized contact row.

    - ``phone:<digits>`` — same phone number, any format.
    - ``email:<lower>`` — same email, any case.
    - ``zipname:<zip>:<surname>`` — same ZIP + surname token (catches
      typo'd first names that phone/email blocks might miss).
    """
    keys: list[str] = []
    digits = str(row.get("phone_digits") or "")
    if digits:
        keys.append(f"phone:{digits}")
    email = str(row.get("email_norm") or "")
    if email:
        keys.append(f"email:{email}")
    zipn = str(row.get("zip_norm") or "")
    tokens = str(row.get("name_key") or "").split()
    if zipn and tokens:
        keys.append(f"zipname:{zipn}:{tokens[-1]}")
    return keys


def build_blocks(conn: sqlite3.Connection) -> dict[str, int]:
    """Rebuild the blocking index from active contacts. Returns counts.

    Merged-away contacts are excluded: they no longer participate in
    candidate generation.
    """
    conn.execute("DELETE FROM er_blocks")
    rows = conn.execute(
        "SELECT id, phone_digits, email_norm, zip_norm, name_key "
        "FROM er_contacts WHERE status = 'active' ORDER BY id"
    ).fetchall()
    block_rows = 0
    for r in rows:
        for key in block_keys_for(_row_dict(r)):
            conn.execute(
                "INSERT OR IGNORE INTO er_blocks (block_key, contact_id) VALUES (?, ?)",
                (key, r["id"]),
            )
            block_rows += 1
    distinct = conn.execute("SELECT COUNT(DISTINCT block_key) AS c FROM er_blocks").fetchone()["c"]
    conn.commit()
    return {"contacts_blocked": len(rows), "block_rows": block_rows, "distinct_blocks": distinct}


def pair_shares_block(conn: sqlite3.Connection, a_id: int, b_id: int) -> bool:
    """True when two contacts co-occur in at least one block."""
    row = conn.execute(
        """
        SELECT 1 FROM er_blocks x
        JOIN er_blocks y ON x.block_key = y.block_key
        WHERE x.contact_id = ? AND y.contact_id = ?
        LIMIT 1
        """,
        (a_id, b_id),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Score stage
# ---------------------------------------------------------------------------

def generate_pairs(conn: sqlite3.Connection) -> int:
    """Generate candidate pairs from block co-occurrence. Returns new pairs.

    Only pairs that share a block are generated — there is deliberately no
    all-pairs fallback, so pair count stays bounded by block structure
    (asserted by tests). INSERT OR IGNORE keeps re-runs idempotent.
    """
    new_pairs = 0
    block_keys = [
        r["block_key"]
        for r in conn.execute("SELECT DISTINCT block_key FROM er_blocks").fetchall()
    ]
    for key in block_keys:
        members = [
            r["contact_id"]
            for r in conn.execute(
                "SELECT contact_id FROM er_blocks WHERE block_key = ? ORDER BY contact_id",
                (key,),
            ).fetchall()
        ]
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO er_pairs (contact_a_id, contact_b_id, block_key)
                    VALUES (?, ?, ?)
                    """,
                    (members[i], members[j], key),
                )
                new_pairs += cur.rowcount
    conn.commit()
    return new_pairs


def score_pairs(
    conn: sqlite3.Connection,
    *,
    scorer: Optional[PairScorer] = None,
    now: Optional[datetime] = None,
) -> dict[str, int]:
    """Score every unscored pair and assign bands. Returns band counts."""
    scorer = scorer or DeterministicDemoScorer()
    moment = _now_or(now)
    counts = {"match": 0, "review": 0, "no_match": 0, "scored": 0}
    pairs = conn.execute(
        "SELECT id, contact_a_id, contact_b_id FROM er_pairs WHERE score IS NULL"
    ).fetchall()
    for p in pairs:
        a = conn.execute(
            "SELECT * FROM er_contacts WHERE id = ?", (p["contact_a_id"],)
        ).fetchone()
        b = conn.execute(
            "SELECT * FROM er_contacts WHERE id = ?", (p["contact_b_id"],)
        ).fetchone()
        result = scorer.score(_row_dict(a), _row_dict(b))
        band = decide(result.total)
        conn.execute(
            """
            UPDATE er_pairs
            SET score = ?, band = ?, score_detail_json = ?, scored_at = ?
            WHERE id = ?
            """,
            (
                str(result.total), band,
                json.dumps({
                    "scorer": result.scorer,
                    "components": result.components,
                    "reasons": result.reasons,
                }, sort_keys=True),
                moment.isoformat(timespec="seconds"), p["id"],
            ),
        )
        counts[band] += 1
        counts["scored"] += 1
    conn.commit()
    return counts


def run_resolution(
    conn: sqlite3.Connection,
    *,
    scorer: Optional[PairScorer] = None,
    actor: str = "system",
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Run the full pipeline: normalize -> block -> pairs -> score -> propose.

    Idempotent: re-running with no new data creates zero new pairs, scores
    zero new pairs, and creates zero new proposals. Merge proposals are
    created ONLY in state 'proposed' — this function never confirms a merge;
    there is no auto-confirm parameter and no auto-confirm code path.
    """
    moment = _now_or(now)
    scorer = scorer or DeterministicDemoScorer()

    normalized = normalize_all(conn)
    block_stats = build_blocks(conn)
    pairs_new = generate_pairs(conn)
    score_counts = score_pairs(conn, scorer=scorer, now=moment)

    # Proposals: one per match-band pair that has none yet. ALWAYS 'proposed'.
    proposals_created = 0
    match_pairs = conn.execute(
        """
        SELECT p.id FROM er_pairs p
        LEFT JOIN er_merge_proposals m ON m.pair_id = p.id
        WHERE p.band = 'match' AND m.id IS NULL
        """
    ).fetchall()
    for mp in match_pairs:
        _create_proposal(conn, mp["id"], proposed_by="system", moment=moment)
        proposals_created += 1

    active = conn.execute(
        "SELECT COUNT(*) AS c FROM er_contacts WHERE status = 'active'"
    ).fetchone()["c"]
    pairs_total = conn.execute("SELECT COUNT(*) AS c FROM er_pairs").fetchone()["c"]
    possible = active * (active - 1) // 2
    reduction = 1.0 - (pairs_total / possible) if possible else 0.0

    stats: dict[str, Any] = {
        "kind": "resolve",
        "scorer": f"{scorer.name}/{SCORER_VERSION}",
        "normalized": normalized,
        "blocks": block_stats,
        "pairs_new": pairs_new,
        "pairs_total": pairs_total,
        "pairs_scored": score_counts["scored"],
        "band_match": score_counts["match"],
        "band_review": score_counts["review"],
        "band_no_match": score_counts["no_match"],
        "proposals_created": proposals_created,
        "active_contacts": active,
        "possible_pairs": possible,
        "reduction_ratio": round(reduction, 4),
        "match_threshold": str(MATCH_THRESHOLD),
        "review_threshold": str(REVIEW_THRESHOLD),
    }
    conn.execute(
        "INSERT INTO er_runs (kind, stats_json, actor, created_at) VALUES (?, ?, ?, ?)",
        ("resolve", json.dumps(stats, sort_keys=True), actor,
         moment.isoformat(timespec="seconds")),
    )
    conn.commit()
    _log(actor, "entity_resolution.resolve", stats)
    return stats


def resolution_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Current pipeline snapshot for dashboards: bands, blocks, pairs."""
    bands = {b: 0 for b in BANDS}
    for r in conn.execute("SELECT band, COUNT(*) AS c FROM er_pairs GROUP BY band").fetchall():
        if r["band"]:
            bands[r["band"]] = r["c"]
    active = conn.execute(
        "SELECT COUNT(*) AS c FROM er_contacts WHERE status = 'active'"
    ).fetchone()["c"]
    pairs_total = conn.execute("SELECT COUNT(*) AS c FROM er_pairs").fetchone()["c"]
    possible = active * (active - 1) // 2
    proposals = {
        r["state"]: r["c"]
        for r in conn.execute(
            "SELECT state, COUNT(*) AS c FROM er_merge_proposals GROUP BY state"
        ).fetchall()
    }
    sources = conn.execute("SELECT COUNT(*) AS c FROM er_sources").fetchone()["c"]
    return {
        "sources": sources,
        "active_contacts": active,
        "merged_contacts": conn.execute(
            "SELECT COUNT(*) AS c FROM er_contacts WHERE status = 'merged'"
        ).fetchone()["c"],
        "distinct_blocks": conn.execute(
            "SELECT COUNT(DISTINCT block_key) AS c FROM er_blocks").fetchone()["c"],
        "pairs_total": pairs_total,
        "possible_pairs": possible,
        "reduction_ratio": round(1.0 - (pairs_total / possible), 4) if possible else 0.0,
        "bands": bands,
        "proposals": proposals,
        "match_threshold": str(MATCH_THRESHOLD),
        "review_threshold": str(REVIEW_THRESHOLD),
    }


# ---------------------------------------------------------------------------
# Merge gate: propose -> human confirm/reject -> audited merge -> reversible
# ---------------------------------------------------------------------------

_MERGE_FIELDS = ("name", "phone", "email", "address", "zip")

_PROPOSAL_TRANSITIONS = {
    "proposed": ("confirmed", "rejected"),
    "confirmed": ("reversed",),
    "rejected": (),
    "reversed": (),
}


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _contact(conn: sqlite3.Connection, contact_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM er_contacts WHERE id = ?", (contact_id,)).fetchone()
    if row is None:
        raise MergeError(f"contact {contact_id} does not exist")
    return row


def _choose_winner(a: Mapping[str, Any], b: Mapping[str, Any]) -> tuple[int, int, str]:
    """Pick the surviving record: more complete wins; ties go to lower id."""
    raws = [f"raw_{f}" for f in _MERGE_FIELDS]

    def completeness(row: Mapping[str, Any]) -> int:
        return sum(1 for f in raws if str(row.get(f) or "").strip())

    ca, cb = completeness(a), completeness(b)
    if ca == cb:
        winner, loser = (a, b) if a["id"] < b["id"] else (b, a)
        reason = f"equal completeness ({ca}/5 fields); lower id {winner['id']} survives"
    elif ca > cb:
        winner, loser, reason = a, b, f"record {a['id']} more complete ({ca}/5 vs {cb}/5)"
    else:
        winner, loser, reason = b, a, f"record {b['id']} more complete ({cb}/5 vs {ca}/5)"
    return winner["id"], loser["id"], reason


def _field_plan(
    winner: Mapping[str, Any], loser: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Per-field winning value with provenance: which record it came from."""
    plan: list[dict[str, Any]] = []
    for field in _MERGE_FIELDS:
        col = f"raw_{field}"
        vw, vl = str(winner.get(col) or ""), str(loser.get(col) or "")
        if vw == vl:
            plan.append({"field": field, "value": vw,
                         "from_contact_id": winner["id"],
                         "reason": "identical in both records"})
        elif not vw:
            plan.append({"field": field, "value": vl,
                         "from_contact_id": loser["id"],
                         "reason": "only present in the merged (loser) record"})
        elif not vl:
            plan.append({"field": field, "value": vw,
                         "from_contact_id": winner["id"],
                         "reason": "only present in the surviving (winner) record"})
        elif len(vl) > len(vw):
            plan.append({"field": field, "value": vl,
                         "from_contact_id": loser["id"],
                         "reason": "longer value kept"})
        else:
            plan.append({"field": field, "value": vw,
                         "from_contact_id": winner["id"],
                         "reason": "longer value kept"})
    return plan


def _create_proposal(
    conn: sqlite3.Connection, pair_id: int, *, proposed_by: str, moment: datetime
) -> int:
    pair = conn.execute("SELECT * FROM er_pairs WHERE id = ?", (pair_id,)).fetchone()
    if pair is None:
        raise MergeError(f"pair {pair_id} does not exist")
    if pair["band"] == "no_match":
        raise MergeError(
            f"pair {pair_id} is in the no-match band (score {pair['score']}); "
            "it cannot be proposed for merging"
        )
    exists = conn.execute(
        "SELECT id FROM er_merge_proposals WHERE pair_id = ?", (pair_id,)
    ).fetchone()
    if exists:
        raise MergeError(f"pair {pair_id} already has proposal {exists['id']}")
    a = _contact(conn, pair["contact_a_id"])
    b = _contact(conn, pair["contact_b_id"])
    winner_id, loser_id, reason = _choose_winner(_row_dict(a), _row_dict(b))
    winner = _row_dict(a) if winner_id == a["id"] else _row_dict(b)
    loser = _row_dict(b) if winner_id == a["id"] else _row_dict(a)
    plan = _field_plan(winner, loser)
    cur = conn.execute(
        """
        INSERT INTO er_merge_proposals
            (pair_id, winner_id, loser_id, state, proposed_by, proposed_at,
             field_plan_json)
        VALUES (?, ?, ?, 'proposed', ?, ?, ?)
        """,
        (pair_id, winner_id, loser_id, proposed_by,
         moment.isoformat(timespec="seconds"), json.dumps(plan, sort_keys=True)),
    )
    proposal_id = cur.lastrowid
    _record_event(conn, "proposal", proposal_id, "merge.proposed", proposed_by,
                  None, "proposed",
                  {"pair_id": pair_id, "winner_id": winner_id, "loser_id": loser_id,
                   "band": pair["band"], "score": pair["score"],
                   "winner_reason": reason}, moment)
    conn.commit()
    return proposal_id


def propose_merge(
    conn: sqlite3.Connection, pair_id: int, *, actor: str, note: str = "",
    now: Optional[datetime] = None,
) -> int:
    """Human proposes a merge for a review-band pair.

    ``run_resolution`` auto-proposes match-band pairs (as 'system'); this is
    the explicit human path for pairs the scorer put in review. No-match
    pairs can never be proposed.
    """
    moment = _now_or(now)
    actor = (actor or "").strip()
    if not actor:
        raise MergeError("proposing a merge requires a named actor")
    proposal_id = _create_proposal(conn, pair_id, proposed_by=actor, moment=moment)
    if note:
        conn.execute(
            "UPDATE er_merge_proposals SET decision_note = ? WHERE id = ?",
            (note, proposal_id),
        )
        conn.commit()
    _log(actor, "entity_resolution.merge_proposed",
         {"proposal_id": proposal_id, "pair_id": pair_id, "note": note})
    return proposal_id


def _require_human_actor(actor: str) -> str:
    cleaned = (actor or "").strip()
    if not cleaned or cleaned.lower() == "system":
        raise MergeError(
            "confirming a merge requires a named human actor "
            "(blank and 'system' are rejected by design — the human stays in the loop)"
        )
    return cleaned


def confirm_merge(
    conn: sqlite3.Connection, proposal_id: int, *, actor: str, note: str = "",
    now: Optional[datetime] = None,
) -> int:
    """Human confirms a proposed merge. Returns the merge-audit id.

    Applies the field plan to the winner, marks the loser merged, and stores
    full pre-merge row images of BOTH records plus per-field provenance —
    the merge is exactly reversible via ``reverse_merge``. There is no
    auto-confirm path: blank/'system' actors are rejected.
    """
    moment = _now_or(now)
    actor = _require_human_actor(actor)
    proposal = conn.execute(
        "SELECT * FROM er_merge_proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    if proposal is None:
        raise MergeError(f"proposal {proposal_id} does not exist")
    if proposal["state"] != "proposed":
        raise MergeError(
            f"proposal {proposal_id} is '{proposal['state']}'; "
            "only 'proposed' proposals can be confirmed"
        )
    winner = _contact(conn, proposal["winner_id"])
    loser = _contact(conn, proposal["loser_id"])
    if winner["status"] != "active" or loser["status"] != "active":
        raise MergeError(
            "both records must be active to merge "
            f"(winner {winner['id']}: {winner['status']}, "
            f"loser {loser['id']}: {loser['status']})"
        )

    winner_pre = _row_dict(winner)
    loser_pre = _row_dict(loser)
    plan: list[dict[str, Any]] = json.loads(proposal["field_plan_json"])

    # Apply the field plan to the winner, then re-derive normalized columns.
    merged_raw = {f: winner_pre[f"raw_{f}"] for f in _MERGE_FIELDS}
    provenance: list[dict[str, Any]] = []
    for item in plan:
        field = item["field"]
        merged_raw[field] = item["value"]
        provenance.append({
            "field": field,
            "value": item["value"],
            "from_contact_id": item["from_contact_id"],
            "reason": item["reason"],
        })
    normalized = _normalized_columns({
        "name": merged_raw["name"], "phone": merged_raw["phone"],
        "email": merged_raw["email"], "address": merged_raw["address"],
        "zip": merged_raw["zip"],
    })
    conn.execute(
        """
        UPDATE er_contacts
        SET raw_name = ?, raw_phone = ?, raw_email = ?, raw_address = ?, raw_zip = ?,
            name_norm = ?, name_key = ?, phone_digits = ?,
            email_norm = ?, address_norm = ?, zip_norm = ?
        WHERE id = ?
        """,
        (
            merged_raw["name"], merged_raw["phone"], merged_raw["email"],
            merged_raw["address"], merged_raw["zip"],
            normalized["name_norm"], normalized["name_key"], normalized["phone_digits"],
            normalized["email_norm"], normalized["address_norm"], normalized["zip_norm"],
            winner["id"],
        ),
    )
    conn.execute(
        "UPDATE er_contacts SET status = 'merged', merged_into = ? WHERE id = ?",
        (winner["id"], loser["id"]),
    )
    conn.execute(
        """
        UPDATE er_merge_proposals
        SET state = 'confirmed', decided_by = ?, decided_at = ?, decision_note = ?
        WHERE id = ?
        """,
        (actor, moment.isoformat(timespec="seconds"), note, proposal_id),
    )
    cur = conn.execute(
        """
        INSERT INTO er_merge_audit
            (proposal_id, winner_id, loser_id,
             winner_pre_image_json, loser_pre_image_json, field_provenance_json,
             merged_by, merged_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            proposal_id, winner["id"], loser["id"],
            json.dumps(winner_pre, sort_keys=True),
            json.dumps(loser_pre, sort_keys=True),
            json.dumps(provenance, sort_keys=True),
            actor, moment.isoformat(timespec="seconds"),
        ),
    )
    audit_id = cur.lastrowid
    _record_event(conn, "merge", audit_id, "merge.confirmed", actor,
                  "proposed", "confirmed",
                  {"proposal_id": proposal_id, "winner_id": winner["id"],
                   "loser_id": loser["id"], "note": note}, moment)
    conn.commit()
    _log(actor, "entity_resolution.merge_confirmed",
         {"proposal_id": proposal_id, "audit_id": audit_id,
          "winner_id": winner["id"], "loser_id": loser["id"]})
    return audit_id


def reject_proposal(
    conn: sqlite3.Connection, proposal_id: int, *, actor: str, note: str = "",
    now: Optional[datetime] = None,
) -> None:
    """Human rejects a proposed merge. The pair stays recorded; no data changes."""
    moment = _now_or(now)
    actor = _require_human_actor(actor)
    proposal = conn.execute(
        "SELECT * FROM er_merge_proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    if proposal is None:
        raise MergeError(f"proposal {proposal_id} does not exist")
    if proposal["state"] != "proposed":
        raise MergeError(
            f"proposal {proposal_id} is '{proposal['state']}'; "
            "only 'proposed' proposals can be rejected"
        )
    conn.execute(
        """
        UPDATE er_merge_proposals
        SET state = 'rejected', decided_by = ?, decided_at = ?, decision_note = ?
        WHERE id = ?
        """,
        (actor, moment.isoformat(timespec="seconds"), note, proposal_id),
    )
    _record_event(conn, "proposal", proposal_id, "merge.rejected", actor,
                  "proposed", "rejected",
                  {"pair_id": proposal["pair_id"], "note": note}, moment)
    conn.commit()
    _log(actor, "entity_resolution.merge_rejected",
         {"proposal_id": proposal_id, "note": note})


def reverse_merge(
    conn: sqlite3.Connection, proposal_id: int, *, actor: str,
    now: Optional[datetime] = None,
) -> None:
    """Reverse a confirmed merge, restoring both records' exact pre-images.

    The loser row is restored byte-for-byte as stored (status back to
    'active', merged_into cleared); the winner row is restored to its
    pre-merge image. The proposal moves to 'reversed' and the audit row is
    stamped — the audit trail itself is never deleted.
    """
    moment = _now_or(now)
    actor = _require_human_actor(actor)
    proposal = conn.execute(
        "SELECT * FROM er_merge_proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    if proposal is None:
        raise MergeError(f"proposal {proposal_id} does not exist")
    if proposal["state"] != "confirmed":
        raise MergeError(
            f"proposal {proposal_id} is '{proposal['state']}'; "
            "only 'confirmed' merges can be reversed"
        )
    audit = conn.execute(
        """
        SELECT * FROM er_merge_audit
        WHERE proposal_id = ? AND reversed_at IS NULL
        ORDER BY id DESC LIMIT 1
        """,
        (proposal_id,),
    ).fetchone()
    if audit is None:
        raise MergeError(f"proposal {proposal_id} has no reversible audit row")

    winner_pre: dict[str, Any] = json.loads(audit["winner_pre_image_json"])
    loser_pre: dict[str, Any] = json.loads(audit["loser_pre_image_json"])

    _restore_row(conn, winner_pre)
    _restore_row(conn, loser_pre)
    conn.execute(
        """
        UPDATE er_merge_proposals
        SET state = 'reversed', decided_by = ?, decided_at = ?
        WHERE id = ?
        """,
        (actor, moment.isoformat(timespec="seconds"), proposal_id),
    )
    conn.execute(
        "UPDATE er_merge_audit SET reversed_at = ?, reversed_by = ? WHERE id = ?",
        (moment.isoformat(timespec="seconds"), actor, audit["id"]),
    )
    _record_event(conn, "merge", audit["id"], "merge.reversed", actor,
                  "confirmed", "reversed",
                  {"proposal_id": proposal_id, "winner_id": proposal["winner_id"],
                   "loser_id": proposal["loser_id"]}, moment)
    conn.commit()
    _log(actor, "entity_resolution.merge_reversed",
         {"proposal_id": proposal_id, "audit_id": audit["id"]})


def _restore_row(conn: sqlite3.Connection, pre_image: Mapping[str, Any]) -> None:
    """Restore a contact row exactly from its stored pre-image."""
    conn.execute(
        """
        UPDATE er_contacts
        SET source_id = ?, source_row = ?,
            raw_name = ?, raw_phone = ?, raw_email = ?,
            raw_address = ?, raw_zip = ?, raw_notes = ?,
            name_norm = ?, name_key = ?, phone_digits = ?,
            email_norm = ?, address_norm = ?, zip_norm = ?,
            status = ?, merged_into = ?, created_at = ?
        WHERE id = ?
        """,
        (
            pre_image["source_id"], pre_image["source_row"],
            pre_image["raw_name"], pre_image["raw_phone"], pre_image["raw_email"],
            pre_image["raw_address"], pre_image["raw_zip"], pre_image["raw_notes"],
            pre_image["name_norm"], pre_image["name_key"], pre_image["phone_digits"],
            pre_image["email_norm"], pre_image["address_norm"], pre_image["zip_norm"],
            pre_image["status"], pre_image["merged_into"], pre_image["created_at"],
            pre_image["id"],
        ),
    )


# ---------------------------------------------------------------------------
# Read helpers (web/API)
# ---------------------------------------------------------------------------

def list_pairs(
    conn: sqlite3.Connection, *, band: Optional[str] = None, limit: int = 200
) -> list[dict[str, Any]]:
    """Pairs with both contacts' display names, newest-scored first."""
    query = """
        SELECT p.*, a.name_norm AS a_name, b.name_norm AS b_name
        FROM er_pairs p
        JOIN er_contacts a ON a.id = p.contact_a_id
        JOIN er_contacts b ON b.id = p.contact_b_id
    """
    params: list[Any] = []
    if band:
        if band not in BANDS:
            raise ValueError(f"band must be one of {BANDS}")
        query += " WHERE p.band = ?"
        params.append(band)
    query += " ORDER BY p.score DESC, p.id LIMIT ?"
    params.append(limit)
    return [_row_dict(r) for r in conn.execute(query, params).fetchall()]


def get_pair(conn: sqlite3.Connection, pair_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT p.*, a.name_norm AS a_name, b.name_norm AS b_name
        FROM er_pairs p
        JOIN er_contacts a ON a.id = p.contact_a_id
        JOIN er_contacts b ON b.id = p.contact_b_id
        WHERE p.id = ?
        """,
        (pair_id,),
    ).fetchone()
    if row is None:
        raise MergeError(f"pair {pair_id} does not exist")
    detail = _row_dict(row)
    detail["contact_a"] = _row_dict(_contact(conn, row["contact_a_id"]))
    detail["contact_b"] = _row_dict(_contact(conn, row["contact_b_id"]))
    return detail


def list_proposals(
    conn: sqlite3.Connection, *, state: Optional[str] = None
) -> list[dict[str, Any]]:
    query = """
        SELECT m.*, a.name_norm AS winner_name, b.name_norm AS loser_name,
               p.score AS pair_score, p.band AS pair_band
        FROM er_merge_proposals m
        JOIN er_contacts a ON a.id = m.winner_id
        JOIN er_contacts b ON b.id = m.loser_id
        JOIN er_pairs p ON p.id = m.pair_id
    """
    params: list[Any] = []
    if state:
        query += " WHERE m.state = ?"
        params.append(state)
    query += " ORDER BY m.id"
    return [_row_dict(r) for r in conn.execute(query, params).fetchall()]


def get_proposal(conn: sqlite3.Connection, proposal_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM er_merge_proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    if row is None:
        raise MergeError(f"proposal {proposal_id} does not exist")
    detail = _row_dict(row)
    pair = conn.execute(
        "SELECT score AS pair_score, band AS pair_band FROM er_pairs WHERE id = ?",
        (row["pair_id"],),
    ).fetchone()
    detail["pair_score"] = pair["pair_score"]
    detail["pair_band"] = pair["pair_band"]
    detail["winner"] = _row_dict(_contact(conn, row["winner_id"]))
    detail["loser"] = _row_dict(_contact(conn, row["loser_id"]))
    detail["field_plan"] = json.loads(row["field_plan_json"])
    detail["audit"] = [
        _row_dict(r) for r in conn.execute(
            "SELECT id, proposal_id, winner_id, loser_id, merged_by, merged_at, "
            "reversed_at, reversed_by FROM er_merge_audit WHERE proposal_id = ? "
            "ORDER BY id",
            (proposal_id,),
        ).fetchall()
    ]
    return detail


def merge_audit_view(conn: sqlite3.Connection, proposal_id: int) -> dict[str, Any]:
    """Before/after audit view for one merge: pre-images + provenance."""
    audit = conn.execute(
        "SELECT * FROM er_merge_audit WHERE proposal_id = ? ORDER BY id DESC LIMIT 1",
        (proposal_id,),
    ).fetchone()
    if audit is None:
        raise MergeError(f"proposal {proposal_id} has no merge audit row")
    return {
        "audit_id": audit["id"],
        "proposal_id": proposal_id,
        "winner_pre_image": json.loads(audit["winner_pre_image_json"]),
        "loser_pre_image": json.loads(audit["loser_pre_image_json"]),
        "field_provenance": json.loads(audit["field_provenance_json"]),
        "merged_by": audit["merged_by"],
        "merged_at": audit["merged_at"],
        "reversed_at": audit["reversed_at"],
        "reversed_by": audit["reversed_by"],
    }


def proposal_events(conn: sqlite3.Connection, proposal_id: int) -> list[dict[str, Any]]:
    """Audit events for one proposal (proposal events + its merge events)."""
    out: list[dict[str, Any]] = []
    for r in conn.execute(
        "SELECT * FROM er_events "
        "WHERE entity_type IN ('proposal', 'merge') ORDER BY id"
    ).fetchall():
        row = _row_dict(r)
        if row["entity_type"] == "proposal" and row["entity_id"] == proposal_id:
            out.append(row)
            continue
        try:
            detail = json.loads(row["detail_json"] or "{}")
        except ValueError:
            continue
        if detail.get("proposal_id") == proposal_id:
            out.append(row)
    return out


# Introspection guard: the resolve entry point must never grow an
# auto-confirm switch. Tested in tests/test_entity_resolution.py.
def _resolve_has_no_auto_confirm() -> bool:
    params = inspect.signature(run_resolution).parameters
    return not any("auto" in name or "confirm" in name for name in params)
