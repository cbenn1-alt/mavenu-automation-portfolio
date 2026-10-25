# N03 — Investigating Cyberpredators & Online Abuse: Victim-Centered, Lawful

**Status: Implemented · Tested** — 86 automated tests, all passing.

> **⚠ SYNTHETIC CASES ONLY — FRAMEWORK DEMONSTRATION, NOT CASEWORK.**
> Every case is a written synthetic scenario, clearly labeled SYNTHETIC.
> This framework **REFERS — it does not pursue.** There is no vigilante
> investigation, no contact with suspected offenders, no accessing of
> private accounts, devices, or communications, no distribution of
> intimate imagery, and never any accessing, possessing, or reproducing
> of child sexual abuse material — under any circumstances, for any
> reason. **Anyone using this framework for harassment, doxxing, or
> vigilante action is misusing it.**
>
> This project is legal *information* (public reporting flows, referral
> paths), never legal advice. If you or someone you know is in danger,
> contact emergency services (911 in the US). Suspected child sexual
> exploitation: report to the **NCMEC CyberTipline (CyberTipline.org)**.

## Honest-status banner

| Aspect | Label | Detail |
|---|---|---|
| What is REAL | **Implemented + Tested** | Case intake with safety triage (immediate-danger → emergency-services guidance first; minor → safeguarding; CSAM → immediate NCMEC referral path); per-category playbooks as data with every step citing a named public authority; closed action vocabulary (`preserve`, `report`, `refer`, `safety_plan`, `document`, `escalate_to_authorities`) enforced in code, DB CHECK constraints, and import-time validation; preserve→report→refer checklist tracking; referral generation (guidance text — the system performs no outreach); findings with lead/verified/unknown attribution discipline; non-graphic content validation; migration `020_safeguard.sql` + down-step, rollback tested for real; web pages (`/project_n03*`) and JSON API (`/api/safeguard*`) |
| What is SIMULATED | **Simulated** | Deterministic demo fixtures: the guided demo runs one synthetic case end-to-end in Demo mode; the referral directory is a *template* (org names, purposes, what-to-bring) — not live contact data, and the framework has no outreach capability to misuse |
| What is SYNTHETIC | **Synthetic** | All 5 case files are written non-graphic scenarios, each labeled SYNTHETIC; every case_ref, summary, finding, and referral note is invented. No real people, accounts, or events anywhere |
| What is NOT claimed | — | No casework experience. No investigations performed (the framework structurally cannot investigate suspects). No production deployment. No real users. No legal advice. No endorsement by NCMEC, the FBI, any platform, or any listed organization |

## Principles (non-negotiable, bannered here and in every document)

- **Victim-centered:** safety planning first; evidence-preservation guidance for victims (screenshots with metadata, URL preservation, no deletion); trauma-informed documentation practices.
- **Lawful:** platform reporting flows documented per major platform; referral paths to law enforcement and specialist services (NCMEC CyberTipline for CSAM, FBI IC3, local law enforcement, victim-support orgs). The portfolio **refers — it does not pursue.**
- **Attribution discipline:** investigative *leads* are distinguished from verified identity; **"unknown" is an acceptable and honest finding.**
- **Misuse banner:** anyone using this framework for harassment, doxxing, or vigilante action is misusing it — the documents say so explicitly.
- **Content discipline:** synthetic cases are NON-GRAPHIC. Scenarios are described at the level of "synthetic scenario: repeated harassing messages to a minor's public post" — never explicit content, never anything CSAM-adjacent.

## Implemented capabilities

- **Intake + safety triage** (`intake_case`): category (8), reporter role, non-graphic summary; `immediate_danger` → `safety_status=emergency` with emergency-services guidance placed first; `involves_minor` → safeguarding guidance; CSAM category → automatic NCMEC referral at intake, "do NOT investigate" guidance.
- **Closed action vocabulary** (`validate_action` + DB CHECK): only `preserve`, `report`, `refer`, `safety_plan`, `document`, `escalate_to_authorities` can be recorded. There is no "investigate suspect" or "contact suspect" action — the vocabulary cannot express it.
- **Playbooks as data** (`PLAYBOOKS`): 8 per-category ordered playbooks, preserve → report → refer; every step cites its authority (NCMEC CyberTipline, FBI IC3, platform help centers, StopBullying.gov, Cyber Civil Rights Initiative, etc.); the CSAM playbook is marked `no_investigation` and opens with an explicit do-not-investigate prohibition step. Import-time validation rejects missing authorities, out-of-vocabulary actions, and forbidden operational phrases.
- **Checklist tracking** (`complete_checklist_item` / `skip_checklist_item`): per-step status with documented reasons for skips; stage machine `triaged → active → referred → closed`.
- **Referrals** (`generate_referral`): referral *guidance* records naming where to refer and what to bring — the system performs no outreach, by construction (no messaging/network code exists; a test scans the module source to prove it).
- **Findings** (`add_finding`): `lead` / `verified` (requires cited evidence) / `unknown`; facts separated from inferences (inferences require a confidence level — the S03 discipline, reused).
- **Evidence-preservation checklist** (`preservation_checklist`): general items plus per-category addenda (e.g. preserve URLs *before* reporting for intimate-image abuse; never touch suspected material for CSAM).
- **Platform reporting guide** (`reporting_guide`): 9 entries — 7 platforms + NCMEC CyberTipline + FBI IC3, each with where/what/authority.
- **Guided demo** (`run_demo`): one synthetic cyberbullying case preserve → report → refer, end to end.

## Layout

- `src/mavenu/safeguard.py` — the module (1 file).
- `src/mavenu/migrations/020_safeguard.sql` + `020_safeguard.down.sql`.
- `tests/test_safeguard.py`, `tests/test_safeguard_api.py` — 86 tests.
- `src/mavenu/web.py` — N03 routes/handlers (added, existing tests intact).

## Quick demo

```bash
cd ~/workspace/mavenu-portfolio && .venv/bin/python run.py   # start the app
# open /project_n03, click "Run guided demo", or via API:
curl -s -X POST localhost:8080/api/safeguard/demo | python3 -m json.tool
```

## Case-study narrative

"When someone is targeted online, the first hour decides everything —
and most people panic, delete the evidence, or try to confront the
harasser. We built the boring discipline instead: safety first, preserve
with context, report through the right channel, refer to the people
whose job it actually is — practiced on synthetic cases until the method
is muscle memory. The framework refers; it does not pursue."

## Limitations

- Synthetic fixtures only. The method transfers; the "experience" does not.
- Referral directory entries are a template — verify current reporting channels yourself.
- Platform reporting flows are described from public help centers; flows change — the framework names authorities, it does not guarantee flow details.
- Legal information only, never legal advice.
