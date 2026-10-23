"""Q01 urgency scorer tests: documented weights, flags, and determinism.

The DeterministicDemoScorer is a pure function of its input features.
Identical input must always produce identical output (property-style test).
"""
import itertools

import pytest

from mavenu.urgency import (
    DeterministicDemoScorer,
    UrgencyScore,
    is_after_hours,
)


@pytest.fixture
def scorer():
    return DeterministicDemoScorer()


def base_features(**over):
    f = {
        "repeat_count": 0,
        "missed_at": "2026-10-22T14:30:00",  # Thursday, business hours
        "transcript": "",
        "ring_count": 3,
    }
    f.update(over)
    return f


# -- documented weights ----------------------------------------------------

def test_base_score(scorer):
    s = scorer.score(base_features())
    assert s.score == 0.2
    assert "base score 0.20" in s.reasons
    assert s.scorer == "deterministic-demo-v1"
    assert s.flags == ()


def test_after_hours_bonus_evening(scorer):
    s = scorer.score(base_features(missed_at="2026-10-22T22:15:00"))
    assert s.score == pytest.approx(0.35)
    assert "+0.15 after-hours call" in s.reasons
    assert "after-hours" in s.flags


def test_after_hours_bonus_weekend(scorer):
    s = scorer.score(base_features(missed_at="2026-10-24T10:00:00"))  # Saturday
    assert s.score == pytest.approx(0.35)


def test_no_after_hours_bonus_at_boundaries(scorer):
    assert scorer.score(base_features(missed_at="2026-10-22T08:00:00")).score == pytest.approx(0.2)
    assert scorer.score(base_features(missed_at="2026-10-22T17:59:00")).score == pytest.approx(0.2)


def test_is_after_hours_helper():
    assert is_after_hours("2026-10-22T07:59:59") is True
    assert is_after_hours("2026-10-22T18:00:00") is True
    assert is_after_hours("2026-10-22T12:00:00") is False
    assert is_after_hours("2026-10-25T12:00:00") is True  # Sunday


def test_emergency_keyword_bonus(scorer):
    s = scorer.score(base_features(transcript="No heat in the house since last night"))
    # base 0.20 + voicemail 0.10 + emergency 0.20
    assert s.score == pytest.approx(0.5)
    assert any("emergency keyword" in r for r in s.reasons)
    assert "emergency-keyword" in s.flags


def test_emergency_keyword_case_insensitive(scorer):
    s = scorer.score(base_features(transcript="FLOODING in the basement"))
    assert s.score == pytest.approx(0.5)


def test_soft_keyword_bonus_only(scorer):
    s = scorer.score(base_features(transcript="Looking for a quote on a new unit"))
    # base 0.20 + voicemail 0.10 + soft 0.05
    assert s.score == pytest.approx(0.35)


def test_emergency_takes_precedence_over_soft(scorer):
    s = scorer.score(base_features(transcript="No heat, need a quote for repair"))
    # soft bonus must NOT stack on top of emergency
    assert s.score == pytest.approx(0.5)
    assert not any("+0.05" in r for r in s.reasons)


def test_repeat_caller_bonus(scorer):
    s = scorer.score(base_features(repeat_count=2))
    assert s.score == pytest.approx(0.45)
    assert any("+0.25 repeat caller" in r for r in s.reasons)
    assert "repeat-caller" in s.flags


def test_long_ring_bonus(scorer):
    s = scorer.score(base_features(ring_count=8))
    assert s.score == pytest.approx(0.3)
    assert any("persistent caller (8 rings)" in r for r in s.reasons)


def test_short_ring_no_bonus(scorer):
    s = scorer.score(base_features(ring_count=7))
    assert s.score == pytest.approx(0.2)


def test_voicemail_bonus_requires_nonempty_transcript(scorer):
    s = scorer.score(base_features(transcript="   "))
    assert s.score == pytest.approx(0.2)


def test_all_signals_clamp_at_one(scorer):
    s = scorer.score(base_features(
        repeat_count=5,
        missed_at="2026-10-22T23:00:00",
        transcript="No heat, furnace is out",
        ring_count=12,
    ))
    # 0.20 + 0.25 + 0.15 + 0.10 + 0.20 + 0.10 = 1.00
    assert s.score == 1.0


def test_score_never_exceeds_one_on_fuzz(scorer):
    transcripts = ["", "no heat", "quote", "no heat and a quote", "x" * 500]
    times = ["2026-10-22T03:00:00", "2026-10-22T14:00:00", "2026-10-24T14:00:00"]
    for tr, tm, rc, rep in itertools.product(transcripts, times, (0, 1, 8, 60), (0, 1, 50)):
        s = scorer.score(base_features(transcript=tr, missed_at=tm,
                                       ring_count=rc, repeat_count=rep))
        assert 0.0 <= s.score <= 1.0


def test_rounding_to_three_decimals(scorer):
    s = scorer.score(base_features())
    assert s.score == round(s.score, 3)


def test_reasons_explain_every_applied_rule(scorer):
    s = scorer.score(base_features(repeat_count=1, ring_count=10,
                                   transcript="need a quote",
                                   missed_at="2026-10-22T21:00:00"))
    joined = " ".join(s.reasons)
    for needle in ("base score 0.20", "+0.25 repeat caller", "+0.15 after-hours",
                   "+0.10 caller left voicemail", "+0.05 service-request keyword",
                   "+0.10 persistent caller"):
        assert needle in joined


# -- determinism --------------------------------------------------------------

def test_identical_input_identical_score(scorer):
    f = base_features(repeat_count=3, missed_at="2026-10-22T22:00:00",
                      transcript="No heat in the house", ring_count=11)
    first = scorer.score(f)
    for _ in range(10_000):
        assert scorer.score(dict(f)) == first


def test_score_is_value_object(scorer):
    a = scorer.score(base_features(transcript="no heat"))
    b = scorer.score(base_features(transcript="no heat"))
    assert a == b
    assert isinstance(a, UrgencyScore)


def test_protocol_shape(scorer):
    assert scorer.name == "deterministic-demo-v1"
    assert hasattr(scorer, "score")
