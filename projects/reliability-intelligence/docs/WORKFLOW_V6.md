# V6 workflow contract — fictional process only

**Requirement:** end-to-end workflow, evidenced by reproducible demo trace (Development Architecture V4, p.42).

The V6 run replays a fixed, wholly invented set of 12 case records and four fictional reviewer-role inputs. The workflow does not ingest customer data, score actual equipment condition, or make a production maintenance decision.

| Stage | Logged event | Safety limitation |
|---|---|---|
| Intake | synthetic case, fixture ID, fabricated work-order reference | no external ingestion |
| Evidence check | fabricated reference IDs and counts | no documents, signatures or authenticity checks |
| Rules review | missing-reference and prior 30-day matching-event flags | not a diagnosis or priority |
| Scripted reviewer disposition | 4 hand-authored fictional actions | no actual human reviewer |
| In-memory export | ordered events and checksum | no file, DB or external write |
| Unresolved queue | 8 example cases not dispositioned | not a real maintenance queue |

Rules look backward only: the same asset ID and failure code must have an event at or before the current event and within 30 elapsed days. A missing evidence reference is flagged when the ID list is empty. These are illustrative deterministic rules, not a model, fault forecast or safety threshold.

Simulated dispositions are acknowledge, investigate_history, request_evidence and defer. Each has a SYN-REVIEWER identity, allowable reason and flags showing scripted_synthetic=true, performed_by_real_human=false, operational_approval=false. Inconsistent decisions are rejected before producing a trace.

Output contains 12 case results, ordered synthetic events, four scripted dispositions, eight unresolved items, rule counts, provenance and SHA-256 of canonical event JSON. This is reproducible but not signed or retained. Real human approvals and audit histories are later independently gated work; the V6 dry-run is not equivalent.

V2 business problem validation, V3–V5 release sign-offs, and future G1/G2 decisions remain outstanding.
