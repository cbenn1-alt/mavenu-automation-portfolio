# Q08 — Review & Reputation Monitor

**Status: Implemented · Tested** — 65 automated tests, all passing
(full suite 934/934: 869 baseline + 65 Q08; zero regressions).

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | Review event ingest (CSV + JSON) with validation and idempotency on the natural key `(source, external_id)`; lexicon-based sentiment/topic tagger (`LexiconTagger`) behind the replaceable `ReviewTagger` protocol — transparent word lists, **not** a learned model; versioned, inspectable lexicons (`review_lexicons` table, `GET /api/reviews/lexicons/1.0`); severity routing (1★ → critical, 2★ → high, negative text → owner queue) with UTC SLA timers (4h/12h/24h) and breach escalation; template-based response drafts with a **human-approval gate**; migration `011_reviews.sql` + real rollback test |
| What is SIMULATED | **Simulated** | The 200-review synthetic fixture (hand-labeled by construction); the demo feed shape (CSV/API events); the owner/human queues (no real notifications sent) |
| What is SYNTHETIC | **Demo** | **Every review body, author name, rating, and timestamp is fabricated.** No real business identities, no real platform data, no scraping of real review platforms. The UI carries the "SYNTHETIC DEMO DATA" banner |
| What is NOT claimed | — | No production deployment. No real users, no real reviews, no platform integrations (Google/Facebook/Yelp). No platform or employer endorsement. **Response drafts are never posted automatically — there is no send path in v1, by architecture** |

## Business problem

A single unanswered 1-star review costs jobs, but owners discover reviews
weeks late. There is no triage: every review gets the same (lack of)
attention.

This project is a working monitor: every ingested review is tagged
(sentiment + topics: service, price, punctuality, workmanship) by an
explainable lexicon tagger, routed into a triage queue with an SLA timer,
and — for negative reviews — given a response draft a human must approve.
Nothing posts itself; that is the point.

## Implemented capabilities

- **Ingest** (`reviews.ingest_event`, `ingest_csv`): validates every event
  (source, external_id, body ≤ 4000 chars, ISO-8601 timestamp, stars 1–5
  optional); idempotent on `(source, external_id)` — re-ingest is a no-op;
  malformed CSV rows are skipped with row numbers, never silently dropped
- **Tag** (`tagger.LexiconTagger` behind the `ReviewTagger` protocol):
  word-boundary lexicon matching with one-token negation scope ("not
  fair" flips polarity); sentiment confidence = hit margin / total hits;
  topics assigned by hit share ≥ 0.20; `uncertain=True` on zero/weak/
  balanced evidence; result carries lexicon version + human-readable
  explanation + matched terms
- **Route** (`reviews.route_decision`): 1★ → critical owner_alert (SLA 4h);
  2★ → high owner_alert (SLA 12h); negative text (conf ≥ 0.5) → normal
  owner_alert (SLA 24h); uncertain → human_review (SLA 24h,
  default-to-alert — ambiguity is never auto-resolved); worst wins
- **SLA** (`reviews.check_sla`): frozen-clock-injectable sweep; overdue
  open entries → `breached` + escalation row + audit event; UTC throughout
- **Drafts** (`reviews.generate_draft` / `decide_draft`): templates contain
  only acknowledgment + next step — no dates, amounts, promises, or any
  digits (asserted by `template_sanity()`); human approves or rejects;
  the `review_drafts.status` CHECK constraint allows only
  `draft | approved | rejected` — **no "sent" state exists and no send/post
  function exists anywhere in the codebase** (asserted by tests)
- **Lexicon versioning** (`tagger.seed_lexicons`, `inspect_lexicon`,
  `LexiconTagger.from_db`): v1.0 seeded into `review_lexicons`;
  inspectable via API; a tagger rebuilt from stored rows tags identically
  to the code tagger
- **Audit**: every ingest/tag/route/draft/decision/SLA event → row in
  `review_events` + JSON stdout log line

## Measured tagger performance (200-review synthetic fixture, 2026-10-23)

| Category | Precision | Recall |
|---|---|---|
| sentiment: positive | 1.000 | 1.000 |
| sentiment: negative | 1.000 | 1.000 |
| topic: service | 0.791 | 0.829 |
| topic: price | 0.821 | 0.920 |
| topic: punctuality | 0.935 | 1.000 |
| topic: workmanship | 0.857 | 0.857 |

Uncertainty flag: 60/60 weak-evidence rows flagged; 0/120 confident rows
wrongly flagged. Severity-routing recall on critical (1★) fixtures:
100% (52/52) → `owner_alert`/critical. Sarcastic/adversarial reviews: all
40 reach a human-attended queue (never auto-resolved, never missed).

These numbers describe the lexicon tagger on this fabricated fixture —
they are not a claim about real-world review data.
