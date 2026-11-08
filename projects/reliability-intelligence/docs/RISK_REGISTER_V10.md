# V10 risk register — all open, ownership unassigned

Controlled source of truth: docs/RISK_REGISTER_V10.json. This file explains scope; it does not assert customer agreements or allocate named individuals.

| ID | Open concern | Severity | Blocks |
|---|---|---|---|
| R01 | V1 Git lineage separate | Medium | Formal V10 |
| R02 | V2 buyer/user/outcome approval absent | High | Formal V10 |
| R03 | V3–V8 human release signatures absent | High | Formal V10 |
| R04 | V9 independent human replay/signature absent | High | Formal V10 |
| R05 | No customer sponsorship or legal data permission | Critical | Customer data or pilot |
| R06 | Existing CMMS/ERP capabilities not assessed | High | Commercial build |
| R07 | No authorized real-world field dictionary, units, stewardship | High | Customer data or pilot |
| R08 | No approved industrial/OT and multi-tenant security case | Critical | Customer data or pilot |
| R09 | CLI/charter/fixture coverage and domain review gaps | Medium | Formal V10 |
| R10 | Invented economics could be confused with actual ROI | High | Commercial build |
| R11 | WSGI access logs and durable audit controls inadequate | Medium | Customer data or pilot |

Proposed accountable roles and exit evidence exist in the machine-readable JSON. All 11 owner assignments, remediation dates and human reviews remain null; every item is OPEN. No mitigation is certified complete.

Closure needs a named person, assigned due date, evidence link, risk disposition and authorized acceptance. Critical risks R05 and R08 are absolute blockers for real customer data and OT systems, regardless of the synthetic test result. A configure/buy/no-build alternative must remain under consideration until discovery confirms an unmet need.
