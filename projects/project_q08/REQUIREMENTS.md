# Q08 — Requirements

**Status:** Implemented · Tested (2026-10-23). Derived from
`portfolio-architecture-2026-10-23.md` §2, Q08.

## Functional requirements

1. **FR-1 Ingest review events.** Accept review events as JSON objects and
   as CSV rows with columns
   `external_id,stars,title,body,reviewed_at,author`. Validate: `source`
   and `external_id` required; `body` 1–4000 chars; `reviewed_at` ISO-8601
   (naive = UTC); `stars` 1–5 when present; `title` ≤ 200 chars. Reject
   invalid events with field-level errors. **Implemented + tested.**
2. **FR-2 Idempotent ingest.** The natural key `(source, external_id)` is
   UNIQUE. Re-ingesting an existing event returns the existing review id
   with `duplicate=True`; no duplicate rows. **Implemented + tested.**
3. **FR-3 Lexicon-based sentiment tagging.** Rule-based (word lists),
   honestly labeled — NOT a claimed ML model. Output: label
   positive/negative/neutral + confidence + explanation. **Implemented +
   tested** (precision/recall reported in README).
4. **FR-4 Topic tagging.** Topics: service, price, punctuality,
   workmanship. Lexicons documented and versioned. **Implemented +
   tested.**
5. **FR-5 Versioned, inspectable lexicons.** Lexicon terms stored in the
   DB per version; readable back via API; a tagger built from stored rows
   behaves identically to the code tagger. **Implemented + tested.**
6. **FR-6 Severity routing.** 1★ → critical, 2★ → high, negative text →
   owner queue; uncertain → human queue. **Implemented + tested**
   (100% critical recall on fixtures).
7. **FR-7 SLA timers.** UTC due times per severity (4h/12h/24h); a sweep
   marks overdue open entries `breached` and records an escalation.
   Frozen-clock-injectable. **Implemented + tested.**
8. **FR-8 Default-to-alert.** Ambiguous/adversarial reviews (sarcasm,
   mixed sentiment) are routed to a human-attended queue — never
   auto-resolved, never dropped. **Implemented + tested.**
9. **FR-9 Template-based response drafts.** Drafts generated from versioned
   templates with tone variants (professional/warm/brief). Templates
   contain no factual claims — only acknowledgment + next step.
   **Implemented + tested** (`template_sanity()` asserts no digits, no
   `$`, no promise-words).
10. **FR-10 Human-approval gate.** Drafts transition only
    `draft → approved | rejected`. There is **no send path**: no "sent"
    state in the DB CHECK constraint, no send/post function in the code,
    no send endpoint in the API. **Implemented + tested** (architecturally
    impossible to auto-post in v1).
11. **FR-11 Audit trail.** Every ingest/tag/route/queue/draft/decision/SLA
    action writes a row to `review_events` and a JSON stdout log line.
    **Implemented + tested.**
12. **FR-12 Web + API.** Pages: dashboard, reviews (with tags), triage
    queues, drafts. API: ingest, review list (with tags + sentiment
    filter), queues, SLA status, draft generate, draft approve/reject,
    lexicon inspection. **Implemented + tested.**

## Non-functional requirements

- **NFR-1 Zero cost:** Python 3.12 stdlib only at runtime; sqlite3; no
  network calls. **Met.**
- **NFR-2 Synthetic data only:** every review in fixtures and demos is
  fabricated; no real business identities; no scraping of real platforms.
  **Met** (banner on UI, banner in docs, masked author names).
- **NFR-3 Determinism:** identical text → identical tags (asserted).
  **Met.**
- **NFR-4 Security:** parameterized SQL only; validation at every
  boundary; no secrets in code; author names masked at rest. **Met**
  (see SECURITY.md).
- **NFR-5 Rollback:** migration `011_reviews.sql` has a tested down-step
  `011_reviews.down.sql`. **Met** (real rollback test, see TEST_RESULTS.md
  and RUNBOOK.md).

## Explicitly out of scope (v1)

- Real platform integrations (Google/Facebook/Yelp APIs) — would need
  platform approval and ToS compliance review.
- Any automatic posting of responses — architecturally excluded.
- A trained ML sentiment model — the lexicon tagger is the honest v1;
  the `ReviewTagger` protocol is the seam a real model would use.
- Notifications (email/SMS) for SLA breaches — escalation is recorded,
  not delivered.
