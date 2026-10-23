# Q03 — Security

## Threat model

This is a demonstration system running entirely on synthetic data. The
threats below are the ones a real deployment would face; each names the
v1 mitigation and the residual work.

## Threats and mitigations

| Threat | v1 mitigation | Residual for a real deployment |
|---|---|---|
| Contacting a do-not-contact customer | Suppression checked at queue-build AND at send time; mid-sequence flags convert queued rows to `suppressed`; adversarial tests assert zero leaks | Suppression list must be the system of record (synced from the real opt-out store); add a pre-send suppression-list refresh |
| Over-contact / fatigue | Global frequency cap (6 touches / 90 days); per-segment step counts are small and fixed | Per-customer preference center; real unsubscribe handling |
| Attribution overclaim | Synthetic-data illustration label on the report, the API, the UI, and the code; traced-booking rule excludes untouchable bookings | Same discipline on real data: pre-registered windows, holdout integrity checks |
| Malformed / hostile template variables | `render_touch` fails closed on missing variables (`TouchRenderError`); the step is skipped and audit-logged | Content review workflow before template activation |
| Pressure-tactic copy | Sequence copy is reminders-only by design; no discounts-as-pressure, no false urgency | Copy review by the business owner |
| SQL injection | Parameterized queries throughout; no string-interpolated SQL except the static IN-list built from bound placeholders | Same |
| Data leakage | All customer names are synthetic fixtures; recipient labels are synthetic; nothing real is stored | Real deployments need consent basis, retention policy, and PII minimization review |

## What v1 deliberately does not do

- **No real sending.** The stub adapter cannot reach a network; there is
  no code path that sends a message anywhere. Any real deployment that
  sends win-back touches needs telecom counsel first — **no
  CAN-SPAM/TCPA-compliance review has been performed** on this project.
- **No real consent basis.** The synthetic customers have no consent
  records. A real deployment must record consent source and honor
  opt-outs; document the legal basis before the first real touch.
- **No authentication.** Like the rest of the portfolio demo, the web app
  has no login; do not expose it beyond localhost without adding auth.

## Auditability

Every scoring run, suppression change, queued touch, flush decision, and
suppressed-at-flush event is an actor-stamped row in
`reactivation_events` plus a stdout JSON line. The suppression audit page
(`/project_q03/suppression`) exists so the absolute-suppression claim can
be inspected, not just trusted.

## Secrets

None. There are no credentials, API keys, or tokens anywhere in Q03 —
by construction, since v1 cannot send anything.
