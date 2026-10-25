# N03 — Requirements (full spec)

**Status:** Implemented + Tested (2026-10-23). Supersedes the §4
spec-sketch in `portfolio-architecture-2026-10-23.md`.

> ⚠ **SYNTHETIC CASES ONLY — FRAMEWORK DEMONSTRATION, NOT CASEWORK.**
> Victim-centered, lawful: safety planning first; the framework
> **refers — it does not pursue**. No vigilante investigation, no
> contact with suspected offenders, no accessing private accounts or
> devices, no distribution of intimate imagery, never any CSAM access
> or possession. Anyone using this for harassment, doxxing, or
> vigilante action is misusing it. Legal information only, never legal
> advice.

## 1. Purpose

Demonstrate a defensible, ethical **triage-and-referral method** for
online-abuse response — the kind of discipline a victim advocate, trust
& safety worker, or community responder uses in the first hour:
**intake → safety triage → playbook selection → preserve / report /
refer → referral → close**. The product is the *method* (safety-first
sequencing, cited authorities, attribution honesty, lawful boundaries),
not an investigation tool. Nothing in this project investigates,
contacts, or pursues any person.

## 2. Scope

**In scope:**

- 8 abuse categories **to understand and refer, never to investigate
  independently**: internet trolling, swatting, cyberbullying,
  cyberharassment, cyberstalking, sextortion, nonconsensual
  intimate-image abuse, child sexual exploitation (CSAM).
- Synthetic case intake with safety triage (immediate-danger,
  minor-safeguarding, CSAM immediate-referral).
- A **closed action vocabulary**: `preserve`, `report`, `refer`,
  `safety_plan`, `document`, `escalate_to_authorities` — enforced in
  code, DB CHECK constraints, and import-time playbook validation.
- Per-category response playbooks as data (ordered steps, each citing
  a named public authority).
- Preserve → report → refer checklist tracking with a stage machine.
- Referral generation: guidance text naming where to refer and what to
  bring (no outreach capability exists).
- Findings with attribution discipline: `lead` / `verified` /
  `unknown`; facts separated from inferences (inferences require
  confidence — the S03 discipline, reused).
- Evidence-preservation checklist for victims (general + per-category
  addenda), platform reporting guide (7 platforms + NCMEC + FBI IC3),
  referral directory template (10 entries).
- 5 synthetic case files (non-graphic, labeled SYNTHETIC) exercising
  preserve → report → refer end-to-end, including one CSAM case whose
  correct outcome is "refer immediately, do not investigate".
- SQLite persistence + migration with a tested down-step.
- Web pages (`/project_n03*`) and JSON API (`/api/safeguard*`), all
  bannered synthetic.

**Out of scope:** see §9 (non-goals).

## 3. Categories (understand and refer — never investigate)

| # | Key | Category | Triage note |
|---|---|---|---|
| 1 | `internet_trolling` | Internet Trolling | Do not engage; preserve, block, report; re-triage if targeted |
| 2 | `swatting` | Swatting | Immediate-danger until responders say otherwise; emergency first |
| 3 | `cyberbullying` | Cyberbullying | Minor-safeguarding: trusted adult, platform + school reporting |
| 4 | `cyberharassment` | Cyberharassment | Pattern documentation; escalate on threats/doxxing |
| 5 | `cyberstalking` | Cyberstalking | Safety planning central; dated log; law-enforcement referral (18 U.S.C. § 2261A — legal information) |
| 6 | `sextortion` | Sextortion | Do NOT pay / send / continue contact; preserve threats, then block; FBI IC3; NCMEC if minor |
| 7 | `nc_ii_abuse` | Nonconsensual Intimate-Image Abuse | Preserve URLs *before* reporting (reports trigger removal); CCRI + law enforcement |
| 8 | `child_sexual_exploitation` | Child Sexual Exploitation (CSAM) | **Refer immediately. No investigation.** NCMEC CyberTipline; never access/copy/forward suspected material |

## 4. Closed action vocabulary

The engine can record exactly six actions — `ACTIONS` in
`safeguard.py`:

`preserve` · `report` · `refer` · `safety_plan` · `document` ·
`escalate_to_authorities`

Structural enforcement (all tested):

- `validate_action()` rejects anything else (e.g. `contact_suspect`,
  `investigate_suspect` raise `SafeguardError`).
- The `safeguard_checklist.action` column has a CHECK constraint on
  the same six values — out-of-vocabulary actions cannot be stored.
- `_validate_playbooks()` runs at import: every playbook step's action
  must be in the vocabulary; every step must cite an authority;
  forbidden operational phrases ("contact the suspect", "investigate
  the suspect", "vigilante", …) are rejected anywhere in playbook,
  referral-directory, or synthetic-case text.
- A test scans the module source and fails on any
  network/messaging import (`socket`, `smtplib`, `urllib`,
  `http.client`, `requests`, …) — the engine cannot contact anyone,
  by construction.

## 5. Safety triage

`intake_case()` computes `safety_status` and ordered guidance:

- `immediate_danger=True` → `emergency`: guidance[0] is
  "EMERGENCY FIRST: contact emergency services (911…)".
- `involves_minor=True` → `minor-safeguarding`: trusted-adult and
  crisis-line guidance (988 Lifeline / Crisis Text Line).
- `category == child_sexual_exploitation` → guidance includes "REFER
  IMMEDIATELY — DO NOT INVESTIGATE" plus an auto-generated NCMEC
  CyberTipline referral row at intake (before any checklist work).
- `category == sextortion` → "Do NOT pay…" guidance.
- Otherwise → standard safety-planning guidance.

Case summaries and finding statements pass `validate_non_graphic()`
(coarse explicit-content term list; synthetic cases are additionally
hand-written non-graphic).

## 6. Playbooks (data, authority-cited)

`PLAYBOOKS[category]` = ordered steps; each step is
`{step_id, action, title, detail, authority}`. Rules:

- Every step's `action` ∈ the closed vocabulary (§4).
- Every step cites a **named public authority** — e.g. "NCMEC
  CyberTipline (CyberTipline.org)", "FBI Internet Crime Complaint
  Center (IC3)", "StopBullying.gov", "Cyber Civil Rights Initiative",
  "Platform help centers (…reporting flows)". Authorities are named,
  not link-guaranteed; flow details change and the docs say so.
- Every playbook covers preserve → report → refer (asserted in tests).
- `child_sexual_exploitation.no_investigation = True`; its first step
  is an explicit do-not-investigate prohibition recorded as a
  `document` action.

## 7. Checklists, preservation guide, reporting guide, referral directory

- **Checklist tracking:** intake opens one checklist row per playbook
  step. `complete_checklist_item` / `skip_checklist_item` (skips need
  a documented reason). Stage machine:
  `triaged → active → referred → closed`; `close_case` requires zero
  pending items.
- **Evidence-preservation checklist** (`preservation_checklist()`):
  7 general items (screenshot with context, save URLs, do-not-delete,
  export, back up, dated log, report confirmations) + per-category
  addenda for sextortion, nc_ii_abuse, swatting, and CSAM (the last:
  preserve only the reporter's own records — never the material).
- **Platform reporting guide** (`reporting_guide()`): 9 entries —
  Instagram, TikTok, X, Facebook, Snapchat, YouTube, Discord, NCMEC
  CyberTipline, FBI IC3 — each with where/what/authority.
- **Referral directory** (`referral_directory()`): 10 template entries
  (NCMEC, FBI IC3, local law enforcement/911, Crisis Text Line, 988
  Lifeline, NDVH, CCRI, StopBullying.gov, VictimConnect, Stop It Now!).
  `generate_referral()` records guidance text (org, purpose, what to
  bring, "no outreach performed" note). The directory is a template —
  verify current channels yourself.

## 8. Synthetic cases (5, all SYNTHETIC, all non-graphic)

| Ref | Category | Exercise |
|---|---|---|
| SYN-CB-01 | cyberbullying | Full preserve → report → refer with minor-safeguarding |
| SYN-SX-01 | sextortion | Safety-plan first; do-not-pay; preserve-before-block; FBI IC3 |
| SYN-CSE-01 | child_sexual_exploitation | **Refer immediately, do not investigate**: NCMEC referral auto-generated at intake; playbook has no investigation steps |
| SYN-SW-01 | swatting | Immediate-danger triage: emergency-services guidance first |
| SYN-CS-01 | cyberstalking | Attribution discipline: "unknown" recorded as an honest finding; documentation + law-enforcement referral proceed |

Each case is exercised end-to-end in tests: intake → complete
preserve/report/safety steps → referral → close, asserting preserve,
report, and refer each have ≥1 completed step. The guided demo
(`run_demo`) runs the cyberbullying case in Demo mode.

## 9. Non-goals, misuse, measurable criteria

**Non-goals (explicitly NOT this project):**

- Not an investigation tool. There is no suspect-investigation,
  suspect-contact, device-access, or account-access capability —
  structurally, not just by policy.
- Not a reporting integration. The framework generates referral
  *guidance*; it files no reports and sends no messages.
- Not legal advice. Public reporting flows and referral paths are
  legal *information*.
- Not casework experience, not a production deployment, not real users.

**Misuse:** anyone using this framework for harassment, doxxing,
vigilante action, or to pursue a suspected offender is misusing it.
The README, module docstring, web banner, and API warning all say so.

**Measurable criteria (all verified — TEST_RESULTS.md):**

- M1 — every playbook step cites an authority (structural assertion over all 8 playbooks).
- M2 — action vocabulary is closed (out-of-vocabulary actions rejected in code, DB, and playbook validation; no suspect-contact code path exists; no network/messaging imports).
- M3 — all 5 synthetic cases complete preserve → report → refer end-to-end with no real-world contact.
- M4 — immediate-danger intake yields emergency-services guidance first.
- M5 — CSAM-category intake auto-generates the NCMEC referral with no investigation steps.
- M6 — attribution: "unknown" accepted as a finding; verified requires evidence; inferences require confidence.
- M7 — migration rollback tested for real (down-step).
- M8 — no regressions (full suite).
