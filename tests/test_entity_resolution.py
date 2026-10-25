"""Tests for Q06 — Data Quality & Entity Resolution Service.

All contact data below is synthetic fixture data (invented names, phone
numbers, emails, addresses). No real people, no real PII.

Fixture design (see projects/project_q06/TEST_PLAN.md):
- 20 planted TRUE duplicate pairs across three sources (typos, format
  variants, token reordering, missing fields on one side).
- 5 adversarial NON-duplicate fixtures: twins (same household, near-name),
  Jr./Sr. (suffix conflict), shared phone (family plan), household members
  (spouses), similar names/different people (scorer unit test only).
- 4 unique contacts with no duplicates.
"""
import csv
import io
import json
from decimal import Decimal

import pytest

from mavenu import normalize as norm
from mavenu import entity_resolution as er
from mavenu.db import rollback_migration, run_migrations

HEADER = ["name", "phone", "email", "address", "zip", "notes"]


def make_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HEADER)
    w.writeheader()
    for r in rows:
        w.writerow({h: r[i] if i < len(r) else "" for i, h in enumerate(HEADER)})
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fixture rows: (name, phone, email, address, zip[, notes])
# ---------------------------------------------------------------------------

A_ROWS = [
    # 20 planted duplicates, source A side
    ("Marcus Bell", "(701) 555-0100", "marcus.bell@example.com", "42 Prairie Lane", "58102"),
    ("Jonathan Smith", "(701) 555-0101", "jonathan.smith@example.com", "15 Oak Street", "58103"),
    ("Priya Nair", "+1 (701) 555-0102", "priya.nair@example.com", "8 Birch Avenue", "58104"),
    ("Daniel Osei", "(701) 555-0103", "daniel.osei@example.com", "220 5th Street North", "58102"),
    ("Grace Adeyemi", "(701) 555-0104", "", "77 River Drive", "58105"),
    ("Elena Vasquez", "(701) 555-0105", "elena.vasquez@example.com", "9 Elm Court", "58102"),
    ("Tom Becker", "(701) 555-0106", "tom.becker@example.com", "301 Main Street", "58103"),
    ("Karen Doyle", "(701) 555-0107", "karen.doyle@example.com", "55 Lake Place", "58104"),
    ("Sam Whitfield", "(701) 555-0108", "sam.whitfield@example.com", "12 Cedar Terrace", "58105"),
    ("Nina Kowalski", "(701) 555-0109", "nina.kowalski@example.com", "400 2nd Avenue", "58102"),
    ("Omar Farouk", "(701) 555-0110", "omar.farouk@example.com", "18 Hill Road", "58103"),
    ("Beatrice Lang", "(701) 555-0111", "beatrice.lang@example.com", "63 Pine Circle", "58104"),
    ("Victor Mensah", "(701) 555-0112", "victor.mensah@example.com", "27 Grand Boulevard", "58105"),
    ("Hannah Lindqvist", "(701) 555-0113", "hannah.lindqvist@example.com", "5 Aspen Way", "58102"),
    ("James P Carter", "(701) 555-0114", "james.carter@example.com", "90 Summit Drive", "58103"),
    ("Ruth Abramowitz", "(701) 555-0115", "ruth.abramowitz@example.com", "33 Willow Lane", "58104"),
    ("Mary-Jane O'Connor", "(701) 555-0116", "maryjane.oconnor@example.com", "71 Cherry Street", "58105"),
    ("Peter Novak", "(701) 555-0117", "peter.novak@example.com", "200 University Drive", "58102"),
    ("Laura Bennett", "(701) 555-0118", "laura.bennett@example.com", "11 Park Place", "58103"),
    ("George Papas", "(701) 555-0119", "george.papas@example.com", "6 Depot Street", "58104"),
    # adversarial A sides: twins / Jr/Sr / shared-phone / household / similar-name
    ("Emma Carter", "(701) 555-0200", "emma.carter@example.com", "14 Rose Street", "58102"),
    ("Robert Hale Jr", "(701) 555-0201", "robert.hale@example.com", "30 Mill Road", "58103"),
    ("Nina Patel", "(701) 555-0202", "nina.patel@example.com", "50 1st Avenue", "58102"),
    ("Daniel Okafor", "(701) 555-0203", "daniel.okafor@example.com", "7 Cottonwood Lane", "58104"),
    ("James Liu", "(701) 555-0204", "james.liu@example.com", "3 North Street", "58102"),
    # unique contacts (no duplicates anywhere)
    ("Quinn Alvarez", "(701) 555-0300", "quinn.alvarez@example.com", "1 Solo Street", "58106"),
    ("Rosa Jimenez", "(701) 555-0301", "rosa.jimenez@example.com", "2 Solo Street", "58107"),
]

B_ROWS = [
    # 20 planted duplicates, source B side (dup10 and dup20 live in source C)
    ("  MARCUS  bell ", "7015550100", "Marcus.Bell@Example.com", "42 prairie ln", "58102"),
    ("Jonathon Smith", "701-555-0101", "jonathan.smith@example.com", "15 Oak St", "58103"),
    ("Priya Nair", "701.555.0102", "PRIYA.NAIR@EXAMPLE.COM", "8 Birch Ave", "58104-1234"),
    ("Daniel Osei", "(701) 555-0103", "daniel.osei@example.com", "220 5th St North", "58102"),
    ("Grace Adeyemi", "7015550104", "grace.adeyemi@example.com", "77 River Dr", "58105"),
    ("Vasquez, Elena", "7015550105", "elena.vasquez@example.com", "9 Elm Ct", "58102"),
    ("Tom Becker", "7015550106", "tom.becker@example.com", "", "58103"),
    ("Karen Doyle", "7015550107", "karen.doyle@example.com", "55 Lake Pl", "58104"),
    ("Sam Whitfeld", "7015550108", "sam.whitfield@example.com", "12 Cedar Ter", "58105"),
    ("Omar Farouk", "(701) 555-0110", "omar.farouk@example.com", "18 Hill Rd", "58103"),
    ("Beatirce Lang", "7015550111", "beatrice.lang@example.com", "63 Pine Cir", "58104"),
    ("Victor Mensah", "701.555.0112", "victor.mensah@example.com", "27 Grand Blvd", "58105"),
    ("Hannah Lindqvist", "7015550113", "hannah.lindqvist@example.com", "5 Aspen Way", "58102", "form signup"),
    ("James Carter", "7015550114", "james.carter@example.com", "90 Summit Dr", "58103"),
    ("Ruth Abramowitz", "(701) 555-0115", "ruth.abramowitz@example.com", "33 Willow Ln", "58104"),
    ("Mary Jane Oconnor", "7015550116", "maryjane.oconnor@example.com", "71 Cherry St", "58105"),
    ("Peter Novak", "7015550117", "peter.novak@example.com", "200 University Dr", "58102"),
    ("Laura Bennet", "7015550118", "laura.bennett@example.com", "11 Park Pl", "58103"),
    # adversarial B sides
    ("Emily Carter", "(701) 555-0200", "emily.carter@example.com", "14 Rose Street", "58102"),
    ("Robert Hale Sr", "(701) 555-0201", "robert.hale@example.com", "30 Mill Road", "58103"),
    ("Omar Haddad", "(701) 555-0202", "omar.haddad@example.com", "99 9th Avenue", "58102"),
    ("Grace Okafor", "(701) 555-0203", "grace.okafor@example.com", "7 Cottonwood Lane", "58104"),
    ("James Lu", "(701) 555-0205", "james.lu@example.com", "88 South Street", "58102"),
    # unique contacts
    ("Leo Fischer", "(701) 555-0302", "leo.fischer@example.com", "3 Solo Street", "58108"),
    ("Mia Rossi", "(701) 555-0303", "mia.rossi@example.com", "4 Solo Street", "58109"),
]

C_ROWS = [
    ("Nina Kowalski", "7015550109", "", "400 2nd Ave", "58102", "called about furnace"),
    ("George Papas", "7015550119", "george.papas@example.com", "6 Depot St", "", "from phone export"),
]


@pytest.fixture
def er_conn(conn):
    """conn (all migrations applied) with the Q06 fixture ingested + resolved."""
    er.ingest_source(conn, label="spreadsheet-customers", source_kind="spreadsheet",
                     csv_text=make_csv(A_ROWS), actor="test")
    er.ingest_source(conn, label="form-tool-signups", source_kind="form",
                     csv_text=make_csv(B_ROWS), actor="test")
    er.ingest_source(conn, label="phone-export", source_kind="phone",
                     csv_text=make_csv(C_ROWS), actor="test")
    stats = er.run_resolution(conn, actor="test")
    ids = {}
    for label, key in (("spreadsheet-customers", "a"), ("form-tool-signups", "b"),
                       ("phone-export", "c")):
        ids[key] = [
            r["id"] for r in conn.execute(
                "SELECT id FROM er_contacts WHERE source_id = "
                "(SELECT id FROM er_sources WHERE label = ?) ORDER BY source_row",
                (label,),
            ).fetchall()
        ]
    return conn, ids, stats


def dup_pairs(ids):
    """The 20 planted true-duplicate (a_id, b_id) pairs."""
    a, b, c = ids["a"], ids["b"], ids["c"]
    pairs = [(a[i], b[i]) for i in range(9)]          # dups 1..9 (A/B)
    pairs.append((a[9], c[0]))                        # dup 10 (A/C)
    pairs += [(a[i], b[i - 1]) for i in range(10, 19)]  # dups 11..19 (A/B)
    pairs.append((a[19], c[1]))                        # dup 20 (A/C)
    return pairs


def adv_pair_ids(ids, which):
    """Adversarial pair ids: 'twins', 'jrsr', 'shared_phone', 'household'."""
    a, b = ids["a"], ids["b"]
    return {
        "twins": (a[20], b[18]),
        "jrsr": (a[21], b[19]),
        "shared_phone": (a[22], b[20]),
        "household": (a[23], b[21]),
    }[which]


def pair_band(conn, a_id, b_id):
    row = conn.execute(
        "SELECT band, score FROM er_pairs "
        "WHERE (contact_a_id = ? AND contact_b_id = ?) "
        "   OR (contact_a_id = ? AND contact_b_id = ?)",
        (a_id, b_id, b_id, a_id),
    ).fetchone()
    return (row["band"], row["score"]) if row else (None, None)


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------

def test_normalize_name_cases():
    assert norm.normalize_name("  MARCUS   bell ") == "Marcus Bell"
    assert norm.normalize_name("O'CONNOR") == "O'Connor"
    assert norm.normalize_name("") == ""
    assert norm.normalize_name(None) == ""


def test_name_key_token_sort_and_punctuation():
    assert norm.name_key("Bell, Marcus") == "bell marcus"
    assert norm.name_key("marcus bell") == "bell marcus"
    assert norm.name_key("Mary-Jane O'Connor") == "maryjane oconnor"
    assert norm.name_key("  ") == ""


def test_normalize_phone_cases():
    assert norm.normalize_phone("(701) 555-0142") == "(701) 555-0142"
    assert norm.normalize_phone("7015550142") == "(701) 555-0142"
    assert norm.normalize_phone("+1 701-555-0142") == "(701) 555-0142"
    assert norm.normalize_phone("701.555.0142") == "(701) 555-0142"
    # unverifiable formats are kept as bare digits, never guessed
    assert norm.normalize_phone("555-0142") == "5550142"
    assert norm.normalize_phone("") == ""


def test_phone_digits_strips_nanp_country_code():
    assert norm.phone_digits("(701) 555-0142") == "7015550142"
    assert norm.phone_digits("+1 (701) 555-0142") == "7015550142"
    assert norm.phone_digits("") == ""


def test_normalize_email_cases():
    assert norm.normalize_email("  Marcus.Bell@Example.COM ") == "marcus.bell@example.com"
    assert norm.normalize_email("") == ""


def test_normalize_address_suffix_expansion():
    assert norm.normalize_address("  42 prairie LN ") == "42 Prairie Lane"
    assert norm.normalize_address("123 main st") == "123 Main Street"
    assert norm.normalize_address("8 Birch Ave") == "8 Birch Avenue"
    assert norm.normalize_address("9 Elm Ct") == "9 Elm Court"
    assert norm.normalize_address("63 Pine Cir") == "63 Pine Circle"
    assert norm.normalize_address("") == ""


def test_normalize_zip_cases():
    assert norm.normalize_zip("58102-4301") == "58102"
    assert norm.normalize_zip(" 58102 ") == "58102"
    assert norm.normalize_zip("") == ""


def test_sanitize_cell_neutralizes_formulas():
    val, flag = norm.sanitize_cell("=1+1")
    assert val == "'=1+1" and flag is True
    val, flag = norm.sanitize_cell("@mention")
    assert flag is True
    val, flag = norm.sanitize_cell("plain text")
    assert (val, flag) == ("plain text", False)


@pytest.mark.parametrize("fn", [
    norm.normalize_name, norm.name_key, norm.normalize_phone,
    norm.phone_digits, norm.normalize_email, norm.normalize_address,
    norm.normalize_zip,
])
@pytest.mark.parametrize("value", [
    "  MARCUS   bell ", "(701) 555-0142", "+1 701-555-0142",
    "Marcus.Bell@Example.COM", "42 prairie LN", "58102-4301",
    "Mary-Jane O'Connor", "Vasquez, Elena", "555-0142", "",
])
def test_normalizers_idempotent(fn, value):
    """normalize(normalize(x)) == normalize(x) for every cleaner."""
    once = fn(value)
    assert fn(once) == once


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def test_ingest_happy_path(conn):
    stats = er.ingest_source(conn, label="s1", source_kind="spreadsheet",
                             csv_text=make_csv(A_ROWS[:3]), actor="test")
    assert stats["inserted"] == 3
    assert stats["errors"] == []
    row = conn.execute("SELECT * FROM er_contacts WHERE source_row = 1").fetchone()
    assert row["raw_name"] == "Marcus Bell"
    assert row["name_norm"] == "Marcus Bell"
    assert row["name_key"] == "bell marcus"
    assert row["phone_digits"] == "7015550100"
    assert row["email_norm"] == "marcus.bell@example.com"
    assert row["address_norm"] == "42 Prairie Lane"
    assert row["zip_norm"] == "58102"
    assert row["status"] == "active"


def test_ingest_missing_columns_is_fatal(conn):
    with pytest.raises(ValueError, match="missing required columns"):
        er.ingest_source(conn, label="bad", source_kind="spreadsheet",
                         csv_text="name,phone\nA,1\n", actor="test")
    assert conn.execute("SELECT COUNT(*) AS c FROM er_sources").fetchone()["c"] == 0


def test_ingest_row_errors_do_not_abort_batch(conn):
    rows = [("Good Person", "7015550000", "g@example.com", "1 Main St", "58102"),
            ("", "7015550001", "bad@example.com", "2 Main St", "58102"),  # no name
            ("Another Good", "7015550002", "a@example.com", "3 Main St", "58102")]
    stats = er.ingest_source(conn, label="s2", source_kind="form",
                             csv_text=make_csv(rows), actor="test")
    assert stats["inserted"] == 2
    assert len(stats["errors"]) == 1
    assert stats["errors"][0]["row"] == 2
    assert "name is required" in stats["errors"][0]["error"]


def test_ingest_reingest_is_idempotent(conn):
    kw = dict(label="s3", source_kind="spreadsheet", csv_text=make_csv(A_ROWS[:2]),
              actor="test")
    first = er.ingest_source(conn, **kw)
    second = er.ingest_source(conn, **kw)
    assert first["inserted"] == 2
    assert second["inserted"] == 0
    assert second["skipped_idempotent"] == 2
    assert conn.execute("SELECT COUNT(*) AS c FROM er_contacts").fetchone()["c"] == 2


def test_ingest_sanitizes_formula_cells(conn):
    rows = [("=HYPERLINK Evil", "7015550000", "g@example.com", "1 Main St", "58102")]
    stats = er.ingest_source(conn, label="s4", source_kind="spreadsheet",
                             csv_text=make_csv(rows), actor="test")
    assert stats["sanitized_cells"] == 1
    row = conn.execute("SELECT raw_name FROM er_contacts").fetchone()
    assert row["raw_name"] == "'=HYPERLINK Evil"


def test_ingest_rejects_bad_source_kind(conn):
    with pytest.raises(ValueError, match="source_kind"):
        er.ingest_source(conn, label="s5", source_kind="carrier-pigeon",
                         csv_text=make_csv(A_ROWS[:1]), actor="test")


# ---------------------------------------------------------------------------
# Blocking
# ---------------------------------------------------------------------------

def test_block_keys_for_shapes():
    row = {"phone_digits": "7015550100", "email_norm": "a@example.com",
           "zip_norm": "58102", "name_key": "bell marcus"}
    keys = er.block_keys_for(row)
    assert "phone:7015550100" in keys
    assert "email:a@example.com" in keys
    assert "zipname:58102:marcus" in keys  # surname = last token of sorted key
    # empty fields produce no keys
    assert er.block_keys_for(
        {"phone_digits": "", "email_norm": "", "zip_norm": "", "name_key": ""}) == []


def test_block_coverage_on_planted_duplicates(er_conn):
    """Every planted duplicate pair shares at least one block (coverage)."""
    conn, ids, _ = er_conn
    pairs = dup_pairs(ids)
    missed = [(a, b) for a, b in pairs if not er.pair_shares_block(conn, a, b)]
    assert missed == [], f"{len(missed)} planted pairs share no block"
    coverage = (len(pairs) - len(missed)) / len(pairs)
    assert coverage == 1.0


def test_every_pair_shares_a_block(er_conn):
    """Blocking correctness: no pair exists without a shared block."""
    conn, _, _ = er_conn
    orphans = conn.execute(
        """
        SELECT p.id FROM er_pairs p
        WHERE NOT EXISTS (
            SELECT 1 FROM er_blocks x
            JOIN er_blocks y ON x.block_key = y.block_key
            WHERE x.contact_id = p.contact_a_id AND y.contact_id = p.contact_b_id
        )
        """
    ).fetchall()
    assert orphans == []


def test_pair_count_bounded_no_o2_fallback(er_conn):
    """Pairs come only from blocks: strictly fewer than all possible pairs."""
    conn, _, stats = er_conn
    assert stats["pairs_total"] < stats["possible_pairs"]
    assert stats["reduction_ratio"] > 0.9  # 24 pairs vs 1485 possible
    # unique contacts share no blocks with anyone -> they generate no pairs
    unique_ids = conn.execute(
        "SELECT id FROM er_contacts WHERE raw_name IN "
        "('Quinn Alvarez','Rosa Jimenez','Leo Fischer','Mia Rossi')"
    ).fetchall()
    for r in unique_ids:
        n = conn.execute(
            "SELECT COUNT(*) AS c FROM er_pairs "
            "WHERE contact_a_id = ? OR contact_b_id = ?", (r["id"], r["id"])
        ).fetchone()["c"]
        assert n == 0


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def test_decide_boundaries():
    assert er.decide(Decimal("1.00")) == "match"
    assert er.decide(Decimal("0.85")) == "match"      # inclusive high threshold
    assert er.decide(Decimal("0.849")) == "review"
    assert er.decide(Decimal("0.60")) == "review"     # inclusive review threshold
    assert er.decide(Decimal("0.599")) == "no_match"
    assert er.decide(Decimal("0.00")) == "no_match"


def test_scorer_weights_documented_and_sum_to_one():
    assert sum(er.WEIGHTS.values()) == Decimal("1.00")
    assert set(er.WEIGHTS) == {"name", "phone", "email", "address", "zip"}
    assert er.MATCH_THRESHOLD == Decimal("0.85")
    assert er.REVIEW_THRESHOLD == Decimal("0.60")


def test_scorer_deterministic(er_conn):
    conn, ids, _ = er_conn
    a_id, b_id = dup_pairs(ids)[0]
    a = conn.execute("SELECT * FROM er_contacts WHERE id = ?", (a_id,)).fetchone()
    b = conn.execute("SELECT * FROM er_contacts WHERE id = ?", (b_id,)).fetchone()
    scorer = er.DeterministicDemoScorer()
    first, second = scorer.score(dict(a), dict(b)), scorer.score(dict(a), dict(b))
    assert first.total == second.total
    assert first.components == second.components


def test_scorer_is_replaceable_protocol(conn):
    """A custom PairScorer implementation drives run_resolution."""
    er.ingest_source(conn, label="rp", source_kind="spreadsheet",
                     csv_text=make_csv([
                         ("Ann Lowe", "7015550400", "ann.lowe@example.com", "1 Main St", "58102"),
                         ("Ann  Lowe", "7015550400", "ann.lowe@example.com", "1 Main Street", "58102"),
                     ]), actor="test")

    class AlwaysMatch:
        name = "always-match-test"

        def score(self, a, b):
            return er.PairScore(total=Decimal("0.90"), components={},
                                reasons=["test double"], scorer="test/1")

    stats = er.run_resolution(conn, scorer=AlwaysMatch(), actor="test")
    assert stats["pairs_scored"] == 1
    assert stats["band_match"] == 1
    assert stats["proposals_created"] == 1
    detail = json.loads(conn.execute(
        "SELECT score_detail_json FROM er_pairs").fetchone()["score_detail_json"])
    assert detail["scorer"] == "test/1"


def test_suffix_conflict_penalty_applies():
    """Jr/Sr pair is penalized exactly SUFFIX_CONFLICT_PENALTY vs control."""
    scorer = er.DeterministicDemoScorer()

    def row(name):
        return {"name_key": norm.name_key(name), "phone_digits": "7015550201",
                "email_norm": "robert.hale@example.com",
                "address_norm": "30 Mill Road", "zip_norm": "58103"}

    penalized = scorer.score(row("Robert Hale Jr"), row("Robert Hale Sr"))
    control = scorer.score(row("Robert Hale"), row("Robert Hale"))
    assert penalized.components["suffix_penalty"] == str(-er.SUFFIX_CONFLICT_PENALTY)
    assert control.components["suffix_penalty"] == "0.00"
    assert er.decide(penalized.total) == "review"  # would be match without penalty
    assert er.decide(control.total) == "match"


def test_precision_recall_on_fixtures(er_conn):
    """Recall >= 95% on the 20 planted duplicates; precision reported honestly."""
    conn, ids, _ = er_conn
    pairs = dup_pairs(ids)
    matched = sum(1 for a, b in pairs if pair_band(conn, a, b)[0] == "match")
    recall = matched / len(pairs)

    match_pairs = conn.execute(
        "SELECT contact_a_id, contact_b_id FROM er_pairs WHERE band = 'match'"
    ).fetchall()
    planted = {tuple(sorted(p)) for p in pairs}
    true_positives = sum(
        1 for r in match_pairs
        if tuple(sorted((r["contact_a_id"], r["contact_b_id"]))) in planted
    )
    precision = true_positives / len(match_pairs) if match_pairs else 0.0

    assert recall >= 0.95, f"recall {recall:.3f} below 0.95"
    # Honest report (also recorded in TEST_RESULTS.md):
    print(f"\nQ06 fixture: recall={recall:.3f} ({matched}/{len(pairs)}), "
          f"precision={precision:.3f} ({true_positives}/{len(match_pairs)})")
    assert matched == 20 and true_positives == 20  # measured, not assumed


# ---------------------------------------------------------------------------
# Adversarial fixtures
# ---------------------------------------------------------------------------

def test_adversarial_twins_land_in_review_not_match(er_conn):
    conn, ids, _ = er_conn
    band, score = pair_band(conn, *adv_pair_ids(ids, "twins"))
    assert band == "review", f"twins scored {score} -> {band}"
    # review-band pairs get NO automatic merge proposal
    n = conn.execute(
        "SELECT COUNT(*) AS c FROM er_merge_proposals m "
        "JOIN er_pairs p ON p.id = m.pair_id "
        "WHERE ((p.contact_a_id = ? AND p.contact_b_id = ?) "
        "   OR (p.contact_a_id = ? AND p.contact_b_id = ?))",
        (*adv_pair_ids(ids, "twins"), *adv_pair_ids(ids, "twins")[::-1]),
    ).fetchone()["c"]
    assert n == 0


def test_adversarial_jr_sr_land_in_review_not_match(er_conn):
    conn, ids, _ = er_conn
    band, score = pair_band(conn, *adv_pair_ids(ids, "jrsr"))
    assert band == "review", f"Jr/Sr scored {score} -> {band}"


def test_adversarial_shared_phone_is_no_match(er_conn):
    """A shared phone number alone never merges two different people."""
    conn, ids, _ = er_conn
    band, score = pair_band(conn, *adv_pair_ids(ids, "shared_phone"))
    assert band == "no_match", f"shared phone scored {score} -> {band}"


def test_adversarial_household_members_land_in_review(er_conn):
    conn, ids, _ = er_conn
    band, score = pair_band(conn, *adv_pair_ids(ids, "household"))
    assert band == "review", f"household scored {score} -> {band}"


def test_adversarial_similar_names_scorer_unit():
    """James Liu vs James Lu: different people -> no_match (scorer unit)."""
    scorer = er.DeterministicDemoScorer()

    def row(name, phone, email, address):
        return {"name_key": norm.name_key(name), "phone_digits": norm.phone_digits(phone),
                "email_norm": norm.normalize_email(email),
                "address_norm": norm.normalize_address(address),
                "zip_norm": norm.normalize_zip("58102")}

    s = scorer.score(
        row("James Liu", "(701) 555-0204", "james.liu@example.com", "3 North Street"),
        row("James Lu", "(701) 555-0205", "james.lu@example.com", "88 South Street"),
    )
    assert er.decide(s.total) == "no_match"


def test_no_automatic_proposals_outside_match_band(er_conn):
    conn, _, _ = er_conn
    rows = conn.execute(
        "SELECT m.id FROM er_merge_proposals m "
        "JOIN er_pairs p ON p.id = m.pair_id WHERE p.band != 'match'"
    ).fetchall()
    assert rows == []


# ---------------------------------------------------------------------------
# Merge gate
# ---------------------------------------------------------------------------

def _proposal_for_pair(conn, a_id, b_id):
    return conn.execute(
        "SELECT m.* FROM er_merge_proposals m JOIN er_pairs p ON p.id = m.pair_id "
        "WHERE (p.contact_a_id = ? AND p.contact_b_id = ?) "
        "   OR (p.contact_a_id = ? AND p.contact_b_id = ?)",
        (a_id, b_id, b_id, a_id),
    ).fetchone()


def test_run_never_confirms_merges(er_conn):
    """The resolve pipeline only ever creates 'proposed' proposals."""
    conn, ids, _ = er_conn
    non_proposed = conn.execute(
        "SELECT COUNT(*) AS c FROM er_merge_proposals WHERE state != 'proposed'"
    ).fetchone()["c"]
    assert non_proposed == 0
    assert er._resolve_has_no_auto_confirm() is True
    # and every match-band pair got exactly one proposal
    n_match = conn.execute(
        "SELECT COUNT(*) AS c FROM er_pairs WHERE band = 'match'").fetchone()["c"]
    n_prop = conn.execute(
        "SELECT COUNT(*) AS c FROM er_merge_proposals").fetchone()["c"]
    assert n_match == n_prop == 20


def test_confirm_merge_requires_human_actor(er_conn):
    conn, ids, _ = er_conn
    prop = _proposal_for_pair(conn, *dup_pairs(ids)[0])
    for bad_actor in ("", "   ", "system", " System ", "SYSTEM"):
        with pytest.raises(er.MergeError, match="human actor"):
            er.confirm_merge(conn, prop["id"], actor=bad_actor)


def test_confirm_merge_applies_field_plan_with_provenance(er_conn):
    conn, ids, _ = er_conn
    a_id, b_id = dup_pairs(ids)[4]  # Grace Adeyemi: A has no email, B does
    prop = _proposal_for_pair(conn, a_id, b_id)
    audit_id = er.confirm_merge(conn, prop["id"], actor="reviewer", note="looks right")

    audit = er.merge_audit_view(conn, prop["id"])
    assert audit["audit_id"] == audit_id
    assert audit["merged_by"] == "reviewer"
    assert audit["reversed_at"] is None
    # full pre-images stored for BOTH records
    assert set(audit["winner_pre_image"]) == set(audit["loser_pre_image"])
    assert audit["loser_pre_image"]["status"] == "active"
    # the winner gained the loser's email, with provenance
    email_prov = next(p for p in audit["field_provenance"] if p["field"] == "email")
    assert email_prov["value"] == "grace.adeyemi@example.com"
    winner = conn.execute("SELECT * FROM er_contacts WHERE id = ?",
                          (prop["winner_id"],)).fetchone()
    assert winner["raw_email"] == "grace.adeyemi@example.com"
    assert winner["email_norm"] == "grace.adeyemi@example.com"
    # proposal state moved
    state = conn.execute("SELECT state, decided_by FROM er_merge_proposals WHERE id = ?",
                         (prop["id"],)).fetchone()
    assert (state["state"], state["decided_by"]) == ("confirmed", "reviewer")


def test_confirm_merge_marks_loser_merged(er_conn):
    conn, ids, _ = er_conn
    a_id, b_id = dup_pairs(ids)[0]
    prop = _proposal_for_pair(conn, a_id, b_id)
    er.confirm_merge(conn, prop["id"], actor="reviewer")
    loser = conn.execute("SELECT status, merged_into FROM er_contacts WHERE id = ?",
                         (prop["loser_id"],)).fetchone()
    assert loser["status"] == "merged"
    assert loser["merged_into"] == prop["winner_id"]


def test_confirm_twice_is_rejected(er_conn):
    conn, ids, _ = er_conn
    prop = _proposal_for_pair(conn, *dup_pairs(ids)[0])
    er.confirm_merge(conn, prop["id"], actor="reviewer")
    with pytest.raises(er.MergeError, match="only 'proposed' proposals can be confirmed"):
        er.confirm_merge(conn, prop["id"], actor="reviewer")


def test_confirm_nonexistent_proposal_rejected(er_conn):
    conn, _, _ = er_conn
    with pytest.raises(er.MergeError, match="does not exist"):
        er.confirm_merge(conn, 99999, actor="reviewer")


def test_confirm_when_record_already_merged_rejected(conn):
    """A contact merged away by one proposal cannot be merged again."""
    er.ingest_source(conn, label="mg", source_kind="spreadsheet",
                     csv_text=make_csv([
                         ("Ann Lowe", "7015550400", "ann.lowe@example.com", "1 Main St", "58102"),
                         ("Ann Lowe", "7015550400", "", "1 Main Street", "58102"),
                         ("Ann Lowe", "7015550400", "ann.lowe@example.com", "1 Main St", "58102"),
                     ]), actor="test")
    er.run_resolution(conn, actor="test")
    ids = [r["id"] for r in conn.execute("SELECT id FROM er_contacts ORDER BY id")]
    c1, c2, c3 = ids
    p12 = _proposal_for_pair(conn, c1, c2)
    p23 = _proposal_for_pair(conn, c2, c3)
    assert p12 is not None and p23 is not None
    # c2 is the less-complete record: it loses the first merge
    er.confirm_merge(conn, p12["id"], actor="reviewer")
    assert p12["loser_id"] == c2
    # the second proposal touches the now-merged c2 -> the guard fires
    with pytest.raises(er.MergeError, match="must be active"):
        er.confirm_merge(conn, p23["id"], actor="reviewer")


def test_reverse_merge_restores_exact_preimage(er_conn):
    """100% merge reversibility: both rows restored byte-for-byte."""
    conn, ids, _ = er_conn
    a_id, b_id = dup_pairs(ids)[2]
    prop = _proposal_for_pair(conn, a_id, b_id)
    winner_before = dict(conn.execute("SELECT * FROM er_contacts WHERE id = ?",
                                      (prop["winner_id"],)).fetchone())
    loser_before = dict(conn.execute("SELECT * FROM er_contacts WHERE id = ?",
                                     (prop["loser_id"],)).fetchone())
    er.confirm_merge(conn, prop["id"], actor="reviewer")
    # sanity: the merge actually changed something
    assert dict(conn.execute("SELECT * FROM er_contacts WHERE id = ?",
                             (prop["loser_id"],)).fetchone()) != loser_before

    er.reverse_merge(conn, prop["id"], actor="reviewer")
    winner_after = dict(conn.execute("SELECT * FROM er_contacts WHERE id = ?",
                                     (prop["winner_id"],)).fetchone())
    loser_after = dict(conn.execute("SELECT * FROM er_contacts WHERE id = ?",
                                    (prop["loser_id"],)).fetchone())
    assert winner_after == winner_before
    assert loser_after == loser_before
    state = conn.execute("SELECT state FROM er_merge_proposals WHERE id = ?",
                         (prop["id"],)).fetchone()["state"]
    assert state == "reversed"
    audit = conn.execute("SELECT reversed_at, reversed_by FROM er_merge_audit "
                         "WHERE proposal_id = ?", (prop["id"],)).fetchone()
    assert audit["reversed_at"] is not None and audit["reversed_by"] == "reviewer"


def test_reverse_merge_non_confirmed_rejected(er_conn):
    conn, ids, _ = er_conn
    prop = _proposal_for_pair(conn, *dup_pairs(ids)[0])
    with pytest.raises(er.MergeError, match="only 'confirmed' merges can be reversed"):
        er.reverse_merge(conn, prop["id"], actor="reviewer")


def test_reverse_merge_twice_rejected(er_conn):
    conn, ids, _ = er_conn
    prop = _proposal_for_pair(conn, *dup_pairs(ids)[0])
    er.confirm_merge(conn, prop["id"], actor="reviewer")
    er.reverse_merge(conn, prop["id"], actor="reviewer")
    with pytest.raises(er.MergeError, match="only 'confirmed' merges can be reversed"):
        er.reverse_merge(conn, prop["id"], actor="reviewer")


def test_reverse_merge_requires_human_actor(er_conn):
    conn, ids, _ = er_conn
    prop = _proposal_for_pair(conn, *dup_pairs(ids)[0])
    er.confirm_merge(conn, prop["id"], actor="reviewer")
    with pytest.raises(er.MergeError, match="human actor"):
        er.reverse_merge(conn, prop["id"], actor="system")


def test_reject_proposal_changes_nothing(er_conn):
    conn, ids, _ = er_conn
    a_id, b_id = dup_pairs(ids)[3]
    prop = _proposal_for_pair(conn, a_id, b_id)
    before = {r["id"]: dict(r) for r in
              conn.execute("SELECT * FROM er_contacts WHERE id IN (?, ?)",
                           (a_id, b_id)).fetchall()}
    er.reject_proposal(conn, prop["id"], actor="reviewer", note="not the same person")
    state = conn.execute("SELECT state, decision_note FROM er_merge_proposals WHERE id = ?",
                         (prop["id"],)).fetchone()
    assert state["state"] == "rejected"
    assert state["decision_note"] == "not the same person"
    after = {r["id"]: dict(r) for r in
             conn.execute("SELECT * FROM er_contacts WHERE id IN (?, ?)",
                          (a_id, b_id)).fetchall()}
    assert after == before
    assert conn.execute("SELECT COUNT(*) AS c FROM er_merge_audit").fetchone()["c"] == 0


def test_propose_merge_human_path_for_review_pair(er_conn):
    """A human can propose a merge for a review-band pair (twins)."""
    conn, ids, _ = er_conn
    a_id, b_id = adv_pair_ids(ids, "twins")
    pair = conn.execute(
        "SELECT id FROM er_pairs WHERE (contact_a_id = ? AND contact_b_id = ?) "
        "OR (contact_a_id = ? AND contact_b_id = ?)",
        (a_id, b_id, b_id, a_id),
    ).fetchone()
    proposal_id = er.propose_merge(conn, pair["id"], actor="reviewer",
                                   note="same household, same person per owner")
    prop = conn.execute("SELECT * FROM er_merge_proposals WHERE id = ?",
                        (proposal_id,)).fetchone()
    assert prop["state"] == "proposed"
    assert prop["proposed_by"] == "reviewer"
    # and the human can then confirm it through the same gate
    audit_id = er.confirm_merge(conn, proposal_id, actor="reviewer")
    assert audit_id > 0


def test_propose_merge_no_match_pair_rejected(er_conn):
    conn, ids, _ = er_conn
    a_id, b_id = adv_pair_ids(ids, "shared_phone")
    pair = conn.execute(
        "SELECT id FROM er_pairs WHERE (contact_a_id = ? AND contact_b_id = ?) "
        "OR (contact_a_id = ? AND contact_b_id = ?)",
        (a_id, b_id, b_id, a_id),
    ).fetchone()
    with pytest.raises(er.MergeError, match="no-match band"):
        er.propose_merge(conn, pair["id"], actor="reviewer")


def test_propose_merge_duplicate_rejected(er_conn):
    conn, ids, _ = er_conn
    pair = conn.execute(
        """SELECT p.id FROM er_pairs p JOIN er_merge_proposals m ON m.pair_id = p.id
           WHERE p.band = 'match' LIMIT 1"""
    ).fetchone()
    with pytest.raises(er.MergeError, match="already has proposal"):
        er.propose_merge(conn, pair["id"], actor="reviewer")


def test_propose_merge_requires_actor(er_conn):
    conn, ids, _ = er_conn
    pair = conn.execute(
        "SELECT id FROM er_pairs WHERE band = 'review' LIMIT 1").fetchone()
    with pytest.raises(er.MergeError, match="named actor"):
        er.propose_merge(conn, pair["id"], actor="  ")


def test_proposal_events_audit_trail(er_conn):
    conn, ids, _ = er_conn
    prop = _proposal_for_pair(conn, *dup_pairs(ids)[0])
    er.confirm_merge(conn, prop["id"], actor="reviewer", note="n")
    er.reverse_merge(conn, prop["id"], actor="reviewer")
    events = er.proposal_events(conn, prop["id"])
    types = [e["event_type"] for e in events]
    assert "merge.proposed" in types
    assert "merge.confirmed" in types
    assert "merge.reversed" in types
    assert all(e["actor"] in ("system", "reviewer") for e in events)
    # append-only er_events: nothing deleted by reversal
    assert conn.execute("SELECT COUNT(*) AS c FROM er_events").fetchone()["c"] >= 3


def test_field_plan_provenance_shape(er_conn):
    conn, ids, _ = er_conn
    prop = er.get_proposal(conn, _proposal_for_pair(conn, *dup_pairs(ids)[5])["id"])
    plan = prop["field_plan"]
    assert {p["field"] for p in plan} == {"name", "phone", "email", "address", "zip"}
    for p in plan:
        assert set(p) == {"field", "value", "from_contact_id", "reason"}
        assert p["from_contact_id"] in (prop["winner_id"], prop["loser_id"])


# ---------------------------------------------------------------------------
# Pipeline idempotency
# ---------------------------------------------------------------------------

def test_run_resolution_idempotent(er_conn):
    conn, _, first = er_conn
    second = er.run_resolution(conn, actor="test")
    assert second["pairs_new"] == 0
    assert second["pairs_scored"] == 0
    assert second["proposals_created"] == 0
    assert second["pairs_total"] == first["pairs_total"]
    # band totals are unchanged (per-run stats only count newly scored pairs)
    assert er.resolution_stats(conn)["bands"] == {"match": 20, "review": 3, "no_match": 1}


def test_normalize_all_idempotent(er_conn):
    conn, _, _ = er_conn
    before = [dict(r) for r in conn.execute("SELECT * FROM er_contacts ORDER BY id")]
    assert er.normalize_all(conn) == len(before)
    after = [dict(r) for r in conn.execute("SELECT * FROM er_contacts ORDER BY id")]
    assert after == before


def test_resolution_stats_snapshot(er_conn):
    conn, _, stats = er_conn
    snap = er.resolution_stats(conn)
    assert snap["sources"] == 3
    assert snap["active_contacts"] == 54
    assert snap["merged_contacts"] == 0
    assert snap["bands"]["match"] == 20
    assert snap["bands"]["review"] == 3
    assert snap["bands"]["no_match"] == 1
    assert snap["pairs_total"] == 24
    assert snap["proposals"] == {"proposed": 20}


# ---------------------------------------------------------------------------
# Migration rollback (real)
# ---------------------------------------------------------------------------

def test_migration_009_down_step_rolls_back_for_real(er_conn):
    conn, _, _ = er_conn
    # prove the schema is live and populated
    assert conn.execute("SELECT COUNT(*) AS c FROM er_contacts").fetchone()["c"] == 54
    assert conn.execute("SELECT COUNT(*) AS c FROM er_pairs").fetchone()["c"] == 24

    assert rollback_migration(conn, "009_entity_resolution.sql") is True

    remaining = {r["name"] for r in
                 conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not {t for t in remaining if t.startswith("er_")}, \
        f"er_* tables survived rollback: {sorted(t for t in remaining if t.startswith('er_'))}"
    # other projects' tables untouched
    assert "leads" in remaining and "recon_invoices" in remaining
    assert "009_entity_resolution.sql" not in {
        r["name"] for r in conn.execute("SELECT name FROM schema_migrations")}

    # re-apply works cleanly
    applied = run_migrations(conn)
    assert "009_entity_resolution.sql" in applied
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM er_contacts").fetchone()["c"] == 0
