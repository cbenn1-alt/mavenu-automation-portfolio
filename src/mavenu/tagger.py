"""Project Q08 — lexicon-based sentiment/topic tagger.

The ``ReviewTagger`` protocol is the seam where a real model would plug in.
The bundled implementation, ``LexiconTagger``, is a transparent rule-based
tagger over versioned, inspectable word lists. It is NOT a trained
machine-learning model, it performs no inference, and it must never be
described as one.

Design:
  * Sentiment: counts of positive vs negative lexicon hits (word-boundary
    regex, case-insensitive), with a one-token negation scope ("not good",
    "never on time" flip polarity). Confidence is the hit margin relative
    to total hits. Low or balanced evidence -> ``uncertain=True``.
  * Topics: service, price, punctuality, workmanship. A topic is assigned
    when at least one of its lexicon terms matches; confidence is that
    topic's share of all topic hits.
  * Uncertainty is reported honestly and the service layer routes uncertain
    reviews to a human queue (default-to-alert). The tagger never
    auto-resolves anything.

Lexicon versioning: the module ships ``LEXICONS`` keyed by version string
("1.0" current). ``seed_lexicons(conn, version)`` writes a version into the
``review_lexicons`` table; ``LexiconTagger.from_db(conn, version)`` builds a
tagger from those stored rows, so a lexicon is inspectable and a new
version is inserted rather than edited.

ALL DATA THIS MODULE PROCESSES IS SYNTHETIC DEMONSTRATION DATA.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence, runtime_checkable

#: Current lexicon version shipped with the code.
LEXICON_VERSION = "1.0"

#: Words that flip the polarity of the next sentiment term ("not great").
NEGATIONS = {"not", "no", "never", "n't", "without", "hardly", "barely"}

#: Confidence below which the tagger flags the review as uncertain.
UNCERTAIN_CONFIDENCE = 0.35

#: Minimum topic-hit share for a topic label to be emitted.
TOPIC_CONFIDENCE_MIN = 0.20

#: (positive terms, negative terms) for sentiment.
SENTIMENT_LEXICON: dict[str, Sequence[str]] = {
    "positive": (
        "excellent", "outstanding", "fantastic", "wonderful", "amazing",
        "great", "good", "perfect", "prompt", "polite", "courteous",
        "friendly", "professional", "helpful", "responsive", "reliable",
        "honest", "efficient", "clean", "neat", "thorough", "fair",
        "reasonable", "affordable", "punctual", "timely", "impressed",
        "pleased", "satisfied", "happy", "recommend", "recommendation",
        "love", "loved", "best", "quick", "quickly", "careful",
        "respectful", "knowledgeable", "skilled", "quality",
    ),
    "negative": (
        "terrible", "awful", "horrible", "worst", "disgusting", "bad",
        "poor", "sloppy", "careless", "rude", "disrespectful", "late",
        "delayed", "unprofessional", "unresponsive", "unreliable",
        "dishonest", "overpriced", "expensive", "overcharged", "mess",
        "messy", "dirty", "broken", "damaged", "wrong", "mistake",
        "failed", "failure", "refused", "ignored", "nightmare",
        "frustrating", "disappointed", "disappointing", "unhappy",
        "angry", "furious", "scam", "ripoff", "warning", "avoid",
        "complaint", "problem", "problems", "issue", "issues",
    ),
}

#: Topic lexicons (word/phrase lists). Spec categories: service, price,
#: punctuality, workmanship.
TOPIC_LEXICONS: dict[str, Sequence[str]] = {
    "service": (
        "crew", "technician", "tech", "team", "office", "dispatcher",
        "receptionist", "customer service", "service rep", "worker",
        "manager", "owner", "staff", "employee", "representative",
        "phone", "call", "called", "voicemail", "follow-up",
    ),
    "price": (
        "price", "pricing", "quote", "estimate", "cost", "charge",
        "charged", "overcharged", "fee", "fees", "invoice", "bill",
        "billed", "expensive", "overpriced", "affordable", "fair",
        "reasonable", "cheap", "discount", "payment",
    ),
    "punctuality": (
        "late", "on time", "punctual", "delayed", "delay", "no-show",
        "never showed", "showed up", "arrived", "arrival", "window",
        "schedule", "scheduled", "appointment", "wait", "waiting",
        "hours late", "rescheduled",
    ),
    "workmanship": (
        "workmanship", "quality", "craftsmanship", "sloppy", "neat",
        "clean", "mess", "messy", "thorough", "careful", "skilled",
        "botched", "damaged", "broken", "fixed", "repair", "install",
        "installed", "paint", "caulk", "seal", "leak", "leaking",
        "dripping", "drafty",
    ),
}

#: category -> (version category name, terms) mapping for seeding.
LEXICONS: dict[str, dict[str, Sequence[str]]] = {
    LEXICON_VERSION: {
        "sentiment_positive": SENTIMENT_LEXICON["positive"],
        "sentiment_negative": SENTIMENT_LEXICON["negative"],
        "topic_service": TOPIC_LEXICONS["service"],
        "topic_price": TOPIC_LEXICONS["price"],
        "topic_punctuality": TOPIC_LEXICONS["punctuality"],
        "topic_workmanship": TOPIC_LEXICONS["workmanship"],
    },
}


@dataclass(frozen=True)
class TagResult:
    """Output of one tag pass over a review's text."""

    sentiment: str                     # 'positive' | 'negative' | 'neutral'
    sentiment_confidence: float        # 0.0 .. 1.0
    topics: tuple                      # tuple of (label, confidence)
    uncertain: bool                    # True -> route to human, never auto-resolve
    matched_terms: tuple               # tuple of (term, polarity_or_topic)
    explanation: str                   # human-readable reasoning
    lexicon_version: str


@runtime_checkable
class ReviewTagger(Protocol):
    """Replaceable seam for review tagging.

    A real ML-backed tagger would implement this protocol. The bundled
    ``LexiconTagger`` is the deterministic, explainable v1.
    """

    name: str

    def tag(self, text: str) -> TagResult:
        ...


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower())


def _hit_spans(
    tokens: list[str], terms: Sequence[str]
) -> list[tuple[str, int]]:
    """Return (term, token_index) for every lexicon term found in the tokens.

    Multi-word terms match consecutive tokens.
    """
    text = " " + " ".join(tokens) + " "
    hits: list[tuple[str, int]] = []
    for term in terms:
        needle = " " + term.lower() + " "
        start = 0
        while True:
            idx = text.find(needle, start)
            if idx == -1:
                break
            token_idx = text[:idx].count(" ")
            hits.append((term.lower(), token_idx))
            start = idx + 1
    return hits


class LexiconTagger:
    """Rule-based demonstration tagger over versioned lexicons.

    Pure function of its inputs and lexicons: identical text always
    produces an identical result (asserted by tests). NOT a machine
    learning model.
    """

    name = f"lexicon-tagger-v{LEXICON_VERSION}"

    def __init__(
        self,
        lexicons: Mapping[str, Sequence[str]] | None = None,
        version: str = LEXICON_VERSION,
    ):
        lexicons = lexicons or LEXICONS[version]
        self.lexicons = {cat: tuple(terms) for cat, terms in lexicons.items()}
        self.version = version

    @classmethod
    def from_db(cls, conn: sqlite3.Connection, version: str = LEXICON_VERSION) -> "LexiconTagger":
        """Build a tagger from lexicon rows stored in ``review_lexicons``.

        Raises ``ValueError`` when the version has no rows — the tagger is
        inspectable but only for versions that were actually seeded.
        """
        rows = conn.execute(
            "SELECT category, term FROM review_lexicons WHERE version = ?",
            (version,),
        ).fetchall()
        lexicons: dict[str, list[str]] = {}
        for row in rows:
            lexicons.setdefault(row["category"], []).append(row["term"])
        if not lexicons:
            raise ValueError(f"No lexicon rows for version {version!r}")
        return cls(lexicons=lexicons, version=version)

    def tag(self, text: str) -> TagResult:
        tokens = _tokenize(text or "")
        matched: list[tuple[str, str]] = []

        pos_hits = _hit_spans(tokens, self.lexicons["sentiment_positive"])
        neg_hits = _hit_spans(tokens, self.lexicons["sentiment_negative"])

        def polarity(term: str, idx: int) -> str:
            # One-token negation scope: the token immediately before the
            # term flips its polarity ("not great", "never on time").
            if idx > 0 and tokens[idx - 1] in NEGATIONS:
                return "negated"
            return "direct"

        pos = neg = 0
        for term, idx in pos_hits:
            flipped = polarity(term, idx) == "negated"
            matched.append((term, "sentiment_negative" if flipped else "sentiment_positive"))
            if flipped:
                neg += 1
            else:
                pos += 1
        for term, idx in neg_hits:
            flipped = polarity(term, idx) == "negated"
            matched.append((term, "sentiment_positive" if flipped else "sentiment_negative"))
            if flipped:
                pos += 1
            else:
                neg += 1

        total = pos + neg
        if total == 0:
            sentiment = "neutral"
            s_conf = 0.0
        elif pos > neg:
            sentiment = "positive"
            s_conf = (pos - neg) / total
        elif neg > pos:
            sentiment = "negative"
            s_conf = (neg - pos) / total
        else:
            sentiment = "neutral"
            s_conf = 0.0

        # Topics.
        topic_hits: dict[str, list[str]] = {}
        for label, category in (
            ("service", "topic_service"),
            ("price", "topic_price"),
            ("punctuality", "topic_punctuality"),
            ("workmanship", "topic_workmanship"),
        ):
            terms = self.lexicons.get(category, ())
            found = sorted({term for term, _ in _hit_spans(tokens, terms)})
            if found:
                topic_hits[label] = found
                for term in found:
                    matched.append((term, f"topic_{label}"))

        total_topic_hits = sum(len(v) for v in topic_hits.values())
        topics = tuple(
            (label, round(len(found) / total_topic_hits, 4))
            for label, found in sorted(topic_hits.items())
            if total_topic_hits and len(found) / total_topic_hits >= TOPIC_CONFIDENCE_MIN
        )

        # Uncertainty: no evidence, weak margin, or strongly mixed signals.
        uncertain = (
            total == 0
            or s_conf < UNCERTAIN_CONFIDENCE
            or (pos >= 2 and neg >= 2)
        )

        explanation = (
            f"{pos} positive / {neg} negative lexicon hits; "
            f"sentiment={sentiment} (confidence {s_conf:.2f}); "
            f"topics={', '.join(l for l, _ in topics) or 'none'}; "
            f"uncertain={uncertain} (lexicon v{self.version})"
        )
        return TagResult(
            sentiment=sentiment,
            sentiment_confidence=round(s_conf, 4),
            topics=topics,
            uncertain=uncertain,
            # Sorted so the result does not depend on lexicon term order
            # (e.g. a tagger rebuilt from DB rows must equal the code tagger).
            matched_terms=tuple(sorted(matched)),
            explanation=explanation,
            lexicon_version=self.version,
        )


def seed_lexicons(conn: sqlite3.Connection, version: str = LEXICON_VERSION) -> int:
    """Insert one lexicon version's terms into ``review_lexicons``.

    Idempotent per (version, category, term). Returns rows inserted.
    """
    if version not in LEXICONS:
        raise ValueError(f"Unknown lexicon version {version!r}")
    inserted = 0
    for category, terms in LEXICONS[version].items():
        for term in terms:
            cur = conn.execute(
                """INSERT OR IGNORE INTO review_lexicons (version, category, term)
                   VALUES (?, ?, ?)""",
                (version, category, term),
            )
            inserted += cur.rowcount
    conn.commit()
    return inserted


def inspect_lexicon(conn: sqlite3.Connection, version: str) -> dict[str, list[str]]:
    """Return the stored lexicon terms for a version (inspectability)."""
    rows = conn.execute(
        "SELECT category, term FROM review_lexicons WHERE version = ? ORDER BY category, term",
        (version,),
    ).fetchall()
    out: dict[str, list[str]] = {}
    for row in rows:
        out.setdefault(row["category"], []).append(row["term"])
    return out


def tag_summary(result: TagResult) -> dict:
    """JSON-friendly summary of a tag result."""
    return {
        "sentiment": result.sentiment,
        "sentiment_confidence": result.sentiment_confidence,
        "topics": [{"label": label, "confidence": conf} for label, conf in result.topics],
        "uncertain": result.uncertain,
        "matched_terms": [{"term": t, "kind": k} for t, k in result.matched_terms],
        "explanation": result.explanation,
        "lexicon_version": result.lexicon_version,
    }


def summary_json(result: TagResult) -> str:
    return json.dumps(tag_summary(result), sort_keys=True)
