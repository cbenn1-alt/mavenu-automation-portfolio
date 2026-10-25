# Q08 — Demo Script

**Status:** Implemented · Tested (2026-10-23). All data synthetic.

A 5-minute walkthrough of the Review & Reputation Monitor. Every name,
review, and rating below is fabricated.

## 0:00 — The problem (30s)

"A bad review sat unanswered for three weeks and cost them a
neighborhood. Owners discover reviews weeks late, and every review gets
the same lack of attention. This monitor tags every review, escalates
the bad ones fast, and drafts replies a human approves. Nothing posts
itself — that's the point."

## 0:30 — Ingest (1 min)

Open `/project_q08`. Paste the demo CSV (see RUNBOOK.md) and ingest.
Point out: the 1★ "No-show" review lands in `owner_alert`/critical with
a 4-hour UTC SLA; the 5★ review is tagged positive and gets no queue
entry (`no_action` — the system doesn't cry wolf).

## 1:30 — Explainable tagging (1 min)

Open `/project_q08/reviews`. Each review shows its tags, e.g.
`sentiment:negative (0.85)`, `topic:punctuality (0.60)`. Open
`/api/reviews/lexicons/1.0` — the word lists are right there in the
open. "This is not a machine-learning model. Every tag is traceable to
the words that caused it."

## 2:30 — Adversarial case (1 min)

Ingest a sarcastic 1★: "Oh fantastic — they never showed up. Wonderful
service!" The lexicon reads the text as positive — but the star rule
still raises it as **critical** in the owner queue. "Worst wins: a
confused text signal can never talk down a 1-star review."

## 3:30 — SLA breach (45s)

Note the `sla_due_at` (UTC). Explain: the sweep marks overdue open
entries `breached` and records an escalation — demonstrated in tests on
a frozen clock (`test_sla_breach_escalates_on_frozen_clock`).

## 4:15 — Human-approved drafts (45s)

From the reviews page, generate a draft (tone: warm). Open
`/project_q08/drafts`: the draft contains acknowledgment + next step —
no dates, no amounts, no promises (`template_sanity()` asserts this).
Approve it. "Approved means a human cleared it to copy and send
manually. There is no button that posts it — the send path doesn't
exist in this system."

## Close

"Synthetic data, transparent rules, and a hard guarantee: the system can
draft, but only a human can speak for the business."
