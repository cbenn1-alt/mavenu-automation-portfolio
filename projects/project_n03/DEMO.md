# N03 — Demo

> **⚠ SYNTHETIC CASES ONLY — FRAMEWORK DEMONSTRATION, NOT CASEWORK.**
> This framework refers; it does not pursue.

## What the demo does

`POST /api/safeguard/demo` (or the "Run guided demo" button on
`/project_n03`) runs one synthetic **cyberbullying** case end-to-end in
Demo mode:

1. **Intake + safety triage** — minor involved → `minor-safeguarding`
   guidance (trusted adult, crisis lines) issued before any procedure.
2. **Playbook opens** — the 6 cyberbullying steps become checklist rows.
3. **Preserve → report** — safety-plan, preserve, report, and document
   steps are completed on the synthetic fixture.
4. **Refer** — a referral guidance record is generated (no outreach
   performed — the system has no outreach capability).
5. **Findings** — one `lead` fact with cited evidence, one `unknown`
   inference ("unknown" is an honest finding).
6. **Close** — stage reaches `closed`; the summary reports steps
   completed, referral org, and findings count.

## Try it

```bash
cd ~/workspace/mavenu-portfolio && .venv/bin/python run.py &
curl -s -X POST localhost:8080/api/safeguard/demo | python3 -m json.tool
# Then open the case page linked in the response, e.g.:
# http://localhost:8080/project_n03/cases/1
```

## The five synthetic cases

The demo runs one case; the other four are exercised in
`tests/test_safeguard.py::TestSyntheticCasesEndToEnd`:

| Ref | Category | What it exercises |
|---|---|---|
| SYN-CB-01 | cyberbullying | Full path (also the guided demo) |
| SYN-SX-01 | sextortion | Do-not-pay / preserve-before-block / FBI IC3 |
| SYN-CSE-01 | child sexual exploitation | **Refer immediately, do not investigate** — NCMEC referral auto-generated at intake |
| SYN-SW-01 | swatting | Immediate-danger triage — emergency guidance first |
| SYN-CS-01 | cyberstalking | "Unknown" attribution finding + law-enforcement referral |

All five are non-graphic written scenarios, each labeled SYNTHETIC.
No real people, accounts, or events are involved at any point.

## Status vocabulary used

The demo case is **Demo** (deterministic fixture mode); the underlying
triage/playbook/referral mechanics it exercises are **Implemented +
Tested**; every case record is **Synthetic**.
