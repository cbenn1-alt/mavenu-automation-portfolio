"""N03 — Investigating Cyberpredators & Online Abuse: Victim-Centered, Lawful.

=====================================================================
SYNTHETIC CASES ONLY. FRAMEWORK DEMONSTRATION — NOT CASEWORK.
NEVER ACCESS PRIVATE ACCOUNTS, DEVICES, OR COMMUNICATIONS.
NO VIGILANTE INVESTIGATION. NO CONTACT WITH SUSPECTED OFFENDERS.
NO DISTRIBUTION OF INTIMATE IMAGERY. NEVER ACCESS, POSSESS,
OR REPRODUCE CHILD SEXUAL ABUSE MATERIAL — UNDER ANY
CIRCUMSTANCES, FOR ANY REASON. THIS FRAMEWORK REFERS; IT DOES
NOT PURSUE.
=====================================================================

This module implements a *triage and referral framework* for online-abuse
response. It is a **method demonstration** for Mavenu's portfolio:
categories to *understand and refer*, never to investigate
independently.

The pipeline:

    intake  ->  safety triage  ->  playbook selection  ->
    preserve / report / refer checklists  ->  referral  ->  close

Deliberate structural limits (the actual product of this project):

* **Closed action vocabulary.** The only actions the engine can record
  are ``preserve``, ``report``, ``refer``, ``safety_plan``,
  ``document``, and ``escalate_to_authorities``. There is no
  "investigate suspect", "contact suspect", or "gather evidence from
  the suspect" action — the vocabulary cannot express them, and the
  database CHECK constraint rejects anything outside it. Tests assert
  the vocabulary is closed and that no such code path exists.
* **No contact capability.** This module contains no messaging,
  email, or network code of any kind. It cannot contact anyone, by
  construction. A test scans this file's own source and fails if any
  socket/messaging import is present.
* **Safety triage first.** An immediate-danger flag routes to
  emergency-services guidance before any other step.
* **CSAM-category cases refer immediately.** A
  ``child_sexual_exploitation`` intake auto-generates an NCMEC
  CyberTipline referral path and its playbook is marked
  ``no_investigation``: preserve the *reporter's own* records, report
  to NCMEC, refer to law enforcement. Investigation is law
  enforcement's job.
* **Attribution discipline.** Findings carry a status of ``lead``,
  ``verified`` (requires cited evidence), or ``unknown``. "Unknown" is
  an acceptable and honest finding. Facts and inferences are separated;
  inferences require an explicit confidence level.
* **Content discipline.** Case summaries and findings are validated as
  non-graphic. All five synthetic cases are non-graphic written
  scenarios, each labeled SYNTHETIC.

Status vocabulary: Implemented, Tested, Simulated, Demo.
The triage/playbook/referral framework is Implemented+Tested; the
synthetic cases and demo fixtures are Simulated; the guided demo runs
in Demo mode.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .db import utcnow_iso
from .validation import ValidationError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The closed action vocabulary. Nothing outside this tuple can be
#: recorded, persisted, or served — structurally, not just by convention.
ACTIONS = (
    "preserve",
    "report",
    "refer",
    "safety_plan",
    "document",
    "escalate_to_authorities",
)

STAGES = ("intake", "triaged", "active", "referred", "closed")

CHECKLIST_STATUSES = ("pending", "done", "skipped")

FINDING_STATUSES = ("lead", "verified", "unknown")

CLAIM_TYPES = ("fact", "inference")

CONFIDENCE_LEVELS = ("low", "medium", "high")

CASE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_]{1,63}$")

#: Non-graphic content discipline. Case summaries and findings are
#: rejected if they contain any of these terms. This is a coarse
#: safety net — the synthetic cases themselves are written non-graphic.
NON_GRAPHIC_FORBIDDEN = (
    "pornograph",
    "child porn",
    "masturbat",
    "genital",
    "bestial",
    "incest",
    "explicit sexual",
    "sexually explicit",
    "nude photo",
    "nude image",
)

#: Forbidden operational phrases. No playbook step, guidance text, or
#: synthetic-case field may contain any of these — the framework never
#: directs anyone toward a suspected offender. Single words match on
#: word boundaries (so "doxxing", the standard victim-centered term for
#: identity exposure, is allowed); multi-word phrases match as phrases.
FORBIDDEN_OPERATIONS = (
    "contact the suspect",
    "confront the suspect",
    "investigate the suspect",
    "message the suspect",
    "track down the suspect",
    r"\bdox\b",
    r"\bdoxx\b",
    "vigilante",
)

# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

CATEGORIES: dict[str, dict[str, str]] = {
    "internet_trolling": {
        "title": "Internet Trolling",
        "understand": (
            "Deliberately provocative, disruptive, or inflammatory "
            "behavior online. Respond with preserve → report → refer; "
            "do not engage. Escalate if it becomes targeted harassment."
        ),
    },
    "swatting": {
        "title": "Swatting",
        "understand": (
            "False emergency reports (e.g. fake calls to dispatchers) "
            "intended to send an armed response to a victim's address. "
            "Treat as immediate-danger until told otherwise by "
            "responders. Preserve any related messages; report to law "
            "enforcement."
        ),
    },
    "cyberbullying": {
        "title": "Cyberbullying",
        "understand": (
            "Repeated, intentional harm to a minor via digital means — "
            "harassing messages, exclusion, rumor-spreading, or "
            "shaming posts. Minor-safeguarding rules apply: involve a "
            "trusted adult, preserve evidence, report to the platform "
            "and the minor's school where appropriate."
        ),
    },
    "cyberharassment": {
        "title": "Cyberharassment",
        "understand": (
            "A pattern of unwanted, hostile online contact toward an "
            "adult that causes distress. Preserve messages with "
            "timestamps, report to platforms, escalate to law "
            "enforcement when it crosses into threats or stalking."
        ),
    },
    "cyberstalking": {
        "title": "Cyberstalking",
        "understand": (
            "Repeated online surveillance, unwanted contact, or "
            "monitoring that causes fear. Safety planning is central; "
            "document every incident with dates; law-enforcement "
            "referral when threats, doxxing, or offline escalation "
            "appear. 18 U.S.C. § 2261A is the federal cyberstalking "
            "statute (legal information, not advice)."
        ),
    },
    "sextortion": {
        "title": "Sextortion",
        "understand": (
            "Threats to share intimate images unless the victim pays, "
            "sends more images, or complies with demands. Victim "
            "guidance: do NOT pay, do NOT send more images, do NOT "
            "delete messages (preserve them), stop contact, report to "
            "the platform, the FBI IC3, and — if the victim is a minor "
            "— NCMEC."
        ),
    },
    "nc_ii_abuse": {
        "title": "Nonconsensual Intimate-Image Abuse",
        "understand": (
            "Sharing or threatening to share intimate images without "
            "consent. Preserve URLs and posts before reporting "
            "(reporting can trigger removal that destroys evidence); "
            "use platform nonconsensual-imagery reporting flows; "
            "refer to the Cyber Civil Rights Initiative and law "
            "enforcement."
        ),
    },
    "child_sexual_exploitation": {
        "title": "Child Sexual Exploitation (CSAM)",
        "understand": (
            "Any sexual exploitation of a child, including suspected "
            "child sexual abuse material. REFER IMMEDIATELY. Do not "
            "access, copy, save, forward, or investigate suspected "
            "material — report to the NCMEC CyberTipline and let law "
            "enforcement investigate. Possessing or distributing CSAM "
            "is itself a crime."
        ),
    },
}

# ---------------------------------------------------------------------------
# Referral directory (template — entries describe where to refer, and are
# NOT live contact integrations; this module performs no outreach)
# ---------------------------------------------------------------------------

REFERRAL_DIRECTORY: list[dict[str, Any]] = [
    {
        "org_key": "ncmec_cybertipline",
        "name": "NCMEC CyberTipline (CyberTipline.org)",
        "purpose": (
            "U.S. centralized reporting for suspected child sexual "
            "exploitation, including CSAM and online enticement of "
            "children. Reports go to law enforcement."
        ),
        "what_to_provide": [
            "The platform or service where the content or contact appeared",
            "URLs, usernames, and timestamps as preserved by the reporter",
            "A factual, non-graphic description of what was observed",
        ],
        "note": (
            "Do NOT attach, upload, or forward suspected CSAM. Report "
            "the location and let NCMEC and law enforcement handle it."
        ),
    },
    {
        "org_key": "fbi_ic3",
        "name": "FBI Internet Crime Complaint Center (IC3)",
        "purpose": (
            "Reports of internet-facilitated crime: sextortion, "
            "cyberstalking, threats, and fraud with an online nexus."
        ),
        "what_to_provide": [
            "Chronology of incidents with dates and times",
            "Preserved messages, URLs, and account identifiers",
            "Any financial transaction records (for extortion)",
        ],
        "note": "File at the IC3 portal; keep the complaint confirmation.",
    },
    {
        "org_key": "local_law_enforcement",
        "name": "Local law enforcement / 911 (emergencies)",
        "purpose": (
            "Immediate danger, threats of violence, swatting, stalking "
            "escalation, or any case where the victim's physical safety "
            "is at risk."
        ),
        "what_to_provide": [
            "Preserved evidence package (screenshots with timestamps, URLs)",
            "The case timeline from this framework",
            "Any platform report confirmation numbers",
        ],
        "note": (
            "For emergencies, call 911 (or the local emergency number) "
            "first — documentation can wait."
        ),
    },
    {
        "org_key": "crisis_text_line",
        "name": "Crisis Text Line",
        "purpose": (
            "Crisis support for a victim in distress — text-based, "
            "available 24/7."
        ),
        "what_to_provide": [
            "Nothing evidentiary — this is victim support, not reporting"
        ],
        "note": "A safety-plan resource, not an investigative channel.",
    },
    {
        "org_key": "988_lifeline",
        "name": "988 Suicide and Crisis Lifeline",
        "purpose": (
            "U.S. crisis support for victims experiencing suicidal "
            "thoughts or acute distress."
        ),
        "what_to_provide": ["Nothing evidentiary — victim support only"],
        "note": "A safety-plan resource, not an investigative channel.",
    },
    {
        "org_key": "ndvh",
        "name": "National Domestic Violence Hotline",
        "purpose": (
            "Support and safety planning when online abuse overlaps "
            "with intimate-partner violence."
        ),
        "what_to_provide": ["Nothing evidentiary — victim support only"],
        "note": "A safety-plan resource; advocates can help plan next steps.",
    },
    {
        "org_key": "ccri",
        "name": "Cyber Civil Rights Initiative (CCRI)",
        "purpose": (
            "Specialist support for nonconsensual intimate-image abuse: "
            "victim resources and guidance on removal and reporting."
        ),
        "what_to_provide": [
            "URLs where the imagery appears (preserved before reporting)",
            "Platform report confirmation numbers",
        ],
        "note": (
            "CCRI also maintains guidance on platform-specific "
            "nonconsensual-imagery reporting flows."
        ),
    },
    {
        "org_key": "stopbullying",
        "name": "StopBullying.gov",
        "purpose": (
            "U.S. federal guidance on cyberbullying: what to do, how to "
            "report to schools and platforms, and when to involve law "
            "enforcement."
        ),
        "what_to_provide": [
            "Preserved messages and posts with timestamps",
            "School contact details, if school-based",
        ],
        "note": "Guidance resource; schools have their own reporting duties.",
    },
    {
        "org_key": "victimconnect",
        "name": "VictimConnect Resource Center",
        "purpose": (
            "Confidential referrals to local victim services for any "
            "crime victim in the U.S."
        ),
        "what_to_provide": ["A summary of what happened and what is needed"],
        "note": "Referral hub, not an investigative body.",
    },
    {
        "org_key": "stop_it_now",
        "name": "Stop It Now! Helpline",
        "purpose": (
            "Guidance for adults concerned about a child's safety or "
            "about concerning behavior — prevention-focused support."
        ),
        "what_to_provide": ["A factual description of the concern"],
        "note": "Support and guidance, not an investigative body.",
    },
]

# ---------------------------------------------------------------------------
# Playbooks (data): ordered preserve → report → refer steps per category.
# Every step cites its authority. No step can express an out-of-vocabulary
# action — validated at import.
# ---------------------------------------------------------------------------

def _step(step_id: str, action: str, title: str, detail: str, authority: str) -> dict:
    return {
        "step_id": step_id,
        "action": action,
        "title": title,
        "detail": detail,
        "authority": authority,
    }


PLAYBOOKS: dict[str, dict[str, Any]] = {
    "internet_trolling": {
        "title": "Internet Trolling",
        "no_investigation": False,
        "steps": [
            _step(
                "preserve-1", "preserve", "Preserve the posts",
                "Screenshot the trolling posts with the poster's handle, "
                "timestamps, and the page URL visible. Save the URLs in a "
                "text note. Do not edit or crop out context.",
                "Platform help centers (in-app reporting requires the post URL); "
                "evidence-preservation best practice (screenshots with metadata)",
            ),
            _step(
                "safety-1", "safety_plan", "Do not engage; protect the account",
                "Do not reply to the troll. Mute or block the account; set "
                "the profile to limit who can comment or message.",
                "Platform safety centers (block/mute/privacy controls)",
            ),
            _step(
                "report-1", "report", "Report to the platform",
                "Use the platform's in-app report flow for harassment or "
                "hateful conduct, referencing the preserved URLs.",
                "Platform help centers (X, Instagram, TikTok, Facebook reporting flows)",
            ),
            _step(
                "document-1", "document", "Log the incident",
                "Record date, platform, handle, URLs, and what action was "
                "taken. If it becomes targeted or repeated, re-triage as "
                "cyberharassment.",
                "Trauma-informed documentation best practice (contemporaneous notes)",
            ),
            _step(
                "refer-1", "refer", "Refer onward if it escalates",
                "If the trolling becomes targeted, repeated, or threatening, "
                "re-triage to cyberharassment or cyberstalking and refer to "
                "law enforcement with the preserved log.",
                "Platform help centers (escalation paths); local law enforcement",
            ),
        ],
    },
    "swatting": {
        "title": "Swatting",
        "no_investigation": False,
        "steps": [
            _step(
                "safety-1", "safety_plan", "Treat as an emergency first",
                "If you believe a swatting call is in progress or imminent, "
                "contact emergency services (911 or local emergency number) "
                "immediately. Tell dispatchers you believe the report is a "
                "swatting attempt. Follow responders' instructions exactly.",
                "FBI guidance on swatting response; local emergency procedures",
            ),
            _step(
                "preserve-1", "preserve", "Preserve related messages",
                "Screenshot any messages, posts, or calls connected to the "
                "incident (threats to 'swat', livestream chat, voicemails) "
                "with timestamps and sender identifiers visible.",
                "Evidence-preservation best practice (screenshots with metadata)",
            ),
            _step(
                "document-1", "document", "Write a contemporaneous timeline",
                "Record what happened, when, who was present, and the "
                "incident or dispatch reference number if one was issued.",
                "Trauma-informed documentation best practice (contemporaneous notes)",
            ),
            _step(
                "report-1", "report", "Report to the FBI IC3",
                "File a complaint with the FBI Internet Crime Complaint "
                "Center describing the false emergency report and attaching "
                "the preserved evidence.",
                "FBI Internet Crime Complaint Center (IC3)",
            ),
            _step(
                "refer-1", "refer", "Refer to local law enforcement",
                "Give the preserved evidence package and IC3 confirmation "
                "to local law enforcement; ask about proactive "
                "flagging of your address with dispatch where available.",
                "Local law enforcement; FBI swatting guidance",
            ),
        ],
    },
    "cyberbullying": {
        "title": "Cyberbullying",
        "no_investigation": False,
        "steps": [
            _step(
                "safety-1", "safety_plan", "Safety plan with a trusted adult",
                "The minor tells a trusted adult (parent, guardian, school "
                "counselor). Review who can contact the minor online; "
                "tighten privacy settings together. If the minor expresses "
                "self-harm, use the 988 Lifeline or Crisis Text Line.",
                "StopBullying.gov; 988 Suicide and Crisis Lifeline; Crisis Text Line",
            ),
            _step(
                "preserve-1", "preserve", "Preserve the messages and posts",
                "Screenshot harassing messages, comments, and posts with "
                "sender names, timestamps, and URLs visible. Save originals "
                "— do not delete anything. Keep the device that received "
                "them.",
                "StopBullying.gov (save evidence); evidence-preservation best practice",
            ),
            _step(
                "report-1", "report", "Report to the platform",
                "Use the platform's report flow for bullying or harassment "
                "(most platforms have a dedicated under-18 reporting path). "
                "Keep confirmation numbers.",
                "Platform help centers (Instagram, TikTok, Snapchat, YouTube reporting flows)",
            ),
            _step(
                "report-2", "report", "Report to the school",
                "If the bullying involves classmates, report to the school "
                "with the preserved evidence. Schools have anti-bullying "
                "policies and reporting duties.",
                "StopBullying.gov (report to schools)",
            ),
            _step(
                "document-1", "document", "Keep an incident log",
                "Each incident: date, time, platform, who was involved, "
                "what happened, what was done. A dated log is far more "
                "useful than memory.",
                "Trauma-informed documentation best practice (contemporaneous notes)",
            ),
            _step(
                "refer-1", "refer", "Refer onward if it escalates",
                "If threats, sexual content, or stalking appear, re-triage "
                "to the matching category; refer to local law enforcement "
                "and, for sexual content involving the minor, NCMEC.",
                "StopBullying.gov (when to involve law enforcement); NCMEC CyberTipline",
            ),
        ],
    },
    "cyberharassment": {
        "title": "Cyberharassment",
        "no_investigation": False,
        "steps": [
            _step(
                "preserve-1", "preserve", "Preserve everything with metadata",
                "Screenshot messages, emails, posts, and profiles with "
                "sender identifiers, timestamps, and URLs visible. Export "
                "message histories where the platform allows. Do not "
                "delete — deletion destroys evidence.",
                "Evidence-preservation best practice (screenshots with metadata, "
                "URL preservation, no deletion)",
            ),
            _step(
                "safety-1", "safety_plan", "Reduce contact surface",
                "Block the harassing accounts after preserving evidence. "
                "Review privacy settings and who can find the victim's "
                "profile, phone, or address online.",
                "Platform safety centers (block/report/privacy controls)",
            ),
            _step(
                "document-1", "document", "Build a dated incident log",
                "Each incident: date, time, channel, sender identifier, "
                "summary of content (non-graphic), impact. This log is the "
                "backbone of any later report.",
                "Trauma-informed documentation best practice (contemporaneous notes)",
            ),
            _step(
                "report-1", "report", "Report to each platform",
                "File harassment reports on every platform where it "
                "occurs, referencing preserved URLs and confirmation "
                "numbers from prior reports.",
                "Platform help centers (reporting flows)",
            ),
            _step(
                "refer-1", "refer", "Refer to law enforcement if it escalates",
                "If threats, doxxing, or offline contact appear, refer to "
                "local law enforcement with the evidence package; consider "
                "an FBI IC3 complaint for a multi-platform pattern.",
                "Local law enforcement; FBI Internet Crime Complaint Center (IC3)",
            ),
        ],
    },
    "cyberstalking": {
        "title": "Cyberstalking",
        "no_investigation": False,
        "steps": [
            _step(
                "safety-1", "safety_plan", "Safety plan first",
                "Assess immediate risk. If there are threats or signs the "
                "stalker knows the victim's location, contact emergency "
                "services. Build a plan: trusted contacts informed, "
                "location sharing reviewed, home and device security "
                "checked. Victim-support orgs can help plan.",
                "National Domestic Violence Hotline (safety planning); "
                "VictimConnect Resource Center",
            ),
            _step(
                "preserve-1", "preserve", "Preserve the full trail",
                "Screenshot messages, profile views, fake accounts, and "
                "location-tagged posts with identifiers and timestamps. "
                "Export chat histories. Preserve — do not delete — "
                "anything the stalker sent.",
                "Evidence-preservation best practice (screenshots with metadata, "
                "URL preservation, no deletion)",
            ),
            _step(
                "document-1", "document", "Maintain a stalking log",
                "Every incident gets a dated entry: what, when, where "
                "online, any offline correlate. Note what is verified "
                "versus what is only suspected — 'unknown' is an honest "
                "entry.",
                "Trauma-informed documentation best practice; attribution "
                "discipline (lead vs verified vs unknown)",
            ),
            _step(
                "report-1", "report", "Report to platforms",
                "Report impersonation, fake accounts, and harassment on "
                "each platform. Request preservation of account records "
                "where the platform offers a law-enforcement channel — "
                "only law enforcement can make that request.",
                "Platform help centers; platform law-enforcement portals",
            ),
            _step(
                "refer-1", "refer", "Refer to law enforcement",
                "Bring the log and preserved evidence to local law "
                "enforcement. Cyberstalking is a crime under 18 U.S.C. "
                "§ 2261A (legal information, not advice) and many state "
                "laws.",
                "Local law enforcement; FBI Internet Crime Complaint Center (IC3); "
                "18 U.S.C. § 2261A (federal cyberstalking statute)",
            ),
        ],
    },
    "sextortion": {
        "title": "Sextortion",
        "no_investigation": False,
        "steps": [
            _step(
                "safety-1", "safety_plan", "Stop, do not pay, do not comply",
                "Do NOT pay. Do NOT send more images. Do NOT continue "
                "contact — stop replying after preserving. If the victim "
                "is a minor, a trusted adult is brought in immediately "
                "and NCMEC is the referral.",
                "FBI guidance on sextortion; NCMEC (for minors)",
            ),
            _step(
                "preserve-1", "preserve", "Preserve before blocking",
                "Screenshot the threats, the demanding account's profile, "
                "and timestamps BEFORE blocking. Save message exports. Do "
                "not delete — the threats are evidence.",
                "FBI guidance (preserve evidence); evidence-preservation best practice",
            ),
            _step(
                "report-1", "report", "Report to the platform",
                "Report the account for sextortion/extortion in the "
                "platform's flow. Keep the confirmation.",
                "Platform help centers (extortion reporting flows)",
            ),
            _step(
                "document-1", "document", "Record the demand timeline",
                "When the first contact happened, what was demanded, what "
                "was threatened, and each contact since — dated and "
                "non-graphic.",
                "Trauma-informed documentation best practice",
            ),
            _step(
                "refer-1", "refer", "Refer to the FBI IC3 and local police",
                "File an FBI IC3 complaint and report to local law "
                "enforcement with the preserved evidence. For a minor "
                "victim, ALSO refer to the NCMEC CyberTipline.",
                "FBI Internet Crime Complaint Center (IC3); NCMEC CyberTipline "
                "(minor victims); local law enforcement",
            ),
        ],
    },
    "nc_ii_abuse": {
        "title": "Nonconsensual Intimate-Image Abuse",
        "no_investigation": False,
        "steps": [
            _step(
                "safety-1", "safety_plan", "Stabilize and support",
                "The victim is not at fault. Connect with a support "
                "resource (Cyber Civil Rights Initiative, Crisis Text "
                "Line) before acting, if needed. Identify a trusted "
                "person to help with the next steps.",
                "Cyber Civil Rights Initiative; Crisis Text Line; "
                "trauma-informed practice",
            ),
            _step(
                "preserve-1", "preserve", "Preserve URLs BEFORE reporting",
                "Screenshot or save the URLs, posts, and profiles where "
                "the imagery appears — with timestamps — BEFORE filing "
                "platform reports, because reporting often triggers "
                "removal that destroys the evidence trail.",
                "Cyber Civil Rights Initiative (preserve first, then report); "
                "evidence-preservation best practice",
            ),
            _step(
                "report-1", "report", "Use nonconsensual-imagery report flows",
                "File reports through each platform's dedicated "
                "nonconsensual-intimate-imagery flow (most major platforms "
                "have one). Keep every confirmation number.",
                "Platform help centers (nonconsensual imagery reporting); "
                "Cyber Civil Rights Initiative",
            ),
            _step(
                "document-1", "document", "Log where it appeared",
                "Each appearance: platform, URL, date seen, date "
                "reported, outcome. Keep it factual and non-graphic.",
                "Trauma-informed documentation best practice",
            ),
            _step(
                "refer-1", "refer", "Refer to CCRI and law enforcement",
                "Refer to the Cyber Civil Rights Initiative for removal "
                "guidance and to local law enforcement — "
                "nonconsensual-image sharing is a crime in most U.S. "
                "states (legal information, not advice).",
                "Cyber Civil Rights Initiative; local law enforcement; "
                "VictimConnect Resource Center",
            ),
        ],
    },
    "child_sexual_exploitation": {
        "title": "Child Sexual Exploitation (CSAM)",
        "no_investigation": True,
        "steps": [
            _step(
                "prohibit-1", "document",
                "Do NOT investigate — record the referral decision",
                "No one using this framework investigates suspected child "
                "sexual exploitation. Do not search for more material, do "
                "not contact any account involved, do not attempt to "
                "identify anyone. Investigation is law enforcement's job. "
                "Record here that this prohibition was read and followed.",
                "NCMEC CyberTipline guidance; this framework's lawful-use rule",
            ),
            _step(
                "preserve-1", "preserve", "Preserve only the reporter's own records",
                "Keep the reporter's own messages, screenshots, URLs, and "
                "timestamps that led to the report. Do NOT access, copy, "
                "save, download, or forward any suspected exploitative "
                "material itself — doing so may be a crime.",
                "NCMEC CyberTipline guidance (report, do not collect); "
                "evidence-preservation best practice (reporter's own records only)",
            ),
            _step(
                "safety-1", "safety_plan", "Protect the child",
                "If a child is believed to be in immediate danger, contact "
                "emergency services (911). Otherwise, ensure a trusted "
                "adult or child-welfare contact is involved and the child "
                "is not left to handle this alone.",
                "Local emergency procedures; child-welfare best practice",
            ),
            _step(
                "report-1", "report", "Report to the NCMEC CyberTipline",
                "File a report at the NCMEC CyberTipline (CyberTipline.org) "
                "with the platform, URLs, usernames, timestamps, and a "
                "factual non-graphic description. NCMEC routes reports to "
                "law enforcement.",
                "NCMEC CyberTipline (CyberTipline.org)",
            ),
            _step(
                "refer-1", "refer", "Refer to law enforcement",
                "Refer to local law enforcement with the CyberTipline "
                "report reference. Do not pursue any independent follow-up.",
                "NCMEC CyberTipline; local law enforcement",
            ),
        ],
    },
}

# ---------------------------------------------------------------------------
# Evidence-preservation checklist (for victims), platform reporting guide
# ---------------------------------------------------------------------------

PRESERVATION_CHECKLIST: list[dict[str, str]] = [
    {
        "item": "Screenshot with context visible",
        "detail": (
            "Capture the sender's name/handle, the message or post, the "
            "date and time, and the page or profile URL — all in the "
            "same screenshot where possible. Do not crop out identifiers."
        ),
        "authority": "Evidence-preservation best practice (screenshots with metadata)",
    },
    {
        "item": "Save the URLs",
        "detail": (
            "Copy the full URL of each post, profile, or message thread "
            "into a dated text note. URLs are how platforms locate the "
            "content later."
        ),
        "authority": "Platform help centers (reporting requires URLs)",
    },
    {
        "item": "Do not delete anything",
        "detail": (
            "Do not delete messages, posts, or accounts involved. "
            "Deletion destroys evidence and can look like tampering."
        ),
        "authority": "Evidence-preservation best practice (no deletion)",
    },
    {
        "item": "Export where possible",
        "detail": (
            "Many platforms let you download your data or export a chat "
            "history. Do this before blocking anyone."
        ),
        "authority": "Platform help centers (data download / export tools)",
    },
    {
        "item": "Back up the evidence",
        "detail": (
            "Copy screenshots and notes to a second location (a trusted "
            "adult's device, a secure folder). Keep originals untouched."
        ),
        "authority": "Evidence-preservation best practice (redundant copies)",
    },
    {
        "item": "Keep a dated incident log",
        "detail": (
            "For each incident: date, time, platform, who was involved, "
            "what happened (non-graphic), and what you did. Write it "
            "the same day — memory fades and logs are trusted."
        ),
        "authority": "Trauma-informed documentation best practice (contemporaneous notes)",
    },
    {
        "item": "Record report confirmations",
        "detail": (
            "Save every platform report confirmation number and the date "
            "filed. Add them to the log."
        ),
        "authority": "Platform help centers (report tracking)",
    },
]

#: Category-specific preservation addenda.
PRESERVATION_ADDENDA: dict[str, list[dict[str, str]]] = {
    "sextortion": [
        {
            "item": "Preserve threats before blocking",
            "detail": (
                "Screenshot the demands and threats first, then block. "
                "The threats are the evidence."
            ),
            "authority": "FBI guidance on sextortion (preserve evidence)",
        },
    ],
    "nc_ii_abuse": [
        {
            "item": "Preserve URLs before reporting",
            "detail": (
                "Save URLs and screenshots of where the imagery appears "
                "BEFORE filing platform reports — reports often trigger "
                "removal, which destroys the trail."
            ),
            "authority": "Cyber Civil Rights Initiative (preserve first, then report)",
        },
    ],
    "swatting": [
        {
            "item": "Keep dispatch references",
            "detail": (
                "Save any incident or dispatch reference numbers, "
                "voicemails, and related messages with timestamps."
            ),
            "authority": "FBI guidance on swatting response",
        },
    ],
    "child_sexual_exploitation": [
        {
            "item": "Preserve only your own records — never the material",
            "detail": (
                "Keep your own messages, URLs, and timestamps that led to "
                "the report. Never access, copy, save, or forward "
                "suspected exploitative material."
            ),
            "authority": "NCMEC CyberTipline guidance (report, do not collect)",
        },
    ],
}

REPORTING_GUIDE: list[dict[str, str]] = [
    {
        "platform": "Instagram",
        "where": "In-app: tap ••• on a post, comment, or profile → Report",
        "what": "Bullying/harassment, hate speech, nudity or sexual activity, sale of illegal content; dedicated under-18 paths exist",
        "authority": "Instagram Help Center (reporting)",
    },
    {
        "platform": "TikTok",
        "where": "Press-and-hold a video or comment → Report; profile → share icon → Report",
        "what": "Harassment and bullying, hateful behavior, minor safety violations",
        "authority": "TikTok Safety Center (reporting)",
    },
    {
        "platform": "X (Twitter)",
        "where": "••• on a post → Report post; profile → ••• → Report",
        "what": "Abusive behavior, hateful conduct, nonconsensual nudity, child sexual exploitation",
        "authority": "X Help Center (reporting abusive behavior)",
    },
    {
        "platform": "Facebook",
        "where": "••• on a post → Report post; profile → ••• → Report",
        "what": "Bullying/harassment, hate speech, nudity or sexual activity",
        "authority": "Facebook Help Center (reporting)",
    },
    {
        "platform": "Snapchat",
        "where": "Press-and-hold a Snap or chat → Report",
        "what": "Harassment, bullying, sexual content involving minors",
        "authority": "Snapchat Safety Center",
    },
    {
        "platform": "YouTube",
        "where": "••• under a video → Report",
        "what": "Harassment or cyberbullying, hateful content, child safety violations",
        "authority": "YouTube Help (report inappropriate content)",
    },
    {
        "platform": "Discord",
        "where": "Right-click a message or user → Report",
        "what": "Harassment, hate speech, child safety violations",
        "authority": "Discord Trust & Safety",
    },
    {
        "platform": "NCMEC CyberTipline",
        "where": "CyberTipline.org — for suspected child sexual exploitation",
        "what": "Suspected CSAM, online enticement of children, child sex trafficking; reports route to law enforcement",
        "authority": "NCMEC CyberTipline (CyberTipline.org)",
    },
    {
        "platform": "FBI IC3",
        "where": "IC3 complaint portal — for internet-facilitated crime",
        "what": "Sextortion, cyberstalking, threats, fraud with an online nexus",
        "authority": "FBI Internet Crime Complaint Center (IC3)",
    },
]

# ---------------------------------------------------------------------------
# Synthetic case files (all non-graphic, all labeled SYNTHETIC).
# These are written scenarios used to exercise preserve → report → refer
# end-to-end. No real people, accounts, or events.
# ---------------------------------------------------------------------------

SYNTHETIC_CASES: list[dict[str, Any]] = [
    {
        "case_ref": "SYN-CB-01",
        "category": "cyberbullying",
        "reporter_role": "parent",
        "summary": (
            "SYNTHETIC SCENARIO. A 14-year-old's public post received "
            "repeated mocking comments from several classmate accounts "
            "over three days. The minor is upset but safe at home. No "
            "threats of violence were made."
        ),
        "immediate_danger": False,
        "involves_minor": True,
        "exercise": "Full preserve → report → refer path with minor-safeguarding.",
    },
    {
        "case_ref": "SYN-SX-01",
        "category": "sextortion",
        "reporter_role": "victim (adult)",
        "summary": (
            "SYNTHETIC SCENARIO. An adult received messages from an "
            "unknown account demanding payment and threatening to share "
            "private photos. No payment was made. The victim preserved "
            "the messages before blocking the account."
        ),
        "immediate_danger": False,
        "involves_minor": False,
        "exercise": "Safety-plan first: do-not-pay guidance, preserve-before-block, FBI IC3 referral.",
    },
    {
        "case_ref": "SYN-CSE-01",
        "category": "child_sexual_exploitation",
        "reporter_role": "concerned adult",
        "summary": (
            "SYNTHETIC SCENARIO. An adult noticed concerning messages "
            "sent to a child by an unknown account and suspects "
            "exploitation. No material was accessed, copied, or "
            "forwarded. The correct outcome is: refer immediately, do "
            "not investigate."
        ),
        "immediate_danger": False,
        "involves_minor": True,
        "exercise": (
            "Refer-immediately path: NCMEC CyberTipline referral "
            "auto-generated at intake; no investigation steps exist."
        ),
    },
    {
        "case_ref": "SYN-SW-01",
        "category": "swatting",
        "reporter_role": "victim",
        "summary": (
            "SYNTHETIC SCENARIO. A person received messages claiming a "
            "false emergency report would be made about their address. "
            "They believe responders could arrive at any time."
        ),
        "immediate_danger": True,
        "involves_minor": False,
        "exercise": "Immediate-danger triage: emergency-services guidance comes first.",
    },
    {
        "case_ref": "SYN-CS-01",
        "category": "cyberstalking",
        "reporter_role": "victim",
        "summary": (
            "SYNTHETIC SCENARIO. An adult reports weeks of unwanted "
            "messages and new fake accounts appearing after each block. "
            "The sender's real identity is not known."
        ),
        "immediate_danger": False,
        "involves_minor": False,
        "exercise": (
            "Attribution discipline: 'unknown' is recorded as an honest "
            "finding; documentation and law-enforcement referral proceed."
        ),
    },
]

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SafeguardError(Exception):
    """Domain error for the safeguard framework (not found, bad transition)."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def validate_action(action: str) -> str:
    """Enforce the closed action vocabulary. Raises on anything else."""
    if action not in ACTIONS:
        raise SafeguardError(
            f"Unknown action {action!r}. The safeguard framework's action "
            f"vocabulary is closed: {', '.join(ACTIONS)}. There is no "
            "'investigate suspect' or 'contact suspect' action — this "
            "framework refers; it does not pursue."
        )
    return action


def validate_non_graphic(text: str, field: str = "text") -> str:
    """Reject graphic/explicit content in case summaries and findings."""
    lowered = (text or "").lower()
    for term in NON_GRAPHIC_FORBIDDEN:
        if term in lowered:
            raise ValidationError(
                {field: f"contains disallowed explicit content ({term!r}). "
                        "Describe scenarios non-graphically."}
            )
    return text or ""


def validate_case_ref(case_ref: str) -> str:
    if not CASE_REF_RE.match(case_ref or ""):
        raise ValidationError(
            {"case_ref": "must be 2–64 chars: letters, digits, '-' or '_'."}
        )
    return case_ref


def _check_no_forbidden_operations(text: str, where: str) -> None:
    lowered = text.lower()
    for phrase in FORBIDDEN_OPERATIONS:
        if phrase.startswith(r"\b"):
            hit = re.search(phrase, lowered)
        else:
            hit = phrase in lowered
        if hit:
            raise SafeguardError(
                f"Forbidden operational phrase {phrase!r} in {where}. "
                "The framework never directs anyone toward a suspected offender."
            )


def _validate_playbooks() -> None:
    """Structural self-check: vocabulary closed, authorities cited,
    no forbidden operations anywhere in the playbook data."""
    for cat, pb in PLAYBOOKS.items():
        if cat not in CATEGORIES:
            raise SafeguardError(f"Playbook for unknown category {cat!r}")
        seen: set[str] = set()
        for step in pb["steps"]:
            validate_action(step["action"])  # raises on out-of-vocabulary
            if step["step_id"] in seen:
                raise SafeguardError(
                    f"Duplicate step_id {step['step_id']!r} in {cat}"
                )
            seen.add(step["step_id"])
            if not step.get("authority") or not str(step["authority"]).strip():
                raise SafeguardError(
                    f"Playbook step {cat}/{step['step_id']} cites no authority. "
                    "Every step must cite its authority."
                )
            _check_no_forbidden_operations(
                f"{step['title']} {step['detail']}", f"playbook {cat}/{step['step_id']}"
            )
        if cat == "child_sexual_exploitation" and not pb.get("no_investigation"):
            raise SafeguardError(
                "The child_sexual_exploitation playbook must be marked no_investigation."
            )
    for sc in SYNTHETIC_CASES:
        validate_non_graphic(sc["summary"], field=f"synthetic case {sc['case_ref']}")
        _check_no_forbidden_operations(sc["summary"], f"synthetic case {sc['case_ref']}")
        if sc["category"] not in CATEGORIES:
            raise SafeguardError(
                f"Synthetic case {sc['case_ref']} has unknown category {sc['category']!r}"
            )
    for entry in REFERRAL_DIRECTORY:
        _check_no_forbidden_operations(
            f"{entry['name']} {entry['purpose']}", f"referral {entry['org_key']}"
        )


_validate_playbooks()

# ---------------------------------------------------------------------------
# DB access helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def get_case(conn: sqlite3.Connection, case_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM safeguard_cases WHERE id = ?", (case_id,)
    ).fetchone()
    if row is None:
        raise SafeguardError(f"Safeguard case {case_id} not found.")
    case = _row_to_dict(row)
    case["guidance"] = json.loads(case["guidance_json"])
    case["immediate_danger"] = bool(case["immediate_danger"])
    case["involves_minor"] = bool(case["involves_minor"])
    case["synthetic"] = bool(case["synthetic"])
    return case


def list_cases(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, case_ref, category, stage, safety_status, created_at "
        "FROM safeguard_cases ORDER BY id"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_playbooks() -> list[dict]:
    return [
        {
            "category": cat,
            "title": CATEGORIES[cat]["title"],
            "understand": CATEGORIES[cat]["understand"],
            "no_investigation": PLAYBOOKS[cat]["no_investigation"],
            "step_count": len(PLAYBOOKS[cat]["steps"]),
        }
        for cat in CATEGORIES
    ]


def get_playbook(category: str) -> dict:
    if category not in PLAYBOOKS:
        raise SafeguardError(f"Unknown category {category!r}.")
    return PLAYBOOKS[category]


def referral_directory() -> list[dict]:
    return [dict(e) for e in REFERRAL_DIRECTORY]


def preservation_checklist(category: str | None = None) -> list[dict]:
    items = [dict(i) for i in PRESERVATION_CHECKLIST]
    if category and category in PRESERVATION_ADDENDA:
        items.extend(dict(i) for i in PRESERVATION_ADDENDA[category])
    return items


def reporting_guide() -> list[dict]:
    return [dict(r) for r in REPORTING_GUIDE]


# ---------------------------------------------------------------------------
# Intake + safety triage
# ---------------------------------------------------------------------------


def _safety_guidance(
    category: str, immediate_danger: bool, involves_minor: bool
) -> tuple[str, list[str]]:
    """Returns (safety_status, guidance). Emergency guidance is always first."""
    guidance: list[str] = []
    if immediate_danger:
        status = "emergency"
        guidance.append(
            "EMERGENCY FIRST: contact emergency services (911 or your local "
            "emergency number) immediately. Swatting, threats of imminent "
            "violence, and any situation where someone could be hurt right "
            "now are handled by emergency responders — documentation and "
            "reporting come after everyone is safe."
        )
    elif involves_minor:
        status = "minor-safeguarding"
        guidance.append(
            "A minor is involved: bring in a trusted adult (parent, "
            "guardian, school counselor) before taking further steps. If "
            "the minor expresses self-harm, contact the 988 Suicide and "
            "Crisis Lifeline or Crisis Text Line."
        )
    else:
        status = "standard"
    if category == "child_sexual_exploitation":
        guidance.append(
            "REFER IMMEDIATELY — DO NOT INVESTIGATE: report to the NCMEC "
            "CyberTipline (CyberTipline.org). Do not access, copy, save, "
            "download, or forward any suspected exploitative material, "
            "and do not contact any account involved. Investigation is "
            "law enforcement's job."
        )
    if category == "sextortion":
        guidance.append(
            "Do NOT pay, do NOT send more images, and do NOT keep "
            "contact — preserve the threats first, then block."
        )
    if not guidance:
        guidance.append(
            "Safety planning first: review who can contact those involved, "
            "tighten privacy settings, and identify a trusted person to "
            "help with the steps below."
        )
    return status, guidance


def intake_case(
    conn: sqlite3.Connection,
    *,
    case_ref: str,
    category: str,
    reporter_role: str,
    summary: str,
    immediate_danger: bool = False,
    involves_minor: bool = False,
) -> dict:
    """Intake a SYNTHETIC case, run safety triage, and open the playbook's
    checklist. CSAM-category intakes auto-generate the NCMEC referral."""
    validate_case_ref(case_ref)
    if category not in CATEGORIES:
        raise ValidationError({"category": f"Unknown category {category!r}."})
    if not (reporter_role or "").strip():
        raise ValidationError({"reporter_role": "reporter_role is required."})
    validate_non_graphic(summary, field="summary")

    safety_status, guidance = _safety_guidance(
        category, immediate_danger, involves_minor
    )
    now = utcnow_iso()
    try:
        cur = conn.execute(
            "INSERT INTO safeguard_cases "
            "(case_ref, category, reporter_role, summary, immediate_danger, "
            " involves_minor, safety_status, guidance_json, stage, synthetic, "
            " created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'triaged', 1, ?)",
            (
                case_ref,
                category,
                reporter_role.strip(),
                summary.strip(),
                1 if immediate_danger else 0,
                1 if involves_minor else 0,
                safety_status,
                json.dumps(guidance),
                now,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValidationError({"case_ref": f"case_ref {case_ref!r} is already in use."}) from exc
    case_id = cur.lastrowid

    for step in PLAYBOOKS[category]["steps"]:
        conn.execute(
            "INSERT INTO safeguard_checklist "
            "(case_id, step_id, action, title, status, note, updated_at) "
            "VALUES (?, ?, ?, ?, 'pending', '', ?)",
            (case_id, step["step_id"], step["action"], step["title"], now),
        )

    # CSAM-category: refer immediately — the NCMEC referral is generated
    # at intake, before any checklist work.
    if category == "child_sexual_exploitation":
        generate_referral(
            conn,
            case_id,
            "ncmec_cybertipline",
            note="Auto-generated at intake: refer immediately, do not investigate.",
        )
    conn.commit()
    return get_case(conn, case_id)


# ---------------------------------------------------------------------------
# Checklist tracking (preserve → report → refer)
# ---------------------------------------------------------------------------


def get_checklist(conn: sqlite3.Connection, case_id: int) -> list[dict]:
    get_case(conn, case_id)  # 404-style guard
    rows = conn.execute(
        "SELECT id, case_id, step_id, action, title, status, note, updated_at "
        "FROM safeguard_checklist WHERE case_id = ? ORDER BY id",
        (case_id,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def checklist_status(conn: sqlite3.Connection, case_id: int) -> dict:
    items = get_checklist(conn, case_id)
    by_status = {"pending": 0, "done": 0, "skipped": 0}
    by_action = {a: {"pending": 0, "done": 0, "skipped": 0} for a in ACTIONS}
    for it in items:
        by_status[it["status"]] += 1
        by_action[it["action"]][it["status"]] += 1
    return {
        "total": len(items),
        "by_status": by_status,
        "by_action": by_action,
        "complete": by_status["pending"] == 0,
    }


def _set_checklist_item(
    conn: sqlite3.Connection, case_id: int, step_id: str, status: str, note: str
) -> dict:
    if status not in ("done", "skipped"):
        raise ValidationError({"status": "status must be 'done' or 'skipped'."})
    get_case(conn, case_id)
    cur = conn.execute(
        "UPDATE safeguard_checklist SET status = ?, note = ?, updated_at = ? "
        "WHERE case_id = ? AND step_id = ?",
        (status, note or "", utcnow_iso(), case_id, step_id),
    )
    if cur.rowcount == 0:
        raise SafeguardError(
            f"Checklist step {step_id!r} not found on case {case_id}."
        )
    # Stage advance: once every preserve/report/safety_plan/document step is
    # resolved, the case is active work; referrals move it to referred.
    st = checklist_status(conn, case_id)
    unresolved = sum(
        by["pending"]
        for action, by in st["by_action"].items()
        if action != "refer"
    )
    stage = "active" if unresolved == 0 else "triaged"
    # Never demote a case that already has a referral.
    n_ref = conn.execute(
        "SELECT COUNT(*) AS c FROM safeguard_referrals WHERE case_id = ?",
        (case_id,),
    ).fetchone()["c"]
    if n_ref > 0:
        stage = "referred"
    conn.execute(
        "UPDATE safeguard_cases SET stage = ? WHERE id = ?", (stage, case_id)
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM safeguard_checklist WHERE case_id = ? AND step_id = ?",
        (case_id, step_id),
    ).fetchone()
    return _row_to_dict(row)


def complete_checklist_item(
    conn: sqlite3.Connection, case_id: int, step_id: str, note: str = ""
) -> dict:
    return _set_checklist_item(conn, case_id, step_id, "done", note)


def skip_checklist_item(
    conn: sqlite3.Connection, case_id: int, step_id: str, reason: str
) -> dict:
    if not (reason or "").strip():
        raise ValidationError({"reason": "Skipping a step requires a documented reason."})
    return _set_checklist_item(conn, case_id, step_id, "skipped", reason.strip())


# ---------------------------------------------------------------------------
# Referrals (directory entries — the framework refers; it never contacts)
# ---------------------------------------------------------------------------


def _directory_entry(org_key: str) -> dict:
    for entry in REFERRAL_DIRECTORY:
        if entry["org_key"] == org_key:
            return entry
    raise ValidationError({"org_key": f"Unknown referral org_key {org_key!r}."})


def generate_referral(
    conn: sqlite3.Connection, case_id: int, org_key: str, note: str = ""
) -> dict:
    """Record a referral decision: where to refer and what to bring.
    This generates *guidance text* — it performs no outreach."""
    case = get_case(conn, case_id)
    entry = _directory_entry(org_key)
    guidance = (
        f"Refer '{case['case_ref']}' ({CATEGORIES[case['category']]['title']}) "
        f"to {entry['name']}. {entry['purpose']} "
        f"Bring: {'; '.join(entry['what_to_provide'])}. Note: {entry['note']}"
    )
    if note:
        guidance += f" Case note: {note.strip()}"
    guidance += (
        " [Synthetic framework output — verify current reporting "
        "channels yourself; this system performs no outreach.]"
    )
    cur = conn.execute(
        "INSERT INTO safeguard_referrals "
        "(case_id, org_key, org_name, purpose, what_to_provide_json, guidance, "
        " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            case_id,
            org_key,
            entry["name"],
            entry["purpose"],
            json.dumps(entry["what_to_provide"]),
            guidance,
            utcnow_iso(),
        ),
    )
    conn.execute(
        "UPDATE safeguard_cases SET stage = 'referred' WHERE id = ? AND stage != 'closed'",
        (case_id,),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM safeguard_referrals WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    referral = _row_to_dict(row)
    referral["what_to_provide"] = json.loads(referral["what_to_provide_json"])
    return referral


def list_referrals(conn: sqlite3.Connection, case_id: int) -> list[dict]:
    get_case(conn, case_id)
    rows = conn.execute(
        "SELECT * FROM safeguard_referrals WHERE case_id = ? ORDER BY id",
        (case_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = _row_to_dict(r)
        d["what_to_provide"] = json.loads(d["what_to_provide_json"])
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Findings — attribution discipline (lead / verified / unknown),
# facts separated from inference (S03 discipline reused)
# ---------------------------------------------------------------------------


def add_finding(
    conn: sqlite3.Connection,
    case_id: int,
    statement: str,
    claim_type: str,
    status: str,
    evidence_ref: str = "",
    confidence: str | None = None,
) -> dict:
    """Record a finding. 'unknown' is an acceptable status. 'verified'
    requires cited evidence; inferences require a confidence level."""
    get_case(conn, case_id)
    if claim_type not in CLAIM_TYPES:
        raise ValidationError({"claim_type": f"claim_type must be one of {CLAIM_TYPES}."})
    if status not in FINDING_STATUSES:
        raise ValidationError({"status": f"status must be one of {FINDING_STATUSES}."})
    validate_non_graphic(statement, field="finding statement")
    if not (statement or "").strip():
        raise ValidationError({"statement": "Finding statement is required."})
    if status == "verified" and not (evidence_ref or "").strip():
        raise ValidationError(
            {"evidence_ref": "'verified' findings must cite evidence. "
                             "Use 'lead' or 'unknown' otherwise."}
        )
    if claim_type == "inference":
        if confidence not in CONFIDENCE_LEVELS:
            raise ValidationError(
                {"confidence": "Inferences must carry a confidence level: "
                               "'low', 'medium', or 'high'."}
            )
    elif confidence is not None:
        raise ValidationError({"confidence": "Facts do not carry confidence levels."})
    cur = conn.execute(
        "INSERT INTO safeguard_findings "
        "(case_id, statement, claim_type, status, confidence, evidence_ref, "
        " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            case_id,
            statement.strip(),
            claim_type,
            status,
            confidence,
            (evidence_ref or "").strip(),
            utcnow_iso(),
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM safeguard_findings WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return _row_to_dict(row)


def list_findings(conn: sqlite3.Connection, case_id: int) -> list[dict]:
    get_case(conn, case_id)
    rows = conn.execute(
        "SELECT * FROM safeguard_findings WHERE case_id = ? ORDER BY id",
        (case_id,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Case detail + close
# ---------------------------------------------------------------------------


def get_case_detail(conn: sqlite3.Connection, case_id: int) -> dict:
    case = get_case(conn, case_id)
    case["checklist"] = get_checklist(conn, case_id)
    case["checklist_status"] = checklist_status(conn, case_id)
    case["referrals"] = list_referrals(conn, case_id)
    case["findings"] = list_findings(conn, case_id)
    case["playbook"] = get_playbook(case["category"])
    case["category_title"] = CATEGORIES[case["category"]]["title"]
    return case


def close_case(conn: sqlite3.Connection, case_id: int) -> dict:
    st = checklist_status(conn, case_id)
    if not st["complete"]:
        raise SafeguardError(
            f"Cannot close case {case_id}: {st['by_status']['pending']} "
            "checklist item(s) still pending. Complete or skip each step "
            "with a documented reason first."
        )
    conn.execute(
        "UPDATE safeguard_cases SET stage = 'closed' WHERE id = ?", (case_id,)
    )
    conn.commit()
    return get_case(conn, case_id)


# ---------------------------------------------------------------------------
# Guided demo (Demo mode): one synthetic case end-to-end
# ---------------------------------------------------------------------------


def run_demo(conn: sqlite3.Connection) -> dict:
    """Run the cyberbullying synthetic case preserve → report → refer,
    end to end, in Demo mode. Returns a summary dict."""
    demo_ref = f"DEMO-CB-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    case = intake_case(
        conn,
        case_ref=demo_ref,
        category="cyberbullying",
        reporter_role="demo (parent)",
        summary=(
            "SYNTHETIC DEMO SCENARIO. A minor's public post received "
            "repeated mocking comments from classmate accounts over "
            "several days. The minor is safe at home; no threats of "
            "violence."
        ),
        immediate_danger=False,
        involves_minor=True,
    )
    case_id = case["id"]
    steps_done: list[str] = []
    for item in get_checklist(conn, case_id):
        if item["action"] == "refer":
            continue  # referral recorded via generate_referral below
        complete_checklist_item(
            conn, case_id, item["step_id"], note="Demo: completed on synthetic fixture."
        )
        steps_done.append(item["step_id"])
    referral = generate_referral(
        conn, case_id, "local_law_enforcement",
        note="Demo escalation path (synthetic).",
    )
    # Mark the playbook's refer step done now that a referral exists.
    for item in get_checklist(conn, case_id):
        if item["action"] == "refer" and item["status"] == "pending":
            complete_checklist_item(
                conn, case_id, item["step_id"],
                note="Demo: referral recorded (no outreach performed).",
            )
            steps_done.append(item["step_id"])
    add_finding(
        conn, case_id,
        "The harassing comments came from classmate accounts (reported by the minor).",
        claim_type="fact", status="lead",
        evidence_ref="demo screenshots SYN-DEMO-01..03",
    )
    add_finding(
        conn, case_id,
        "The real-world identity behind one anonymous commenter account.",
        claim_type="inference", status="unknown", confidence="low",
    )
    close_case(conn, case_id)
    final = get_case_detail(conn, case_id)
    return {
        "case_id": case_id,
        "case_ref": demo_ref,
        "category": "cyberbullying",
        "steps_completed": steps_done,
        "referral_org": referral["org_name"],
        "findings": len(final["findings"]),
        "stage": final["stage"],
        "synthetic": True,
        "mode": "Demo",
        "warning": (
            "Synthetic demo only. This framework refers; it does not "
            "pursue, and it performs no outreach."
        ),
    }
