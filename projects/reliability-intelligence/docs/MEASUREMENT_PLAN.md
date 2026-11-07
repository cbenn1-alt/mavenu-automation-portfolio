# V2 — measurable outcome and test protocol (proposed)

## Primary measurable outcome

**Metric:** median reviewer minutes per *completed* maintenance review case, with an explicit start/stop definition frozen before a trial. **Primary comparison:** matched manual-only versus tool-assisted review using comparable case severity and documentation. **Directional target:** at least **20% less** median time, *only if* error/quality guardrails are met. The 20% target is a management assumption, not observed evidence or a promise.

**Formula:** `(median_manual_minutes - median_assisted_minutes) / median_manual_minutes * 100`; evaluate only with positive baseline and complete timed observations. Record reviewer identity, assignment order, case IDs and excluded/abandoned cases. Report raw distributions and uncertainty; do not infer a percentage from incomplete observations.

## Required guardrails

| Dimension | Pre-registration proposal | Status |
| --- | --- | --- |
| Seeded critical cases | 100% detected in synthetic comparison | Not tested |
| Evidence reconstruction | 100% cases link to synthetic source, reviewer and disposition | Not tested |
| False flags | Set an acceptable per-100-case rate with domain SME | Threshold unset |
| Unauthorized data reads | 0 | Structural control contract only |
| CMMS / ERP / PLC / SCADA writes | 0 | Interfaces absent |
| Unsafe autonomous actions | 0 | Not implemented |

**Not a predictive-maintenance model:** The V2 scope defines a review experiment. V41–V60 determine whether rule baselines or models provide justified advantage; V81–V90 consider forecasting only when useful and validated.

## Proposed evaluation sequence

1. Independent sponsor confirms that an unaddressed pain point exists and agrees that the selected cohort is worthwhile.
2. Verify current-system capabilities, permissions, event definitions and necessary historical data; decide build/configure/buy/stop.
3. Freeze case selection, severity, data-quality exclusions, target sample size, reviewer roles, rubric, randomization and stop criteria **before** performing any formal comparison.
4. Conduct synthetic training/calibration separately from blinded comparison; avoid leakage and record order effects.
5. Compare manual and assisted review time, exception recall, false alarms, reviewer adoption, decision reconstruction and safety failures.
6. Require a qualified maintenance reviewer and customer sponsor to accept or reject findings; no customer deployment without later gates.

## Economics and evidence limits

Potential capacity value = verified time saved × actual review volume × burdened labor rate. **Capacity released is not cash saved** unless supported by a verified expenditure reduction or incremental productive output. Downtime/repair avoidance must be causally supported and independently validated before valuation. Subtract integration, software, support, security and training costs. With no validated baseline, every ROI value is currently **unknown**.
