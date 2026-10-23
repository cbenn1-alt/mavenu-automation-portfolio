# Q01 — Requirements

Target user: owner/operators of 1–10-person home-service firms
(HVAC, plumbing, electrical, roofing). v1 is a **processing engine for
call records** — no telephony integration.

## Functional requirements

### FR-1 Ingestion
- FR-1.1 Accept missed-call events as CSV (header row:
  `timestamp, caller_id, ring_count, duration_seconds, transcript`) and as
  single JSON objects (the documented webhook shape).
- FR-1.2 Required fields: `timestamp` (ISO-8601), `caller_id` (≥ 7 digits
  after normalization). Optional: `ring_count` (0–60), `duration_seconds`
  (0–7200), `transcript` (string, capped at 2000 chars).
- FR-1.3 Validation failures reject the event/row with field-level errors;
  a bad row never aborts a CSV batch.
- FR-1.4 Duplicate events (same caller + same timestamp) are detected via a
  natural dedup key; the second ingest returns the original record without
  creating a new row and logs a `call.duplicate_received` event.
- FR-1.5 Client `Idempotency-Key` replay returns the original response
  without creating duplicate records.

### FR-2 Caller-ID privacy
- FR-2.1 Raw caller IDs are never persisted. Storage holds only the masked
  display form (last 4 digits visible) and a SHA-256 hash of the digits.
- FR-2.2 The hash is used solely for dedup and repeat-caller detection.

### FR-3 Urgency scoring
- FR-3.1 Every ingested call is scored by a deterministic, explainable
  ruleset behind the replaceable `UrgencyScorer` protocol.
- FR-3.2 Documented weights: base 0.20; repeat caller +0.25; after-hours
  +0.15; emergency keyword +0.20; service-request keyword +0.05 (not stacked
  with emergency); voicemail left +0.10; persistent caller (≥8 rings) +0.10;
  clamped to [0, 1], rounded to 3 decimals.
- FR-3.3 Every score carries human-readable reasons and machine-readable
  flags; the scorer identifier is stored on the call.
- FR-3.4 Identical input always yields an identical score (determinism
  property, tested across 10,000 replays).

### FR-4 Queue
- FR-4.1 Pending calls are presented as a priority queue:
  `priority = urgency_score × age decay` (decay halves priority every 24h).
- FR-4.2 Calls can be claimed/assigned to a person; claiming does not change
  state and is audit-logged.
- FR-4.3 Out-of-order ingestion (older timestamps arriving later) is
  accepted; the queue orders by computed priority, not arrival order.

### FR-5 Outcome tracking
- FR-5.1 Lifecycle enforced in code:
  `pending → attempted → connected → booked | lost`, plus `attempted → lost`
  and `pending → lost` (administrative close). `booked`/`lost` are terminal.
- FR-5.2 Illegal transitions raise `InvalidTransition` and change nothing.
- FR-5.3 First callback attempt and final outcome timestamps are stamped.
- FR-5.4 Every state change writes a `call_events` row (actor, from/to,
  detail) and a JSON stdout log line.

### FR-6 Failure analysis
- FR-6.1 Repeat-ID anomaly: the 3rd missed call from one caller hash within
  24h is flagged `repeat-id-anomaly`; the flag never auto-trusts or drops.
- FR-6.2 SLA sweep: pending calls with urgency ≥ 0.7 older than 2h are
  escalated (`escalated = 1`) and a notification **stub** row is written
  (`status = 'queued-stub'` — nothing is sent). The sweep is idempotent.
- FR-6.3 Ingestion-lag report: when the newest stored event is older than
  6h relative to now, an alert is returned (stub heuristic for a dead feed).

### FR-7 Dashboard
- FR-7.1 Metrics: total missed calls, counts by state, recovery rate
  (booked/total), contact rate ((connected+booked)/total), median
  time-to-callback (missed_at → first attempt), escalated count,
  high-urgency-pending count.
- FR-7.2 Every total reconciles to source rows (asserted by tests with an
  independent SQL re-computation).

## Non-functional requirements

- NFR-1 Zero cost: Python 3.12 stdlib only at runtime; no network calls.
- NFR-2 Ingestion p95 < 5 ms/event (measured: 0.279 ms on 2,000 synthetic
  events; see TEST_RESULTS.md).
- NFR-3 Scoring determinism 100% across 10,000 replays.
- NFR-4 All SQL parameterized; input validated at every boundary; audit
  events committed immediately.
- NFR-5 Synthetic data only; no real phone numbers in fixtures, logs, or
  demos.

## Out of scope (v1)

Real telephony hookup, actual SMS/voice notifications, TCPA-compliance
review (required before any real callback deployment — get counsel),
authenticated multi-user access, scheduled sweep execution.
