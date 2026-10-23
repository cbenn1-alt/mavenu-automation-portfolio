# Q03 — Requirements

Source: portfolio-architecture-2026-10-23.md §2 (Q03). Every requirement
below is implemented and tested; status labels follow the portfolio
vocabulary (Implemented / Tested / Simulated / Demo).

## Functional requirements

1. **RFM feature computation** (Implemented, Tested)
   - Compute recency (days since last job), frequency (lifetime job
     count), monetary (lifetime spend in cents) over synthetic job
     history at an injectable reference time.
   - Customers with no job history are handled explicitly (fully dormant),
     future-dated jobs are ignored.
2. **Dormancy scoring with documented, explainable weights** (Implemented, Tested)
   - `DormancyScorer` protocol; bundled `DeterministicDemoScorer` applies
     published weights: 0.50 recency / 0.30 frequency / 0.20 monetary,
     with documented normalization caps (365-day window, 10-job cap,
     $2,000 cap). Every applied weight appears in the score's reasons.
   - Scores are pure functions of features: 100% determinism across
     replays (tested, 1,000 scorer replays + 50 full re-scoring runs).
3. **Segmented win-back sequences per segment** (Implemented, Tested)
   - Segments: `active < 0.25`, `cooling < 0.50`, `dormant < 0.75`,
     `churned ≤ 1.0` (boundary-exact tests).
   - Per-segment touch plans: cooling 2 steps, dormant 3 steps, churned
     2 steps, active none. Steps queue only when due; reminders-only
     copy (no pressure tactics); global frequency cap 6 touches / 90 days.
4. **Suppression rules honored absolutely** (Implemented, Tested)
   - Do-not-contact flag, complaint within 180 days, or active job
     excludes the customer from every win-back step.
   - Checked at queue-build time AND re-checked at send time; a flag set
     mid-sequence stops remaining touches (queued rows marked
     `suppressed`, adapter never called). Zero leaks across adversarial
     tests (300 customers × mixed flag states × mid-sequence flag flips).
5. **Attribution: bookings traced to reactivation touches vs. organic
   return** (Implemented, Tested; Synthetic illustration)
   - Deterministic holdout split (SHA-256 per run_name + public_id);
     treated return counts only *traced* reactivation bookings
     (booking_source flag + a sent touch predating the job); control
     return counts organic bookings; lift with Wald 95% CI.
   - All attribution outputs carry the synthetic-data illustration label;
     arithmetic verified against hand-computed fixtures.
6. **Synthetic customer histories only** (Demo)
   - No real customers, no real contact data, no real PII anywhere.
7. **Reports reconcile to source rows** (Implemented, Tested)
   - Segment report, suppression audit, and attribution counts verified
     against independent raw-SQL re-computations.

## Non-functional requirements

- **Zero cost**: Python 3.12 stdlib only at runtime; no network calls.
- **Auditability**: every scoring, suppression, queueing, and flush
  decision writes an actor-stamped event row + stdout JSON line.
- **Rollback**: `005_reactivation.down.sql` removes all six Q03 tables
  and nothing else; tested for real.
- **Honest labeling**: Simulated (stub sending, triggered execution) and
  Synthetic (all data; attribution as illustration) labels appear in the
  README, the UI, the API responses, and the code docstrings.

## Out of scope (explicitly not claimed)

- Real message delivery, real provider integration, scheduled execution,
  consent/opt-out legal review for real outreach (see SECURITY.md), and
  any claim that synthetic attribution numbers represent real campaign
  performance.
