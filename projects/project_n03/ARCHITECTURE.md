# N03 — Architecture

## Module map (one module: `src/mavenu/safeguard.py`)

```
safeguard.py
├── constants            ACTIONS (closed vocabulary), STAGES, CATEGORIES (8),
│                        NON_GRAPHIC_FORBIDDEN, FORBIDDEN_OPERATIONS
├── data                 PLAYBOOKS (8 authority-cited playbooks),
│                        REFERRAL_DIRECTORY (10 template entries),
│                        PRESERVATION_CHECKLIST + PRESERVATION_ADDENDA,
│                        REPORTING_GUIDE (9 entries), SYNTHETIC_CASES (5)
├── _validate_playbooks  import-time structural self-check: vocabulary closed,
│                        every step cites authority, no forbidden operations,
│                        CSAM playbook marked no_investigation
├── validation           validate_action, validate_non_graphic,
│                        validate_case_ref, _check_no_forbidden_operations
├── intake_case          intake + safety triage → safety_status + guidance;
│                        opens playbook checklist; CSAM auto-refers to NCMEC
├── checklist            get_checklist, checklist_status,
│                        complete_checklist_item, skip_checklist_item (reason required)
├── referrals            referral_directory, generate_referral (guidance text only),
│                        list_referrals
├── findings             add_finding (lead/verified/unknown; fact vs inference),
│                        list_findings
├── case lifecycle       get_case, list_cases, get_case_detail, close_case
└── run_demo             one synthetic case preserve → report → refer (Demo mode)
```

Rationale for one module: the framework is a single pipeline with
shared discipline (closed vocabulary, authority citation, attribution
rules). Splitting it would add seams with no benefit at this scale.
The playbook *data* is the content; the *code* is the discipline
enforcing how that content may be used.

## Data model (`020_safeguard.sql`)

- `safeguard_cases` — intake: `case_ref` (UNIQUE), `category`
  (CHECK: 8 keys), `reporter_role`, `summary` (non-graphic, validated
  in code), `immediate_danger`, `involves_minor`, `safety_status`
  (CHECK: standard/minor-safeguarding/emergency), `guidance_json`,
  `stage` (CHECK: intake/triaged/active/referred/closed), `synthetic`.
- `safeguard_checklist` — `case_id`, `step_id`, `action` (CHECK: the 6
  vocabulary actions — the DB itself rejects anything else), `title`,
  `status` (CHECK: pending/done/skipped), `note`, UNIQUE(case_id, step_id).
- `safeguard_referrals` — `case_id`, `org_key`, `org_name`, `purpose`,
  `what_to_provide_json`, `guidance` (text ending in the "no outreach
  performed" note), `created_at`. Guidance records, never outreach logs.
- `safeguard_findings` — `case_id`, `statement`, `claim_type`
  (CHECK: fact/inference), `status` (CHECK: lead/verified/unknown),
  `confidence` (NULL or low/medium/high), `evidence_ref`.

Migration down-step (`020_safeguard.down.sql`) drops indexes + tables;
`rollback_migration()` removes the `schema_migrations` record so the
up-step can re-apply (rollback tested for real — TEST_RESULTS.md).

## Safety triage (`_safety_guidance`)

Deterministic and ordered: emergency guidance is always guidance[0]
when `immediate_danger` is set — nothing (not even documentation) comes
before "contact emergency services". Minor involvement adds
trusted-adult + crisis-line guidance. CSAM adds the refer-immediately
guidance and the auto-generated NCMEC referral. The ordering is what
makes the triage victim-centered: safety instructions precede
procedure.

## Closed vocabulary — three layers

1. **Code:** `validate_action()` raises `SafeguardError` on anything
   outside `ACTIONS`. All checklist writes flow through it.
2. **Database:** `CHECK (action IN (...))` on `safeguard_checklist`.
   A raw INSERT of `contact_suspect` fails at the storage layer.
3. **Data validation:** `_validate_playbooks()` at import time proves
   the shipped playbooks, referral directory, and synthetic cases
   contain only in-vocabulary actions, cited authorities, and no
   forbidden operational phrases.

Because the vocabulary has no "investigate" or "contact" action, the
framework *cannot express* pursuing a suspect — the misuse case is
blocked by grammar, not just by a warning banner.

## Attribution discipline (S03 discipline reused)

`add_finding()` separates facts from inferences:

- `claim_type=fact`: no confidence allowed (facts don't carry it).
- `claim_type=inference`: `confidence` in low/medium/high is required
  — an inference without confidence is rejected, exactly as in S03's
  `draft_report`.
- `status=verified`: requires `evidence_ref` — a verified claim must
  cite its evidence.
- `status=unknown`: always acceptable. "Unknown" is the honest
  terminal finding for "we don't know who is behind the account", and
  the workflow (documentation, referral) proceeds regardless.

## Web + API

Pages: `/project_n03` (framework), `/project_n03/playbooks`,
`/project_n03/playbooks/<category>`, `/project_n03/cases`,
`/project_n03/cases/<id>`, `/project_n03/preservation`,
`/project_n03/reporting`, `/project_n03/referrals`, POST
`/project_n03/demo`. API: `/api/safeguard/playbooks[/<category>]`,
`/api/safeguard/cases` (POST intake / GET list), `/api/safeguard/cases/<id>`,
`/api/safeguard/cases/<id>/checklist/<step_id>` (POST done/skipped),
`/api/safeguard/cases/<id>/referrals` (POST),
`/api/safeguard/cases/<id>/findings` (POST),
`/api/safeguard/preservation`, `/api/safeguard/reporting-guide`,
`/api/safeguard/referral-directory`, POST `/api/safeguard/demo`.
Every page carries the misuse banner; every API response carries
`synthetic: true` and the method-demo warning.

## What is deliberately absent

- No suspect-investigation or suspect-contact code path (asserted by
  test: identifier scan of the module source).
- No network/messaging imports (asserted by test: import-line scan).
- No real contact data in the referral directory (template only).
- No casework claims anywhere (README "NOT claimed" row).
