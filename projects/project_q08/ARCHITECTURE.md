# Q08 — Architecture

**Status:** Implemented · Tested (2026-10-23).

## Module map

```
src/mavenu/
  tagger.py            LexiconTagger behind the ReviewTagger protocol;
                       versioned lexicon constants; seed/inspect/from_db.
  reviews.py           Service layer: normalize → ingest → tag → route →
                       queue/SLA → drafts → human gate; audit events.
  web.py               /project_q08* pages and /api/reviews* endpoints
                       (additive only; no existing routes touched).
  migrations/
    011_reviews.sql        reviews, review_lexicons, review_tags,
                           review_queues, review_drafts,
                           review_escalations, review_events
    011_reviews.down.sql   drops all Q08 objects (tested rollback)
```

## Data flow

```
CSV / JSON review event
        │  normalize_event (validation; ValidationError on bad input)
        ▼
ingest_event ── idempotency: UNIQUE(source, external_id) → no-op on re-ingest
        │  review_events: "ingested"
        ▼
LexiconTagger.tag(text)          ← ReviewTagger protocol (replaceable seam)
        │  sentiment label + confidence + uncertain flag
        │  topic labels + matched terms + explanation
        │  review_tags rows; review_events: "tagged"
        ▼
route_decision(stars, tag)       ← pure function, worst-wins
        │  critical/high → owner_alert (SLA 4h/12h)
        │  negative text → owner_alert (SLA 24h)
        │  uncertain → human_review (SLA 24h, default-to-alert)
        │  positive/confident-neutral → no queue ("no_action")
        │  review_queues row; review_events: "routed"
        ▼
check_sla(now) ── frozen-clock injectable ── overdue & open → breached
        │  review_escalations row; review_events: "sla_breached"
        ▼
generate_draft(template, tone) → status 'draft'
        │  templates: acknowledgment + next step only (no factual claims)
        ▼
decide_draft(approve|reject, approver) → 'approved' | 'rejected'
        │  review_drafts CHECK(status IN ('draft','approved','rejected'))
        ╳  NO "sent" STATE · NO SEND FUNCTION · NO SEND ENDPOINT
```

## Key design decisions

1. **Lexicon transparency over black-box sentiment.** Every tag carries
   its matched terms and a human-readable explanation; the lexicon is
   stored in the DB and inspectable via `GET /api/reviews/lexicons/1.0`.
   The `ReviewTagger` protocol is the seam where a real model would plug
   in — the same pattern as P01's `LeadClassifier`.
2. **Worst-wins routing.** A review can trigger several rules (e.g. a
   sarcastic 1★: "critical by stars" + "positive-sounding text"); the
   most severe queue/severity always wins, so a severe review can never be
   talked down by a confused text signal.
3. **Default-to-alert, not default-to-resolve.** The tagger reports
   uncertainty honestly (zero/weak/balanced evidence); the router turns
   every uncertain review into a human-attended queue entry. There is no
   code path that auto-resolves an ambiguous review.
4. **The send path does not exist.** This is architectural, not policy:
   the state machine has no `sent` state, the CHECK constraint rejects it,
   no function posts anything, no route accepts a send. Tests assert all
   four. A future real deployment would add an explicit, separately
   reviewed send adapter — never by accident.
5. **UTC everywhere.** `reviewed_at`, `ingested_at`, `sla_due_at` are
   ISO-8601 UTC; the SLA sweep takes an injectable clock, so breach logic
   is tested deterministically.

## Failure modes (from the spec) and mitigations

| Failure | Mitigation | Test |
|---|---|---|
| Missed severe review | Worst-wins severity rules; tested against 200-row adversarial fixture; 100% critical recall | `test_critical_routing_recall_100_percent_on_fixture`, `test_fixture_routing_matches_expectations` |
| Draft with wrong facts | Templates contain no factual claims (no digits, no `$`, no promise-words); asserted by `template_sanity()` | `test_templates_contain_no_factual_claims` |
| SLA timer drift | UTC storage; injectable clock; breach math tested on frozen clock | `test_sla_due_is_utc_and_correct`, `test_sla_breach_escalates_on_frozen_clock` |
| Auto-posted response | No send path exists (state, constraint, code, API all assert) | `test_sent_state_is_unreachable`, `test_db_check_constraint_rejects_sent`, `test_api_has_no_send_path` |
| Lexicon drift / silent changes | Lexicons versioned in DB; rebuilt tagger must tag identically | `test_tagger_rebuilt_from_db_matches_code_tagger` |
