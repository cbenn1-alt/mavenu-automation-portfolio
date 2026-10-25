"""N02 — Cyber Risk Assessment & Management workbook engine.

=====================================================================
FICTIONAL COMPANY. SYNTHETIC DATA. ILLUSTRATIVE SCORES ONLY.
=====================================================================

This module implements a risk-management workbook for "Synthetic Test
Co.", a FICTIONAL 24-person home-services company invented for this
demonstration. Every asset, threat, likelihood/impact rating, cost, and
effort figure is synthetic. The scores are illustrative worked examples
of the documented scoring rules — they are NEVER an audit opinion, a
certification, or a claim about any real organization.

The module references (imports) the S01 (firewall / monitoring) and S02
(hardening baseline) control identifiers and validates every mapped
control against those live registries instead of duplicating them.

Pipeline::

    asset inventory  ->  threat analysis  ->  likelihood x impact scoring
    ->  risk register  ->  control mapping (S01/S02 refs, validated)
    ->  remediation prioritization (documented, reproducible rule)
    ->  residual-risk recomputation + statement

Status vocabulary: Implemented, Tested, Simulated, Demo.
The scoring engine, register validation, control-reference validation,
prioritization, and residual-risk recomputation are Implemented+Tested;
the company, assets, threats, ratings, costs, and efforts are
Synthetic fixtures (seed data).
"""
from __future__ import annotations

import copy
import json
import sqlite3
from decimal import Decimal
from fractions import Fraction
from typing import Any, Optional

from . import firewall as fw_service
from . import netsec as ns_service
from . import ossec as os_service
from .db import utcnow_iso
from .validation import ValidationError

# ---------------------------------------------------------------------------
# Ethical banner + fictional company profile
# ---------------------------------------------------------------------------

ETHICAL_BANNER = (
    "FICTIONAL COMPANY — SYNTHETIC DATA. Synthetic Test Co. does not "
    "exist; every asset, threat, rating, cost, and effort figure here is "
    "invented. Scores are illustrative worked examples of the documented "
    "rules — NEVER an audit opinion, certification, or statement about a "
    "real organization."
)

COMPANY = {
    "name": "Synthetic Test Co.",
    "fictional": True,
    "profile": (
        "A fictional 24-person residential plumbing/HVAC services company "
        "operating from one leased office suite with a small on-prem server "
        "closet, 12 office workstations, 6 field tablets, a cloud email "
        "tenant, and a line-of-business dispatch application. Invented for "
        "this workbook demonstration; no real business is described."
    ),
    "employees": 24,
    "note": "SYNTHETIC — illustrative fixture only.",
}

ASSET_TYPES = ("hardware", "software", "data", "people", "facilities")

# ---------------------------------------------------------------------------
# Scoring scales (documented, with per-level rationale)
# ---------------------------------------------------------------------------

LIKELIHOOD_SCALE: tuple[dict[str, str], ...] = (
    {"level": 1, "label": "Rare",
     "rationale": "No known occurrence in comparable small businesses; would "
                  "require unusual conditions or a determined, resourced actor."},
    {"level": 2, "label": "Unlikely",
     "rationale": "Possible but not observed in the fixture environment; requires "
                  "meaningful attacker effort or a rare misstep."},
    {"level": 3, "label": "Possible",
     "rationale": "Observed in comparable organizations; plausible within the next "
                  "12 months given current controls."},
    {"level": 4, "label": "Likely",
     "rationale": "Expected within the next 12 months: conditions are favorable "
                  "and similar events are routine in the sector."},
    {"level": 5, "label": "Almost certain",
     "rationale": "Happening now or recurring; existing controls demonstrably "
                  "absent or routinely bypassed."},
)

IMPACT_SCALE: tuple[dict[str, str], ...] = (
    {"level": 1, "label": "Negligible",
     "rationale": "No meaningful effect on confidentiality, integrity, or "
                  "availability; no customer or regulatory consequence."},
    {"level": 2, "label": "Minor",
     "rationale": "Limited C/I/A effect confined to non-critical records or "
                  "systems; recoverable the same day with routine effort."},
    {"level": 3, "label": "Moderate",
     "rationale": "Material C/I/A effect on some customer records or business "
                  "systems; requires deliberate response but not existential."},
    {"level": 4, "label": "Major",
     "rationale": "Severe C/I/A effect: operations disrupted, broad customer "
                  "data exposed, or regulatory notification obligations triggered."},
    {"level": 5, "label": "Catastrophic",
     "rationale": "Business-ending C/I/A effect: total loss of customer trust, "
                  "extended outage, or liabilities the fictional company could "
                  "not absorb."},
)

# Risk band thresholds over score = likelihood x impact (1..25).
BANDS: tuple[tuple[str, int, int], ...] = (
    ("low", 1, 4),
    ("medium", 5, 9),
    ("high", 10, 15),
    ("critical", 16, 25),
)

BAND_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


class RiskError(ValidationError):
    """Raised for invalid risk workbook input (bad level, unknown ref, ...).

    Carries a single-message field_errors dict so the web layer's
    ValidationError handler renders it as a 400.
    """

    def __init__(self, message: str):
        super().__init__({"risk": message})


def _check_level(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
        raise RiskError(f"{name} must be an integer 1..5, got {value!r}")
    return value


def band_for_score(score: int) -> str:
    """Map a 1..25 risk score to its band. Raises RiskError out of range."""
    if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 25:
        raise RiskError(f"score must be an integer 1..25, got {score!r}")
    for name, lo, hi in BANDS:
        if lo <= score <= hi:
            return name
    raise RiskError(f"score out of band range: {score!r}")  # pragma: no cover


def score_risk(likelihood: int, impact_c: int, impact_i: int, impact_a: int) -> dict[str, int | str]:
    """Score one risk: impact = max(C, I, A); score = likelihood x impact.

    Returns {"likelihood", "impact", "impact_c", "impact_i", "impact_a",
    "score", "band"}. Every field carries the documented scale levels; the
    calling register entry adds the written rationale for WHY those levels.
    """
    likelihood = _check_level("likelihood", likelihood)
    impact_c = _check_level("impact_c (confidentiality)", impact_c)
    impact_i = _check_level("impact_i (integrity)", impact_i)
    impact_a = _check_level("impact_a (availability)", impact_a)
    impact = max(impact_c, impact_i, impact_a)
    score = likelihood * impact
    return {
        "likelihood": likelihood,
        "impact_c": impact_c,
        "impact_i": impact_i,
        "impact_a": impact_a,
        "impact": impact,
        "score": score,
        "band": band_for_score(score),
    }


# ---------------------------------------------------------------------------
# Control registry: validated references to S01 / S02 (never duplicated)
# ---------------------------------------------------------------------------

def _build_control_registry() -> dict[str, dict[str, str]]:
    """Index every S01/S02 control by a stable reference string.

    Refs: ``S02:<baseline_id>``, ``S01:<firewall_rule_id>``,
    ``S01:alert:<alert_type>``. The registry is built live from the
    S01/S02 modules, so a renamed or removed control breaks loudly here
    instead of silently mapping to a stale copy.
    """
    reg: dict[str, dict[str, str]] = {}
    for b in os_service.BASELINES:
        reg[f"S02:{b['id']}"] = {
            "project": "S02",
            "kind": "hardening-baseline",
            "title": b.get("title", b["id"]),
            "category": b.get("category", ""),
        }
    for rule in fw_service.RULESET:
        reg[f"S01:{rule.rule_id}"] = {
            "project": "S01",
            "kind": "firewall-rule",
            "title": rule.description,
            "category": "network-segmentation",
        }
    for alert_id, alert in ns_service.ALERT_TYPES.items():
        reg[f"S01:alert:{alert_id}"] = {
            "project": "S01",
            "kind": "monitoring-alert",
            "title": alert["description"],
            "category": "detection",
        }
    return reg


CONTROL_REGISTRY: dict[str, dict[str, str]] = _build_control_registry()


def validate_control_ref(ref: str) -> dict[str, str]:
    """Validate one control reference. ``GAP`` is the explicit accepted-gap
    marker (the register entry must carry its reason); anything else must
    exist in the live S01/S02 registry."""
    if ref == "GAP":
        return {"project": "—", "kind": "accepted-gap", "title": "Explicit accepted gap",
                "category": "gap"}
    try:
        return CONTROL_REGISTRY[ref]
    except KeyError:
        raise RiskError(f"unknown control reference {ref!r}; valid refs are the "
                        f"S01/S02 registry ids or 'GAP'") from None


# ---------------------------------------------------------------------------
# Synthetic asset inventory
# ---------------------------------------------------------------------------

ASSETS: tuple[dict[str, Any], ...] = (
    {"asset_id": "A-01", "name": "Office workstation fleet", "asset_type": "hardware",
     "description": "12 synthetic office desktops used by dispatch and admin staff.",
     "location": "Main office (leased suite)"},
    {"asset_id": "A-02", "name": "On-prem file server (FS-01)", "asset_type": "hardware",
     "description": "Single synthetic file/print server hosting shared drives.",
     "location": "Server closet"},
    {"asset_id": "A-03", "name": "Field tablets (6)", "asset_type": "hardware",
     "description": "6 synthetic tablets used by field technicians for job tickets.",
     "location": "In the field / office"},
    {"asset_id": "A-04", "name": "Office router / firewall appliance", "asset_type": "hardware",
     "description": "Synthetic edge device separating office, guest, and IoT segments.",
     "location": "Server closet"},
    {"asset_id": "A-05", "name": "Dispatch application (synthetic LOB app)", "asset_type": "software",
     "description": "Synthetic line-of-business scheduling/dispatch application.",
     "location": "On-prem / vendor-hosted (synthetic)"},
    {"asset_id": "A-06", "name": "Cloud email tenant (synthetic)", "asset_type": "software",
     "description": "Synthetic hosted email tenant for all staff mailboxes.",
     "location": "Cloud (synthetic)"},
    {"asset_id": "A-07", "name": "Backup software + NAS", "asset_type": "software",
     "description": "Synthetic nightly backup job to a local NAS appliance.",
     "location": "Server closet"},
    {"asset_id": "A-08", "name": "Customer PII database", "asset_type": "data",
     "description": "Synthetic customer records: names, addresses, phone numbers.",
     "location": "File server (A-02)"},
    {"asset_id": "A-09", "name": "Payment card records (tokenized)", "asset_type": "data",
     "description": "Synthetic tokenized payment references; no full card numbers stored.",
     "location": "Dispatch app (A-05)"},
    {"asset_id": "A-10", "name": "Employee HR records", "asset_type": "data",
     "description": "Synthetic HR files: payroll, tax forms, emergency contacts.",
     "location": "File server (A-02)"},
    {"asset_id": "A-11", "name": "Office staff (privileged users)", "asset_type": "people",
     "description": "8 synthetic office staff with elevated application rights.",
     "location": "Main office"},
    {"asset_id": "A-12", "name": "Field technicians (mobile users)", "asset_type": "people",
     "description": "16 synthetic technicians using tablets and personal phones.",
     "location": "In the field"},
    {"asset_id": "A-13", "name": "Main office (leased suite)", "asset_type": "facilities",
     "description": "Synthetic leased office suite; shared building, landlord-managed entry.",
     "location": "Fargo, ND (synthetic address)"},
    {"asset_id": "A-14", "name": "Server closet", "asset_type": "facilities",
     "description": "Synthetic locking closet housing the file server, NAS, and router.",
     "location": "Inside main office"},
)

ASSET_INDEX = {a["asset_id"]: a for a in ASSETS}

# ---------------------------------------------------------------------------
# Threat catalog (each mapped to an S01/S02 vulnerability class)
# ---------------------------------------------------------------------------

THREATS: tuple[dict[str, Any], ...] = (
    {"threat_id": "T-01", "name": "Phishing → credential theft",
     "description": "Deceptive email harvests staff credentials for email or app access.",
     "vuln_class": "S02 weak-credentials",
     "applies_to": ("people", "software", "data")},
    {"threat_id": "T-02", "name": "Ransomware via unpatched endpoint",
     "description": "Malware exploits a missing security patch, then encrypts local data.",
     "vuln_class": "S02 unpatched-software",
     "applies_to": ("hardware", "software")},
    {"threat_id": "T-03", "name": "Insider privilege abuse",
     "description": "A trusted user exceeds their role and reads or alters records.",
     "vuln_class": "S02 excessive-privilege",
     "applies_to": ("people", "data", "hardware")},
    {"threat_id": "T-04", "name": "Remote-admin brute force",
     "description": "Automated password guessing against SSH/remote management.",
     "vuln_class": "S02 ssh-misconfiguration",
     "applies_to": ("hardware", "software")},
    {"threat_id": "T-05", "name": "WAN inbound probing",
     "description": "External scanning of the office edge for open services.",
     "vuln_class": "S01 firewall-exposure",
     "applies_to": ("hardware", "software")},
    {"threat_id": "T-06", "name": "Lateral movement across segments",
     "description": "A compromised guest/IoT device reaches office systems.",
     "vuln_class": "S01 missing-segmentation",
     "applies_to": ("hardware",)},
    {"threat_id": "T-07", "name": "Data exfiltration over DNS",
     "description": "Stolen data leaves disguised as DNS queries.",
     "vuln_class": "S01 monitoring-gap",
     "applies_to": ("data", "software")},
    {"threat_id": "T-08", "name": "Lost or stolen field tablet",
     "description": "A technician's tablet is lost or stolen with cached job data.",
     "vuln_class": "S02 account-policy (partial — no mobile-device baseline exists)",
     "applies_to": ("hardware", "data")},
    {"threat_id": "T-09", "name": "Exposed unneeded service",
     "description": "An unnecessary network service is left running and reachable.",
     "vuln_class": "S02 unnecessary-services",
     "applies_to": ("software", "hardware")},
    {"threat_id": "T-10", "name": "Facility break-in",
     "description": "Unauthorized physical entry to the office or server closet.",
     "vuln_class": "none — physical security is outside S01/S02 scope",
     "applies_to": ("facilities", "hardware")},
)

THREAT_INDEX = {t["threat_id"]: t for t in THREATS}

# ---------------------------------------------------------------------------
# Risk register (synthetic fixture). Every entry traces to asset + threat +
# >=1 validated control ref ("GAP" = explicit accepted gap with reason).
# Each score cites its likelihood/impact scale levels in the rationale.
# ---------------------------------------------------------------------------

REGISTER_FIXTURE: tuple[dict[str, Any], ...] = (
    {
        "risk_id": "R-01", "asset_id": "A-08", "threat_id": "T-01",
        "likelihood": 4,
        "likelihood_rationale": (
            "L4 Likely: staff receive vendor/invoice email daily and handle "
            "customer records by email; phishing is the routine initial vector "
            "for this profile."),
        "impact_c": 4, "impact_i": 3, "impact_a": 1,
        "impact_rationale": (
            "Impact 4 (max of C4/I3/A1): C4 Major — customer PII exfiltration "
            "triggers breach-notification obligations for the fictional company; "
            "I3 Moderate — altered contact records; A1 Negligible — no outage."),
        "controls": [
            {"ref": "S02:acct-02",
             "note": "Password policy raises the bar after credential theft."},
            {"ref": "S01:alert:failed_logins_burst",
             "note": "Detects post-phish credential-stuffing bursts."},
        ],
        "treatment": "mitigate",
    },
    {
        "risk_id": "R-02", "asset_id": "A-05", "threat_id": "T-02",
        "likelihood": 3,
        "likelihood_rationale": (
            "L3 Possible: the dispatch app runs on endpoints with a history of "
            "deferred patching; ransomware crews target exactly this profile."),
        "impact_c": 2, "impact_i": 4, "impact_a": 5,
        "impact_rationale": (
            "Impact 5 (max of C2/I4/A5): A5 Catastrophic — dispatch outage halts "
            "all field work; I4 Major — schedule integrity lost; C2 Minor — "
            "limited customer data in tickets."),
        "controls": [
            {"ref": "S02:pat-01", "note": "Patch within the policy window."},
            {"ref": "S02:pat-02", "note": "Zero pending security updates."},
        ],
        "treatment": "mitigate",
    },
    {
        "risk_id": "R-03", "asset_id": "A-02", "threat_id": "T-03",
        "likelihood": 3,
        "likelihood_rationale": (
            "L3 Possible: 8 staff share broad file-server rights; no periodic "
            "access review exists in the fixture."),
        "impact_c": 4, "impact_i": 4, "impact_a": 2,
        "impact_rationale": (
            "Impact 4 (max of C4/I4/A2): C4/I4 Major — broad read/write to PII "
            "and HR shares; A2 Minor — no deletion of the server itself."),
        "controls": [
            {"ref": "S02:acct-04", "note": "Least-privilege sudo/share review."},
            {"ref": "S02:perm-01", "note": "Sensitive files at policy mode."},
        ],
        "treatment": "mitigate",
    },
    {
        "risk_id": "R-04", "asset_id": "A-02", "threat_id": "T-04",
        "likelihood": 4,
        "likelihood_rationale": (
            "L4 Likely: SSH is password-enabled and reachable from the office "
            "LAN; brute-force bots are routine background noise."),
        "impact_c": 3, "impact_i": 3, "impact_a": 2,
        "impact_rationale": (
            "Impact 3 (max of C3/I3/A2): C3/I3 Moderate — full share access on "
            "compromise; A2 Minor — service stays up."),
        "controls": [
            {"ref": "S02:auth-01", "note": "Disable SSH password authentication."},
            {"ref": "S02:auth-02", "note": "Disable direct root login."},
            {"ref": "S02:auth-03", "note": "Limit authentication attempts."},
            {"ref": "S01:alert:failed_logins_burst",
             "note": "Alerts on 5+ failed SSH logins in 10 minutes."},
        ],
        "treatment": "mitigate",
    },
    {
        "risk_id": "R-05", "asset_id": "A-04", "threat_id": "T-05",
        "likelihood": 5,
        "likelihood_rationale": (
            "L5 Almost certain: any internet-facing edge device is probed "
            "continuously; the fixture edge is directly reachable."),
        "impact_c": 2, "impact_i": 2, "impact_a": 2,
        "impact_rationale": (
            "Impact 2 (max of C2/I2/A2): C2/I2/A2 Minor — probing alone exposes "
            "little; the edge denies inbound by default."),
        "controls": [
            {"ref": "S01:deny-wan-inbound", "note": "Explicit WAN inbound deny."},
            {"ref": "S01:alert:port_scan_detected",
             "note": "Detects multi-port probes from one WAN source."},
        ],
        "treatment": "mitigate",
    },
    {
        "risk_id": "R-06", "asset_id": "A-04", "threat_id": "T-06",
        "likelihood": 3,
        "likelihood_rationale": (
            "L3 Possible: guest Wi-Fi shares the same edge device; a compromised "
            "guest/IoT device is a plausible pivot."),
        "impact_c": 3, "impact_i": 3, "impact_a": 3,
        "impact_rationale": (
            "Impact 3 (max of C3/I3/A3): C3/I3/A3 Moderate — office LAN reach "
            "means workstation and share exposure, no full takeover."),
        "controls": [
            {"ref": "S01:deny-inter-vlan",
             "note": "Catch-all inter-VLAN deny blocks the pivot."},
            {"ref": "S01:deny-iot-internal",
             "note": "IoT segment is internet-only."},
            {"ref": "S01:alert:rogue_dhcp_server",
             "note": "Detects rogue infrastructure on the LAN."},
        ],
        "treatment": "mitigate",
    },
    {
        "risk_id": "R-07", "asset_id": "A-08", "threat_id": "T-07",
        "likelihood": 2,
        "likelihood_rationale": (
            "L2 Unlikely: DNS exfiltration requires an already-compromised "
            "host with tooling the fixture has not observed."),
        "impact_c": 5, "impact_i": 2, "impact_a": 1,
        "impact_rationale": (
            "Impact 5 (max of C5/I2/A1): C5 Catastrophic — bulk PII database "
            "exfiltrated silently; I2 Minor; A1 Negligible."),
        "controls": [
            {"ref": "S01:alert:dns_tunneling_suspect",
             "note": "Flags abnormal DNS query volume/shape."},
            {"ref": "S01:allow-office-dns",
             "note": "Office DNS pinned through the gateway for inspection."},
        ],
        "treatment": "mitigate",
    },
    {
        "risk_id": "R-08", "asset_id": "A-03", "threat_id": "T-08",
        "likelihood": 4,
        "likelihood_rationale": (
            "L4 Likely: 6 tablets travel daily in work trucks; the fixture "
            "loses roughly one device per year."),
        "impact_c": 4, "impact_i": 2, "impact_a": 1,
        "impact_rationale": (
            "Impact 4 (max of C4/I2/A1): C4 Major — cached job tickets hold "
            "customer names/addresses/phones; I2 Minor; A1 Negligible."),
        "controls": [
            {"ref": "GAP",
             "reason": ("No S01/S02 baseline covers mobile-device encryption or "
                        "remote wipe; accepted as a gap pending RM-07 "
                        "(tablet MDM enrollment).")},
        ],
        "treatment": "mitigate",
    },
    {
        "risk_id": "R-09", "asset_id": "A-06", "threat_id": "T-01",
        "likelihood": 4,
        "likelihood_rationale": (
            "L4 Likely: same daily email exposure as R-01; mailbox takeover "
            "is the common second stage."),
        "impact_c": 3, "impact_i": 3, "impact_a": 2,
        "impact_rationale": (
            "Impact 3 (max of C3/I3/A2): C3/I3 Moderate — mailbox contents and "
            "sent-as impersonation; A2 Minor — tenant stays up."),
        "controls": [
            {"ref": "S02:acct-02",
             "note": "Password policy on all staff accounts."},
        ],
        "treatment": "mitigate",
    },
    {
        "risk_id": "R-10", "asset_id": "A-01", "threat_id": "T-02",
        "likelihood": 3,
        "likelihood_rationale": (
            "L3 Possible: workstations lag patches the same way endpoints "
            "do in R-02."),
        "impact_c": 2, "impact_i": 3, "impact_a": 4,
        "impact_rationale": (
            "Impact 4 (max of C2/I3/A4): A4 Major — fleet-wide encryption "
            "halts dispatch; I3 Moderate; C2 Minor."),
        "controls": [
            {"ref": "S02:pat-01", "note": "Patch within the policy window."},
            {"ref": "S02:svc-01", "note": "Remove unneeded services (attack surface)."},
        ],
        "treatment": "mitigate",
    },
    {
        "risk_id": "R-11", "asset_id": "A-07", "threat_id": "T-02",
        "likelihood": 3,
        "likelihood_rationale": (
            "L3 Possible: the NAS is reachable from the office LAN, so the "
            "same ransomware path as R-02/R-10 reaches it."),
        "impact_c": 2, "impact_i": 5, "impact_a": 5,
        "impact_rationale": (
            "Impact 5 (max of C2/I5/A5): I5/A5 Catastrophic — encrypted backups "
            "remove the recovery path entirely; C2 Minor."),
        "controls": [
            {"ref": "S02:perm-01", "note": "Backup files at policy mode."},
            {"ref": "S02:acct-04", "note": "Least privilege on backup credentials."},
        ],
        "treatment": "mitigate",
    },
    {
        "risk_id": "R-12", "asset_id": "A-13", "threat_id": "T-10",
        "likelihood": 2,
        "likelihood_rationale": (
            "L2 Unlikely: shared building with landlord-managed entry and "
            "foot traffic; after-hours entry requires effort."),
        "impact_c": 2, "impact_i": 2, "impact_a": 3,
        "impact_rationale": (
            "Impact 3 (max of C2/I2/A3): A3 Moderate — office disruption and "
            "workstation access; C2/I2 Minor."),
        "controls": [
            {"ref": "GAP",
             "reason": ("Physical security is outside S01/S02 scope; accepted "
                        "pending RM-08 (closet lock upgrade + visitor log).")},
        ],
        "treatment": "mitigate",
    },
    {
        "risk_id": "R-13", "asset_id": "A-05", "threat_id": "T-09",
        "likelihood": 3,
        "likelihood_rationale": (
            "L3 Possible: the dispatch host runs vendor defaults with "
            "unreviewed services; nobody has audited them in the fixture."),
        "impact_c": 3, "impact_i": 3, "impact_a": 3,
        "impact_rationale": (
            "Impact 3 (max of C3/I3/A3): C3/I3/A3 Moderate — an exposed service "
            "is a foothold, not yet data loss."),
        "controls": [
            {"ref": "S02:svc-01", "note": "No unneeded running services."},
            {"ref": "S02:svc-02", "note": "No unneeded services at boot."},
            {"ref": "S01:deny-wan-inbound", "note": "Edge denies inbound regardless."},
        ],
        "treatment": "mitigate",
    },
    {
        "risk_id": "R-14", "asset_id": "A-11", "threat_id": "T-03",
        "likelihood": 2,
        "likelihood_rationale": (
            "L2 Unlikely: requires a trusted employee to act maliciously or "
            "carelessly; no such event in the fixture history."),
        "impact_c": 3, "impact_i": 3, "impact_a": 2,
        "impact_rationale": (
            "Impact 3 (max of C3/I3/A2): C3/I3 Moderate — staff can reach PII "
            "and schedules; A2 Minor."),
        "controls": [
            {"ref": "S02:acct-04", "note": "Least-privilege review."},
            {"ref": "S02:acct-03", "note": "No stale accounts lingering."},
        ],
        "treatment": "mitigate",
    },
    {
        "risk_id": "R-15", "asset_id": "A-09", "threat_id": "T-07",
        "likelihood": 2,
        "likelihood_rationale": (
            "L2 Unlikely: same precondition as R-07 (compromised host with "
            "tooling), not observed in the fixture."),
        "impact_c": 4, "impact_i": 2, "impact_a": 1,
        "impact_rationale": (
            "Impact 4 (max of C4/I2/A1): C4 Major — payment references exposed "
            "(tokenized, which caps the blast radius); I2 Minor; A1 Negligible."),
        "controls": [
            {"ref": "S01:alert:dns_tunneling_suspect",
             "note": "Flags abnormal DNS exfiltration patterns."},
            {"ref": "S02:perm-01", "note": "Payment records at policy mode."},
        ],
        "treatment": "mitigate",
    },
    {
        "risk_id": "R-16", "asset_id": "A-14", "threat_id": "T-10",
        "likelihood": 2,
        "likelihood_rationale": (
            "L2 Unlikely: same building controls as R-12; the closet is "
            "inside the leased suite."),
        "impact_c": 3, "impact_i": 2, "impact_a": 3,
        "impact_rationale": (
            "Impact 3 (max of C3/I2/A3): C3/A3 Moderate — direct access to the "
            "file server and router; I2 Minor."),
        "controls": [
            {"ref": "GAP",
             "reason": ("Physical security is outside S01/S02 scope; accepted "
                        "pending RM-08 (closet lock upgrade + visitor log).")},
        ],
        "treatment": "mitigate",
    },
    {
        "risk_id": "R-17", "asset_id": "A-02", "threat_id": "T-10",
        "likelihood": 1,
        "likelihood_rationale": (
            "L1 Rare: requires defeating the building entry AND the suite AND "
            "the closet lock; no such event in the fixture history."),
        "impact_c": 3, "impact_i": 2, "impact_a": 2,
        "impact_rationale": (
            "Impact 3 (max of C3/I2/A2): C3 Moderate — share contents readable "
            "with physical disk access; I2/A2 Minor."),
        "controls": [
            {"ref": "GAP",
             "reason": ("Physical security is outside S01/S02 scope; accepted — "
                        "low inherent score (3) makes further action "
                        "disproportionate for the fixture.")},
        ],
        "treatment": "accept",
    },
)


def build_register(
    fixture: tuple[dict[str, Any], ...] = REGISTER_FIXTURE,
) -> list[dict[str, Any]]:
    """Validate the fixture structurally and compute every score.

    Structural guarantees (asserted in tests): every entry traces to a
    known asset AND a known threat whose ``applies_to`` covers the asset's
    type; every entry carries >=1 control ref; every control ref validates
    against the live S01/S02 registry (or is GAP with a written reason);
    every score carries its scale levels plus written rationale.
    """
    register: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in fixture:
        rid = raw["risk_id"]
        if rid in seen:
            raise RiskError(f"duplicate risk_id {rid!r}")
        seen.add(rid)
        asset = ASSET_INDEX.get(raw["asset_id"])
        if asset is None:
            raise RiskError(f"{rid}: unknown asset_id {raw['asset_id']!r}")
        threat = THREAT_INDEX.get(raw["threat_id"])
        if threat is None:
            raise RiskError(f"{rid}: unknown threat_id {raw['threat_id']!r}")
        if asset["asset_type"] not in threat["applies_to"]:
            raise RiskError(
                f"{rid}: threat {threat['threat_id']} does not apply to "
                f"asset type {asset['asset_type']!r}")
        controls = raw.get("controls") or []
        if not controls:
            raise RiskError(f"{rid}: every register entry needs >=1 control ref")
        resolved = []
        for c in controls:
            info = validate_control_ref(c["ref"])
            if c["ref"] == "GAP" and not c.get("reason"):
                raise RiskError(f"{rid}: GAP control requires a written reason")
            resolved.append({
                "ref": c["ref"],
                "project": info["project"],
                "kind": info["kind"],
                "title": info["title"],
                "note": c.get("note", ""),
                "reason": c.get("reason", ""),
            })
        if not raw.get("likelihood_rationale") or not raw.get("impact_rationale"):
            raise RiskError(f"{rid}: score must carry written rationale")
        scored = score_risk(raw["likelihood"], raw["impact_c"],
                            raw["impact_i"], raw["impact_a"])
        register.append({
            "risk_id": rid,
            "asset_id": asset["asset_id"],
            "asset_name": asset["name"],
            "asset_type": asset["asset_type"],
            "threat_id": threat["threat_id"],
            "threat_name": threat["name"],
            "vuln_class": threat["vuln_class"],
            "likelihood": scored["likelihood"],
            "likelihood_rationale": raw["likelihood_rationale"],
            "impact_c": scored["impact_c"],
            "impact_i": scored["impact_i"],
            "impact_a": scored["impact_a"],
            "impact": scored["impact"],
            "impact_rationale": raw["impact_rationale"],
            "score": scored["score"],
            "band": scored["band"],
            "controls": resolved,
            "treatment": raw.get("treatment", "mitigate"),
        })
    register.sort(key=lambda r: (-BAND_ORDER[r["band"]], -r["score"], r["risk_id"]))
    return register


def register_audit(register: list[dict[str, Any]]) -> list[str]:
    """Check control-mapping completeness. Returns a list of violations
    (empty = complete). Rule: every high/critical risk must map to >=1 real
    control OR carry an explicit accepted-gap record."""
    violations: list[str] = []
    for r in register:
        if r["band"] in ("high", "critical"):
            real = [c for c in r["controls"] if c["ref"] != "GAP"]
            gaps = [c for c in r["controls"]
                    if c["ref"] == "GAP" and c["reason"]]
            if not real and not gaps:
                violations.append(
                    f"{r['risk_id']}: {r['band']} risk has no control and no "
                    "accepted-gap record")
    return violations


# ---------------------------------------------------------------------------
# Remediation planner (synthetic costs/efforts, documented reproducible rule)
# ---------------------------------------------------------------------------

# Prioritization rule (documented, reproducible):
#   ratio = risk_reduction / effort_hours   (risk_reduction = sum of inherent
#   score minus residual score over affected risks; effort_hours >= 1 guard)
#   order = ratio DESC, then rem_id ASC (deterministic tie-break).
# Same inputs -> identical order; shuffling input order cannot change output.
PRIORITIZATION_RULE = (
    "Order remediations by risk-reduction-per-effort ratio "
    "(reduction / effort_hours, exact Fraction arithmetic) descending; "
    "ties broken by remediation id ascending. Deterministic: identical "
    "inputs always yield identical order regardless of input order."
)

REMEDIATION_FIXTURE: tuple[dict[str, Any], ...] = (
    {
        "rem_id": "RM-01", "title": "Phishing-resistant MFA on email + PII access",
        "description": ("Enroll all staff in MFA for the email tenant and PII "
                        "database access (synthetic rollout plan)."),
        "cost_usd_cents": 120000, "cost_basis": "synthetic estimate",
        "effort_hours": 24, "effort_basis": "synthetic estimate",
        "effects": [
            {"risk_id": "R-01", "field": "likelihood", "new_value": 2},
            {"risk_id": "R-09", "field": "likelihood", "new_value": 2},
        ],
    },
    {
        "rem_id": "RM-02", "title": "Automated patching cadence (endpoints + server)",
        "description": ("Weekly automated patch window for workstations, file "
                        "server, and dispatch host (synthetic schedule)."),
        "cost_usd_cents": 80000, "cost_basis": "synthetic estimate",
        "effort_hours": 16, "effort_basis": "synthetic estimate",
        "effects": [
            {"risk_id": "R-02", "field": "likelihood", "new_value": 1},
            {"risk_id": "R-10", "field": "likelihood", "new_value": 1},
        ],
    },
    {
        "rem_id": "RM-03", "title": "SSH hardening (key-only, no root, attempt limit)",
        "description": ("Apply the S02 authentication baselines to the file "
                        "server: key-only SSH, no direct root, attempt limit."),
        "cost_usd_cents": 20000, "cost_basis": "synthetic estimate",
        "effort_hours": 8, "effort_basis": "synthetic estimate",
        "effects": [
            {"risk_id": "R-04", "field": "likelihood", "new_value": 1},
        ],
    },
    {
        "rem_id": "RM-04", "title": "Immutable offline backup copy",
        "description": ("Add a weekly offline/immutable backup copy so ransomware "
                        "cannot encrypt every recovery path (synthetic design)."),
        "cost_usd_cents": 150000, "cost_basis": "synthetic estimate",
        "effort_hours": 20, "effort_basis": "synthetic estimate",
        "effects": [
            {"risk_id": "R-11", "field": "impact_i", "new_value": 2},
            {"risk_id": "R-11", "field": "impact_a", "new_value": 2},
        ],
    },
    {
        "rem_id": "RM-05", "title": "Enable S01 segmentation + monitoring on the edge",
        "description": ("Enforce the inter-VLAN/guest/IoT denies and switch on the "
                        "S01 alert types covering probing, lateral movement, and "
                        "DNS exfiltration (synthetic rollout)."),
        "cost_usd_cents": 60000, "cost_basis": "synthetic estimate",
        "effort_hours": 12, "effort_basis": "synthetic estimate",
        "effects": [
            {"risk_id": "R-05", "field": "likelihood", "new_value": 3},
            {"risk_id": "R-06", "field": "likelihood", "new_value": 1},
            {"risk_id": "R-07", "field": "likelihood", "new_value": 1},
            {"risk_id": "R-15", "field": "likelihood", "new_value": 1},
        ],
    },
    {
        "rem_id": "RM-06", "title": "Least-privilege review + stale-account cleanup",
        "description": ("Quarterly access review of file shares and removal of "
                        "stale accounts (synthetic procedure)."),
        "cost_usd_cents": 0, "cost_basis": "synthetic estimate (staff time only)",
        "effort_hours": 16, "effort_basis": "synthetic estimate",
        "effects": [
            {"risk_id": "R-03", "field": "likelihood", "new_value": 1},
            {"risk_id": "R-14", "field": "likelihood", "new_value": 1},
        ],
    },
    {
        "rem_id": "RM-07", "title": "Tablet MDM enrollment + remote wipe (closes R-08 gap)",
        "description": ("Enroll field tablets in MDM with encryption enforced and "
                        "remote wipe; converts the R-08 accepted gap into a control."),
        "cost_usd_cents": 240000, "cost_basis": "synthetic estimate",
        "effort_hours": 24, "effort_basis": "synthetic estimate",
        "effects": [
            {"risk_id": "R-08", "field": "likelihood", "new_value": 1},
        ],
    },
    {
        "rem_id": "RM-08", "title": "Server-closet lock upgrade + visitor log",
        "description": ("Upgrade the server-closet lock and keep a visitor log; "
                        "physical measure outside S01/S02 scope (synthetic)."),
        "cost_usd_cents": 90000, "cost_basis": "synthetic estimate",
        "effort_hours": 10, "effort_basis": "synthetic estimate",
        "effects": [
            {"risk_id": "R-12", "field": "likelihood", "new_value": 1},
            {"risk_id": "R-16", "field": "likelihood", "new_value": 1},
        ],
    },
)

EFFECT_FIELDS = ("likelihood", "impact_c", "impact_i", "impact_a")


def _apply_effect(entry: dict[str, Any], field: str, new_value: int) -> dict[str, Any]:
    if field not in EFFECT_FIELDS:
        raise RiskError(f"unknown effect field {field!r}")
    _check_level(field, new_value)
    entry = copy.deepcopy(entry)
    entry[field] = new_value
    scored = score_risk(entry["likelihood"], entry["impact_c"],
                        entry["impact_i"], entry["impact_a"])
    entry.update({k: scored[k] for k in ("impact", "score", "band")})
    return entry


def apply_remediations(
    register: list[dict[str, Any]],
    remediations: tuple[dict[str, Any], ...] = REMEDIATION_FIXTURE,
) -> list[dict[str, Any]]:
    """Apply remediation effects (in rem_id order) and recompute scores.

    Returns the residual register. Effects only ever lower a level (new
    value must be <= current), so residual <= inherent per risk.
    """
    residual = {r["risk_id"]: copy.deepcopy(r) for r in register}
    by_id = {r["risk_id"] for r in register}
    for rem in sorted(remediations, key=lambda x: x["rem_id"]):
        for eff in rem["effects"]:
            rid = eff["risk_id"]
            if rid not in by_id:
                raise RiskError(f"{rem['rem_id']}: unknown risk {rid!r}")
            current = residual[rid][eff["field"]]
            if eff["new_value"] > current:
                raise RiskError(
                    f"{rem['rem_id']}: effect would raise {rid}.{eff['field']} "
                    f"({current} -> {eff['new_value']}); remediations only reduce")
            residual[rid] = _apply_effect(residual[rid], eff["field"], eff["new_value"])
            residual[rid].setdefault("applied_remediations", []).append(rem["rem_id"])
    out = list(residual.values())
    out.sort(key=lambda r: (-BAND_ORDER[r["band"]], -r["score"], r["risk_id"]))
    return out


def build_remediations(
    register: list[dict[str, Any]],
    fixture: tuple[dict[str, Any], ...] = REMEDIATION_FIXTURE,
) -> list[dict[str, Any]]:
    """Attach computed reduction + ratio to each remediation (plan order
    unchanged here — see prioritize()). Reduction = sum over affected risks
    of (inherent score - residual score after ONLY this remediation)."""
    by_id = {r["risk_id"]: r for r in register}
    planned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in fixture:
        if raw["rem_id"] in seen:
            raise RiskError(f"duplicate rem_id {raw['rem_id']!r}")
        seen.add(raw["rem_id"])
        for eff in raw["effects"]:
            if eff["risk_id"] not in by_id:
                raise RiskError(f"{raw['rem_id']}: unknown risk {eff['risk_id']!r}")
            if eff["field"] not in EFFECT_FIELDS:
                raise RiskError(f"{raw['rem_id']}: bad effect field {eff['field']!r}")
        # reduction from this remediation alone, summed per AFFECTED RISK
        # (a remediation may carry several effects on one risk; the risk's
        # score delta must be counted once, not once per effect)
        solo = apply_remediations(register, (raw,))
        solo_by_id = {r["risk_id"]: r for r in solo}
        affected = sorted({e["risk_id"] for e in raw["effects"]})
        reduction = sum(
            by_id[rid]["score"] - solo_by_id[rid]["score"] for rid in affected
        )
        effort = raw["effort_hours"]
        if not isinstance(effort, int) or isinstance(effort, bool) or effort < 0:
            raise RiskError(f"{raw['rem_id']}: effort_hours must be a non-negative int")
        ratio = Fraction(reduction, max(effort, 1))  # effort >= 1 guard: documented
        cost = (Decimal(raw["cost_usd_cents"]) / 100).quantize(Decimal("0.01"))
        planned.append({
            "rem_id": raw["rem_id"],
            "title": raw["title"],
            "description": raw["description"],
            "cost_usd": str(cost),
            "cost_basis": raw["cost_basis"],
            "effort_hours": effort,
            "effort_basis": raw["effort_basis"],
            "effects": copy.deepcopy(raw["effects"]),
            "affected_risks": sorted({e["risk_id"] for e in raw["effects"]}),
            "risk_reduction": reduction,
            "ratio": ratio,  # Fraction; JSON views render as float/str
        })
    return planned


def prioritize(remediations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order remediations per PRIORITIZATION_RULE. Deterministic: input
    order cannot change the output."""
    return sorted(remediations,
                  key=lambda r: (-r["ratio"], r["rem_id"]))


def register_totals(register: list[dict[str, Any]]) -> dict[str, Any]:
    band_counts = {name: 0 for name, _, _ in BANDS}
    for r in register:
        band_counts[r["band"]] += 1
    return {
        "count": len(register),
        "total_score": sum(r["score"] for r in register),
        "band_counts": band_counts,
    }


def residual_statement(register: list[dict[str, Any]]) -> dict[str, Any]:
    """Full residual-risk statement: residual register, per-risk deltas,
    before/after totals that reconcile."""
    residual = apply_remediations(register)
    inherent = register_totals(register)
    after = register_totals(residual)
    res_by_id = {r["risk_id"]: r for r in residual}
    deltas = []
    for r in register:
        res = res_by_id[r["risk_id"]]
        deltas.append({
            "risk_id": r["risk_id"],
            "inherent_score": r["score"],
            "inherent_band": r["band"],
            "residual_score": res["score"],
            "residual_band": res["band"],
            "delta": r["score"] - res["score"],
            "applied_remediations": res.get("applied_remediations", []),
        })
    deltas.sort(key=lambda d: (-d["delta"], d["risk_id"]))
    assert inherent["total_score"] - after["total_score"] == sum(d["delta"] for d in deltas)
    return {
        "inherent": inherent,
        "residual": after,
        "total_reduction": inherent["total_score"] - after["total_score"],
        "deltas": deltas,
        "risks": residual,
        "memo": (
            "RESIDUAL-RISK MEMO (SYNTHETIC — illustrative, not an audit opinion). "
            f"After applying all {len(REMEDIATION_FIXTURE)} planned remediations to the "
            f"fictional {COMPANY['name']} register, the total inherent score of "
            f"{inherent['total_score']} falls to {after['total_score']} "
            f"(reduction {inherent['total_score'] - after['total_score']}). "
            f"Critical risks: {inherent['band_counts']['critical']} -> "
            f"{after['band_counts']['critical']}; high risks: "
            f"{inherent['band_counts']['high']} -> {after['band_counts']['high']}. "
            "Remaining medium risks are accepted by the fictional owner in this "
            "fixture or await a future review cycle. Residual risk is never zero: "
            "unremediated risks (e.g. R-13 exposed service review cadence, R-17 "
            "accepted physical risk) keep their inherent scores by design."
        ),
    }


# ---------------------------------------------------------------------------
# Serialization helpers (JSON-safe views for web/API)
# ---------------------------------------------------------------------------

def _jsonable_remediation(r: dict[str, Any]) -> dict[str, Any]:
    out = dict(r)
    out["ratio"] = float(r["ratio"])
    out["ratio_exact"] = str(r["ratio"])
    return out


def scales_doc() -> dict[str, Any]:
    return {
        "likelihood_scale": [dict(s) for s in LIKELIHOOD_SCALE],
        "impact_scale": [dict(s) for s in IMPACT_SCALE],
        "scoring_rule": "score = likelihood x impact (1..25); impact = max(C, I, A)",
        "bands": [{"band": n, "min": lo, "max": hi} for n, lo, hi in BANDS],
        "prioritization_rule": PRIORITIZATION_RULE,
    }


# ---------------------------------------------------------------------------
# SQLite persistence
# ---------------------------------------------------------------------------

def seed_demo(conn: sqlite3.Connection) -> dict[str, int]:
    """Seed the synthetic N02 workbook. Idempotent: clears prior N02 rows
    first, so re-seeding is deterministic."""
    register = build_register()
    stmt = residual_statement(register)
    remediations = build_remediations(register)
    cur = conn.cursor()
    for table in ("risk_snapshots", "risk_remediation_effects",
                  "risk_remediations", "risk_register",
                  "risk_threats", "risk_assets"):
        cur.execute(f"DELETE FROM {table}")
    for a in ASSETS:
        cur.execute(
            "INSERT INTO risk_assets (asset_id, name, asset_type, description, location)"
            " VALUES (?, ?, ?, ?, ?)",
            (a["asset_id"], a["name"], a["asset_type"], a["description"], a["location"]),
        )
    for t in THREATS:
        cur.execute(
            "INSERT INTO risk_threats (threat_id, name, description, vuln_class, applies_to)"
            " VALUES (?, ?, ?, ?, ?)",
            (t["threat_id"], t["name"], t["description"], t["vuln_class"],
             json.dumps(list(t["applies_to"]))),
        )
    for r in register:
        cur.execute(
            """INSERT INTO risk_register
               (risk_id, asset_id, threat_id, likelihood, impact_c, impact_i, impact_a,
                likelihood_rationale, impact_rationale, controls_json, treatment)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r["risk_id"], r["asset_id"], r["threat_id"], r["likelihood"],
             r["impact_c"], r["impact_i"], r["impact_a"],
             r["likelihood_rationale"], r["impact_rationale"],
             json.dumps(r["controls"]), r["treatment"]),
        )
    for raw in REMEDIATION_FIXTURE:
        cur.execute(
            """INSERT INTO risk_remediations
               (rem_id, title, description, cost_usd_cents, cost_basis,
                effort_hours, effort_basis)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (raw["rem_id"], raw["title"], raw["description"],
             raw["cost_usd_cents"], raw["cost_basis"],
             raw["effort_hours"], raw["effort_basis"]),
        )
        for eff in raw["effects"]:
            cur.execute(
                "INSERT INTO risk_remediation_effects (rem_id, risk_id, field, new_value)"
                " VALUES (?, ?, ?, ?)",
                (raw["rem_id"], eff["risk_id"], eff["field"], eff["new_value"]),
            )
    created = utcnow_iso()
    for label, payload in (("inherent", {
            "totals": stmt["inherent"],
            "risks": [{k: r[k] for k in ("risk_id", "score", "band")} for r in register]}),
                           ("residual", {
            "totals": stmt["residual"],
            "total_reduction": stmt["total_reduction"],
            "deltas": stmt["deltas"]})):
        cur.execute(
            "INSERT INTO risk_snapshots (label, created_at, payload_json)"
            " VALUES (?, ?, ?)",
            (label, created, json.dumps(payload)),
        )
    conn.commit()
    return {"assets": len(ASSETS), "threats": len(THREATS),
            "risks": len(register), "remediations": len(remediations),
            "snapshots": 2}


def _row_register(row: sqlite3.Row) -> dict[str, Any]:
    scored = score_risk(row["likelihood"], row["impact_c"],
                        row["impact_i"], row["impact_a"])
    asset = ASSET_INDEX[row["asset_id"]]
    threat = THREAT_INDEX[row["threat_id"]]
    controls = json.loads(row["controls_json"])
    resolved = []
    for c in controls:
        info = validate_control_ref(c["ref"])
        resolved.append({**c, "project": info["project"],
                         "kind": info["kind"], "title": info["title"]})
    return {
        "risk_id": row["risk_id"],
        "asset_id": row["asset_id"], "asset_name": asset["name"],
        "asset_type": asset["asset_type"],
        "threat_id": row["threat_id"], "threat_name": threat["name"],
        "vuln_class": threat["vuln_class"],
        "likelihood": row["likelihood"],
        "likelihood_rationale": row["likelihood_rationale"],
        "impact_c": row["impact_c"], "impact_i": row["impact_i"],
        "impact_a": row["impact_a"], "impact": scored["impact"],
        "impact_rationale": row["impact_rationale"],
        "score": scored["score"], "band": scored["band"],
        "controls": resolved, "treatment": row["treatment"],
    }


def list_assets(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT asset_id, name, asset_type, description, location"
        " FROM risk_assets ORDER BY asset_id")]


def list_threats(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT threat_id, name, description, vuln_class, applies_to"
        " FROM risk_threats ORDER BY threat_id")
    return [{**dict(r), "applies_to": json.loads(r["applies_to"])} for r in rows]


def list_risks(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM risk_register")
    out = [_row_register(r) for r in rows]
    out.sort(key=lambda r: (-BAND_ORDER[r["band"]], -r["score"], r["risk_id"]))
    return out


def list_remediations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    register = list_risks(conn)
    rows = conn.execute("SELECT * FROM risk_remediations")
    raws = []
    for row in rows:
        effs = conn.execute(
            "SELECT risk_id, field, new_value FROM risk_remediation_effects"
            " WHERE rem_id = ? ORDER BY risk_id, field",
            (row["rem_id"],)).fetchall()
        raws.append({
            "rem_id": row["rem_id"], "title": row["title"],
            "description": row["description"],
            "cost_usd_cents": row["cost_usd_cents"],
            "cost_basis": row["cost_basis"],
            "effort_hours": row["effort_hours"],
            "effort_basis": row["effort_basis"],
            "effects": [dict(e) for e in effs],
        })
    built = build_remediations(register, tuple(raws))
    return [_jsonable_remediation(r) for r in prioritize(built)]


def get_residual_report(conn: sqlite3.Connection) -> dict[str, Any]:
    register = list_risks(conn)
    stmt = residual_statement(register)
    stmt["risks"] = [{
        "risk_id": r["risk_id"], "asset_name": r["asset_name"],
        "threat_name": r["threat_name"], "likelihood": r["likelihood"],
        "impact": r["impact"], "score": r["score"], "band": r["band"],
        "applied_remediations": r.get("applied_remediations", []),
    } for r in stmt["risks"]]
    return stmt


def list_snapshots(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, label, created_at, payload_json FROM risk_snapshots ORDER BY id")
    return [{**dict(r), "payload": json.loads(r["payload_json"])} for r in rows]


def seeded(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT COUNT(*) c FROM risk_assets").fetchone()["c"] > 0
