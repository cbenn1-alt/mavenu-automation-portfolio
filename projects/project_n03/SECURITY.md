# N03 — Security

> **⚠ SYNTHETIC CASES ONLY — FRAMEWORK DEMONSTRATION, NOT CASEWORK.**
> This framework refers; it does not pursue. Misuse (harassment,
> doxxing, vigilante action) is explicitly disclaimed in the README,
> module docstring, web banner, and API warning.

## Threat model

This project handles an especially sensitive domain. The security
posture is: **minimize capability, maximize discipline.**

| # | Threat | Control |
|---|---|---|
| 1 | Framework used to harass, dox, or pursue a suspected offender | **Structural:** the action vocabulary has no investigate/contact action (code + DB CHECK + import-time validation); the module has no network/messaging code (import-scan test); misuse banner on every surface |
| 2 | Graphic or explicit content entered into cases/findings | `validate_non_graphic()` on intake summaries and findings; synthetic cases hand-written non-graphic; 422/API + `ValidationError`/module on violation |
| 3 | CSAM handling — access, possession, or reproduction | CSAM playbook opens with an explicit do-not-investigate prohibition; guidance and preservation addendum forbid accessing/copying/forwarding suspected material; auto-referral to NCMEC at intake; tests assert the playbook contains no investigation steps |
| 4 | Out-of-vocabulary action smuggled via API | `validate_action()` on all writes; DB CHECK constraint as second layer; raw-INSERT rejection tested |
| 5 | Real PII leaking into fixtures | Absolute prohibition (§5.3): all names, refs, and scenarios are invented; test asserts synthetic-case summaries carry the SYNTHETIC label |
| 6 | Stale platform reporting flows misdirecting a victim | Authorities are named, not link-guaranteed; docs state flows change and must be verified; referral directory labeled a template |
| 7 | Mistaking this for legal advice or casework | "Legal information only" + "NOT claimed" rows in README; method-demo warning on every API response; misuse banner on every page |

## What the code cannot do (by construction)

- Contact anyone: no `socket`, `smtplib`, `urllib`, `http.client`,
  `requests`, or email imports exist in `safeguard.py` (test-enforced).
- Investigate or identify a suspect: no such action exists in the
  vocabulary, the database, or the playbooks (test-enforced at all
  three layers).
- Access private accounts, devices, or communications: no such
  capability exists anywhere in the module.

## Residual risks

1. **Someone could still misuse the *guidance text*** (e.g. follow a
   playbook while ignoring the prohibitions). Mitigation: prohibitions
   are first-class playbook steps, not footnotes; misuse is disclaimed
   on every surface. Cannot be eliminated by code.
2. **Referral directory drift** (org names, channels change).
   Mitigation: labeled a template; "verify current channels yourself"
   in every referral record.
3. **The non-graphic filter is coarse** (term list, not semantics).
   Mitigation: synthetic cases are hand-written; the filter is a safety
   net, documented as such.
4. **This is method demonstration, not casework experience** (README
   "NOT claimed"). The discipline transfers; the experience does not.
