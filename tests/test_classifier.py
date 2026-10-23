"""Unit tests: deterministic demo classifier.

These tests pin the honesty contract: the classifier is a pure function of
its inputs (deterministic), reports calibrated-looking scores with reasons,
and is labeled as a demonstration — not a trained model.
"""
from mavenu.classifier import DeterministicDemoClassifier


def _features(**over):
    base = {
        "service": "hvac",
        "zip": "58102",
        "in_service_area": True,
        "urgency": "standard",
        "has_phone": True,
        "has_email": True,
        "notes_len": 60,
    }
    base.update(over)
    return base


def test_deterministic_same_input_same_output():
    clf = DeterministicDemoClassifier()
    a = clf.classify(_features())
    b = clf.classify(_features())
    assert a == b


def test_strong_lead_is_qualified_with_high_confidence():
    clf = DeterministicDemoClassifier(threshold=0.65)
    c = clf.classify(_features())
    assert c.label == "qualified"
    assert c.confidence >= 0.65
    assert c.model == "deterministic-demo-v1"
    assert c.reason  # reason must be non-empty


def test_thin_lead_is_needs_review():
    clf = DeterministicDemoClassifier(threshold=0.65)
    c = clf.classify(_features(has_phone=False, has_email=True, notes_len=0,
                               in_service_area=True, service="landscaping"))
    assert c.label == "needs_review"
    assert c.confidence < 0.65


def test_confidence_is_bounded():
    clf = DeterministicDemoClassifier()
    for f in [_features(), _features(has_phone=False, has_email=False, notes_len=0,
                                     in_service_area=False)]:
        c = clf.classify(f)
        assert 0.0 <= c.confidence <= 1.0
        assert c.label in ("qualified", "needs_review")


def test_custom_threshold_is_respected():
    clf = DeterministicDemoClassifier(threshold=0.99)
    c = clf.classify(_features())
    assert c.label == "needs_review"  # strong lead still below an extreme threshold
