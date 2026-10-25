"""Tests for Q08 — lexicon-based review tagger.

All review text is synthetic fixture data. The precision/recall numbers
below are measured against 200 hand-labeled fabricated reviews and are
reported honestly — they describe the lexicon tagger on this fixture,
nothing more.
"""
import sqlite3

import pytest

from mavenu import tagger
from mavenu.db import get_connection, run_migrations
from mavenu.tagger import (
    LEXICON_VERSION,
    LexiconTagger,
    ReviewTagger,
    inspect_lexicon,
    seed_lexicons,
)

from tests.q08_review_fixtures import FIXTURE, pr_fixture

TOPICS = ("service", "price", "punctuality", "workmanship")


@pytest.fixture
def tg():
    return LexiconTagger()


def _pr(predicted: list, expected: list, label) -> tuple:
    tp = sum(1 for p, e in zip(predicted, expected) if p == label and e == label)
    fp = sum(1 for p, e in zip(predicted, expected) if p == label and e != label)
    fn = sum(1 for p, e in zip(predicted, expected) if p != label and e == label)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return precision, recall, tp, fp, fn


def test_fixture_has_200_rows():
    assert len(FIXTURE) == 200


def test_sentiment_precision_recall_positive(tg):
    rows = pr_fixture()
    got = [tg.tag(r["title"] + "\n" + r["body"]).sentiment for r in rows]
    exp = [r["expected_sentiment"] for r in rows]
    p, r_, tp, fp, fn = _pr(got, exp, "positive")
    print(f"\nsentiment positive: P={p:.3f} R={r_:.3f} tp={tp} fp={fp} fn={fn}")
    assert p >= 0.95, (p, tp, fp, fn)
    assert r_ >= 0.95, (r_, tp, fp, fn)


def test_sentiment_precision_recall_negative(tg):
    rows = pr_fixture()
    got = [tg.tag(r["title"] + "\n" + r["body"]).sentiment for r in rows]
    exp = [r["expected_sentiment"] for r in rows]
    p, r_, tp, fp, fn = _pr(got, exp, "negative")
    print(f"\nsentiment negative: P={p:.3f} R={r_:.3f} tp={tp} fp={fp} fn={fn}")
    assert p >= 0.95, (p, tp, fp, fn)
    assert r_ >= 0.95, (r_, tp, fp, fn)


@pytest.mark.parametrize("topic", TOPICS)
def test_topic_precision_recall(tg, topic):
    got = [{t for t, _ in tg.tag(r["title"] + "\n" + r["body"]).topics} for r in FIXTURE]
    exp = [r["expected_topics"] for r in FIXTURE]
    tp = sum(1 for g, e in zip(got, exp) if topic in g and topic in e)
    fp = sum(1 for g, e in zip(got, exp) if topic in g and topic not in e)
    fn = sum(1 for g, e in zip(got, exp) if topic not in g and topic in e)
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r_ = tp / (tp + fn) if (tp + fn) else 0.0
    print(f"\ntopic {topic}: P={p:.3f} R={r_:.3f} tp={tp} fp={fp} fn={fn}")
    # Lexicon topic matching is deliberately simple; floors lock in the
    # current honest performance rather than claiming excellence.
    assert p >= 0.70, (topic, p, tp, fp, fn)
    assert r_ >= 0.70, (topic, r_, tp, fp, fn)


def test_uncertain_flagged_on_weak_evidence(tg):
    rows = [r for r in FIXTURE if r["expected_uncertain"]]
    assert rows, "fixture must contain uncertain rows"
    flagged = sum(
        1 for r in rows if tg.tag(r["title"] + "\n" + r["body"]).uncertain
    )
    print(f"\nuncertain rows flagged: {flagged}/{len(rows)}")
    # 100% of the weak-evidence fixture rows must be flagged uncertain —
    # this is the default-to-alert input condition.
    assert flagged == len(rows)


def test_confident_rows_not_flagged(tg):
    rows = pr_fixture()
    flagged = sum(
        1 for r in rows if tg.tag(r["title"] + "\n" + r["body"]).uncertain
    )
    print(f"\nconfident rows wrongly flagged uncertain: {flagged}/{len(rows)}")
    assert flagged == 0


def test_deterministic(tg):
    text = "The crew was friendly and professional. Great value for the price."
    first = tg.tag(text)
    for _ in range(5):
        assert tg.tag(text) == first


def test_negation_flips_polarity(tg):
    result = tg.tag("The price was not fair and the service was not good.")
    assert result.sentiment == "negative"


def test_empty_text_is_neutral_uncertain(tg):
    result = tg.tag("")
    assert result.sentiment == "neutral"
    assert result.uncertain is True


def test_explanation_is_human_readable(tg):
    result = tg.tag("Terrible work, sloppy mess.")
    assert "lexicon" in result.explanation
    assert result.explanation  # non-empty


def test_result_carries_lexicon_version(tg):
    result = tg.tag("Great service.")
    assert result.lexicon_version == LEXICON_VERSION


def test_tagger_is_honestly_labeled_not_ml():
    # The bundled tagger must never present itself as a learned model.
    assert "lexicon" in LexiconTagger.name
    doc = LexiconTagger.__doc__ or ""
    assert "NOT a machine" in doc or "not a machine" in doc.lower()


def test_lexicon_seeding_and_inspection(tmp_path):
    db_path = str(tmp_path / "lex.db")
    conn = get_connection(db_path)
    try:
        run_migrations(conn)
        inserted = seed_lexicons(conn)
        assert inserted > 0
        # Idempotent.
        assert seed_lexicons(conn) == 0
        terms = inspect_lexicon(conn, LEXICON_VERSION)
        assert "sentiment_positive" in terms
        assert "excellent" in terms["sentiment_positive"]
        assert "topic_workmanship" in terms
    finally:
        conn.close()


def test_tagger_rebuilt_from_db_matches_code_tagger(tmp_path):
    db_path = str(tmp_path / "lex2.db")
    conn = get_connection(db_path)
    try:
        run_migrations(conn)
        seed_lexicons(conn)
        from_db = LexiconTagger.from_db(conn)
        code = LexiconTagger()
        for text in (
            "Great service, fair price, arrived on time.",
            "Terrible mess, late and overpriced.",
            "They came out Tuesday.",
        ):
            assert from_db.tag(text) == code.tag(text)
    finally:
        conn.close()


def test_from_db_unknown_version_raises(tmp_path):
    db_path = str(tmp_path / "lex3.db")
    conn = get_connection(db_path)
    try:
        run_migrations(conn)
        with pytest.raises(ValueError):
            LexiconTagger.from_db(conn, "9.9")
    finally:
        conn.close()


def test_protocol_replaceable():
    # The ReviewTagger protocol is a real seam: a stub implementation
    # satisfies it and can drive the pipeline (tested in test_reviews.py).
    class StubTagger:
        name = "stub-v0"

        def tag(self, text: str):
            from mavenu.tagger import TagResult
            return TagResult(
                sentiment="neutral", sentiment_confidence=0.0,
                topics=(), uncertain=True, matched_terms=(),
                explanation="stub", lexicon_version="stub",
            )

    stub = StubTagger()
    assert isinstance(stub, ReviewTagger)
    assert stub.tag("anything").uncertain is True
