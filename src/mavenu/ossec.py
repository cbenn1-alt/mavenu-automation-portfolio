"""S02 — OS Architecture & Vulnerabilities: Privilege Boundaries & Hardening.

Defense-documented-as-code. Baselines as structured data plus verification
functions that evaluate a *simulated system-state snapshot* (a dict fixture
representing a training VM's configuration — the schema is defined below);
vulnerability-class records as description -> detection -> remediation ->
verification; and a remediation simulator that applies fixes to the
simulated state so re-running verification proves the fix (before/after
evidence).

The lab VM is a SIMULATION. Nothing here touches a real machine: there is
no shell access, no SSH client, no package manager, no privilege operation
of any kind in this module — verification reads a Python dict, remediation
returns a *transformed copy* of a Python dict. All states, accounts,
services, and findings are synthetic fixtures invented for training.

Defensive only: this module documents how to DETECT and FIX configuration
weaknesses. It contains no exploit code, no exploitation workflow, and no
zero-day material.

AUTHORIZATION WARNING: the techniques this project documents (baseline
verification, remediation of vulnerable configurations) must never be
applied to systems you do not own or do not have explicit, written
authorization to assess.
"""
from __future__ import annotations

import copy
import sqlite3
from typing import Any, Callable, Optional

from .db import utcnow_iso

# ---------------------------------------------------------------------------
# Simulated system-state schema
# ---------------------------------------------------------------------------
# A "lab VM state" is a plain Python dict of this shape. It is a training
# fixture — invented data describing an intentionally vulnerable practice
# image — not a read from any real machine.
#
#   {
#     "label": "lab-vm-vulnerable",
#     "os": {"name": str, "kernel": str, "latest_kernel": str},
#     "patch": {"last_patch_days_ago": int, "pending_security_updates": int},
#     "accounts": [ {"name": str, "uid": int, "password_set": bool,
#                    "password_strength": "weak"|"strong", "locked": bool,
#                    "sudo": bool, "last_login_days_ago": int} ],
#     "ssh": {"enabled": bool, "password_auth": bool,
#             "permit_root_login": bool, "max_auth_tries": int},
#     "services": [ {"name": str, "running": bool, "enabled": bool,
#                    "version": str, "latest_version": str, "needed": bool} ],
#     "files": [ {"path": str, "mode": str ("0o640"),
#                 "owner": str, "suid": bool, "justified": bool,
#                 "expected_mode": str} ],
#   }
#
# Note on "password_strength": this is a *declared policy marker* on the
# fixture (weak = would fail the lab password policy; strong = meets it).
# This module never reads, stores, or tests real credentials, and it never
# attempts authentication against anything.

STATE_REQUIRED_TOP_KEYS = (
    "label", "os", "patch", "accounts", "ssh", "services", "files")

POLICY_PATCH_MAX_DAYS = 30
POLICY_SSH_MAX_AUTH_TRIES = 4
POLICY_STALE_LOGIN_DAYS = 90


def validate_state(state: dict[str, Any]) -> list[str]:
    """Structural check of a simulated state dict. Returns a list of
    problems (empty = structurally valid)."""
    problems: list[str] = []
    if not isinstance(state, dict):
        return ["state must be a dict"]
    for key in STATE_REQUIRED_TOP_KEYS:
        if key not in state:
            problems.append(f"missing top-level key: {key}")
    if "accounts" in state and not isinstance(state["accounts"], list):
        problems.append("accounts must be a list")
    if "services" in state and not isinstance(state["services"], list):
        problems.append("services must be a list")
    if "files" in state and not isinstance(state["files"], list):
        problems.append("files must be a list")
    return problems


# ---------------------------------------------------------------------------
# Hardening baselines: structured data + verification functions
# ---------------------------------------------------------------------------
CheckFn = Callable[[dict[str, Any]], tuple[bool, str]]
FixFn = Callable[[dict[str, Any]], list[str]]


def _check_single_uid0(state: dict[str, Any]) -> tuple[bool, str]:
    uid0 = [a["name"] for a in state["accounts"] if a.get("uid") == 0]
    others = [n for n in uid0 if n != "root"]
    if others:
        return False, (f"accounts other than root hold uid 0: "
                       f"{', '.join(sorted(others))}")
    if "root" not in uid0:
        return False, "no root account with uid 0 present"
    return True, "root is the only uid-0 account"


def _fix_single_uid0(state: dict[str, Any]) -> list[str]:
    evidence: list[str] = []
    for a in state["accounts"]:
        if a.get("uid") == 0 and a.get("name") != "root":
            a["uid"] = 1001
            a["locked"] = True
            evidence.append(
                f"removed uid 0 from {a['name']!r}: reassigned uid 1001 and "
                f"locked the account")
    return evidence or ["no duplicate uid-0 accounts existed"]


def _check_weak_passwords(state: dict[str, Any]) -> tuple[bool, str]:
    weak = [a["name"] for a in state["accounts"]
            if a.get("password_set") and a.get("password_strength") == "weak"
            and not a.get("locked")]
    if weak:
        return False, (f"active accounts with weak (policy-failing) "
                       f"passwords: {', '.join(sorted(weak))}")
    return True, "no active account carries a weak password marker"


def _fix_weak_passwords(state: dict[str, Any]) -> list[str]:
    evidence: list[str] = []
    for a in state["accounts"]:
        if (a.get("password_set") and a.get("password_strength") == "weak"
                and not a.get("locked")):
            a["password_strength"] = "strong"
            evidence.append(
                f"{a['name']!r}: password replaced with a generated "
                f"passphrase meeting the lab policy (simulated)")
    return evidence or ["no weak passwords to replace"]


def _check_stale_accounts(state: dict[str, Any]) -> tuple[bool, str]:
    stale = [a["name"] for a in state["accounts"]
             if a.get("last_login_days_ago", 0) > POLICY_STALE_LOGIN_DAYS
             and not a.get("locked")]
    if stale:
        return False, (f"stale, still-enabled accounts (> "
                       f"{POLICY_STALE_LOGIN_DAYS} days since login): "
                       f"{', '.join(sorted(stale))}")
    return True, "no stale enabled accounts"


def _fix_stale_accounts(state: dict[str, Any]) -> list[str]:
    evidence: list[str] = []
    for a in state["accounts"]:
        if (a.get("last_login_days_ago", 0) > POLICY_STALE_LOGIN_DAYS
                and not a.get("locked")):
            a["locked"] = True
            evidence.append(f"{a['name']!r}: locked (no login in "
                            f"{a['last_login_days_ago']} days)")
    return evidence or ["no stale accounts to lock"]


def _check_no_extra_sudo(state: dict[str, Any]) -> tuple[bool, str]:
    extra = [a["name"] for a in state["accounts"]
             if a.get("sudo") and a.get("name") != "root"]
    if extra:
        return False, (f"non-root accounts with sudo privilege: "
                       f"{', '.join(sorted(extra))}")
    return True, "sudo is held by root only (per lab least-privilege policy)"


def _fix_no_extra_sudo(state: dict[str, Any]) -> list[str]:
    evidence: list[str] = []
    for a in state["accounts"]:
        if a.get("sudo") and a.get("name") != "root":
            a["sudo"] = False
            evidence.append(f"removed sudo from {a['name']!r}")
    return evidence or ["no extra sudo grants to remove"]


def _check_ssh_password_auth(state: dict[str, Any]) -> tuple[bool, str]:
    ssh = state["ssh"]
    if not ssh.get("enabled"):
        return True, "sshd is not enabled"
    if ssh.get("password_auth"):
        return False, "sshd permits password authentication"
    return True, "sshd password authentication is disabled"


def _fix_ssh_password_auth(state: dict[str, Any]) -> list[str]:
    if state["ssh"].get("password_auth"):
        state["ssh"]["password_auth"] = False
        return ["sshd: PasswordAuthentication set to no (simulated config "
                "change)"]
    return ["sshd password authentication already disabled"]


def _check_ssh_root_login(state: dict[str, Any]) -> tuple[bool, str]:
    ssh = state["ssh"]
    if not ssh.get("enabled"):
        return True, "sshd is not enabled"
    if ssh.get("permit_root_login"):
        return False, "sshd permits direct root login"
    return True, "sshd direct root login is disabled"


def _fix_ssh_root_login(state: dict[str, Any]) -> list[str]:
    if state["ssh"].get("permit_root_login"):
        state["ssh"]["permit_root_login"] = False
        return ["sshd: PermitRootLogin set to no (simulated config change)"]
    return ["sshd root login already disabled"]


def _check_ssh_auth_tries(state: dict[str, Any]) -> tuple[bool, str]:
    ssh = state["ssh"]
    if not ssh.get("enabled"):
        return True, "sshd is not enabled"
    tries = ssh.get("max_auth_tries", 0)
    if tries > POLICY_SSH_MAX_AUTH_TRIES:
        return False, (f"sshd MaxAuthTries is {tries} "
                       f"(policy allows at most {POLICY_SSH_MAX_AUTH_TRIES})")
    return True, f"sshd MaxAuthTries is {tries} (within policy)"


def _fix_ssh_auth_tries(state: dict[str, Any]) -> list[str]:
    if state["ssh"].get("max_auth_tries", 0) > POLICY_SSH_MAX_AUTH_TRIES:
        state["ssh"]["max_auth_tries"] = POLICY_SSH_MAX_AUTH_TRIES
        return [f"sshd: MaxAuthTries set to {POLICY_SSH_MAX_AUTH_TRIES} "
                f"(simulated config change)"]
    return ["sshd MaxAuthTries already within policy"]


def _check_services_minimized(state: dict[str, Any]) -> tuple[bool, str]:
    extra = [s["name"] for s in state["services"]
             if s.get("running") and not s.get("needed")]
    if extra:
        return False, (f"running services not marked needed: "
                       f"{', '.join(sorted(extra))}")
    return True, "every running service is marked needed"


def _fix_services_minimized(state: dict[str, Any]) -> list[str]:
    evidence: list[str] = []
    for s in state["services"]:
        if s.get("running") and not s.get("needed"):
            s["running"] = False
            evidence.append(f"stopped unneeded service {s['name']!r}")
    return evidence or ["no unneeded services running"]


def _check_services_disabled(state: dict[str, Any]) -> tuple[bool, str]:
    extra = [s["name"] for s in state["services"]
             if s.get("enabled") and not s.get("needed")]
    if extra:
        return False, (f"unneeded services still enabled at boot: "
                       f"{', '.join(sorted(extra))}")
    return True, "no unneeded service is enabled at boot"


def _fix_services_disabled(state: dict[str, Any]) -> list[str]:
    evidence: list[str] = []
    for s in state["services"]:
        if s.get("enabled") and not s.get("needed"):
            s["enabled"] = False
            evidence.append(f"disabled {s['name']!r} at boot")
    return evidence or ["no unneeded services enabled at boot"]


def _check_services_patched(state: dict[str, Any]) -> tuple[bool, str]:
    outdated = [s["name"] for s in state["services"]
                if s.get("running")
                and s.get("version") != s.get("latest_version")]
    if outdated:
        return False, (f"running services behind the latest version: "
                       f"{', '.join(sorted(outdated))}")
    return True, "all running services are at their latest version"


def _fix_services_patched(state: dict[str, Any]) -> list[str]:
    evidence: list[str] = []
    for s in state["services"]:
        if s.get("running") and s.get("version") != s.get("latest_version"):
            evidence.append(f"{s['name']!r}: {s['version']} -> "
                            f"{s['latest_version']}")
            s["version"] = s["latest_version"]
    return evidence or ["all running services already current"]


def _check_patch_cadence(state: dict[str, Any]) -> tuple[bool, str]:
    days = state["patch"].get("last_patch_days_ago", 10**9)
    if days > POLICY_PATCH_MAX_DAYS:
        return False, (f"last patch {days} days ago "
                       f"(policy: within {POLICY_PATCH_MAX_DAYS} days)")
    return True, f"last patch {days} days ago (within policy)"


def _fix_patch_cadence(state: dict[str, Any]) -> list[str]:
    state["patch"]["last_patch_days_ago"] = 0
    state["patch"]["pending_security_updates"] = 0
    kernel = state["os"].get("latest_kernel")
    if kernel:
        state["os"]["kernel"] = kernel
    return ["applied pending security updates and rebooted into the latest "
            "kernel (simulated)"]


def _check_pending_updates(state: dict[str, Any]) -> tuple[bool, str]:
    pending = state["patch"].get("pending_security_updates", 0)
    if pending:
        return False, f"{pending} pending security updates"
    return True, "no pending security updates"


def _check_kernel_current(state: dict[str, Any]) -> tuple[bool, str]:
    running, latest = state["os"].get("kernel"), state["os"].get("latest_kernel")
    if running != latest:
        return False, f"running kernel {running}; latest available {latest}"
    return True, f"running kernel {running} is current"


def _check_file_modes(state: dict[str, Any]) -> tuple[bool, str]:
    bad = [f["path"] for f in state["files"]
           if f.get("mode") != f.get("expected_mode")]
    if bad:
        return False, (f"files whose mode differs from policy: "
                       f"{', '.join(sorted(bad))}")
    return True, "all tracked files match their policy mode"


def _fix_file_modes(state: dict[str, Any]) -> list[str]:
    evidence: list[str] = []
    for f in state["files"]:
        if f.get("mode") != f.get("expected_mode"):
            evidence.append(f"{f['path']}: mode {f['mode']} -> "
                            f"{f['expected_mode']}")
            f["mode"] = f["expected_mode"]
    return evidence or ["all tracked files already match policy mode"]


def _check_suid_allowlist(state: dict[str, Any]) -> tuple[bool, str]:
    bad = [f["path"] for f in state["files"]
           if f.get("suid") and not f.get("justified")]
    if bad:
        return False, (f"setuid binaries without a documented justification: "
                       f"{', '.join(sorted(bad))}")
    return True, "every setuid binary has a documented justification"


def _fix_suid_allowlist(state: dict[str, Any]) -> list[str]:
    evidence: list[str] = []
    for f in state["files"]:
        if f.get("suid") and not f.get("justified"):
            f["suid"] = False
            evidence.append(f"removed the setuid bit from {f['path']} "
                            f"(unjustified)")
    return evidence or ["no unjustified setuid binaries"]


# Baseline catalog: every item carries a verification function (check) and a
# simulated remediation (fix). The coverage audit asserts this structurally.
BASELINES: list[dict[str, Any]] = [
    {"id": "acct-01", "category": "account_policy",
     "title": "Single uid-0 account",
     "description": "Only root may hold uid 0. A second uid-0 account is a "
                    "backdoor-class misconfiguration: it grants full kernel-"
                    "level privilege while hiding behind an ordinary name.",
     "expected": "root is the only account with uid 0",
     "remediation": "Remove uid 0 from the duplicate account and lock it.",
     "check": _check_single_uid0, "fix": _fix_single_uid0},
    {"id": "acct-02", "category": "account_policy",
     "title": "No weak passwords",
     "description": "Every active account's password must meet the lab "
                    "password policy (the fixture records a policy marker, "
                    "never a real credential). Weak credentials remain the "
                    "most common initial-access vector.",
     "expected": "no active account has a weak password marker",
     "remediation": "Replace weak passwords with generated passphrases "
                    "meeting the policy.",
     "check": _check_weak_passwords, "fix": _fix_weak_passwords},
    {"id": "acct-03", "category": "account_policy",
     "title": "No stale accounts",
     "description": "Accounts that have not logged in within "
                    f"{POLICY_STALE_LOGIN_DAYS} days must be disabled. "
                    "Dormant accounts are forgotten attack surface.",
     "expected": "no enabled account is stale",
     "remediation": "Lock accounts with no recent login.",
     "check": _check_stale_accounts, "fix": _fix_stale_accounts},
    {"id": "acct-04", "category": "account_policy",
     "title": "Least-privilege sudo",
     "description": "Sudo grants administrative privilege; it must be held "
                    "only where the role requires it. Broad sudo is "
                    "privilege escalation waiting for a trigger.",
     "expected": "no non-root account holds sudo",
     "remediation": "Remove sudo from accounts that do not require it.",
     "check": _check_no_extra_sudo, "fix": _fix_no_extra_sudo},
    {"id": "auth-01", "category": "authentication",
     "title": "SSH password authentication disabled",
     "description": "Password auth over SSH invites credential guessing. "
                    "Key-based auth (managed by the lab operator outside "
                    "this simulator) is the policy.",
     "expected": "PasswordAuthentication no",
     "remediation": "Set PasswordAuthentication no in the sshd config.",
     "check": _check_ssh_password_auth, "fix": _fix_ssh_password_auth},
    {"id": "auth-02", "category": "authentication",
     "title": "SSH direct root login disabled",
     "description": "Direct root login over SSH removes the audit trail of "
                    "which operator acted. Operators log in as themselves "
                    "and elevate deliberately.",
     "expected": "PermitRootLogin no",
     "remediation": "Set PermitRootLogin no in the sshd config.",
     "check": _check_ssh_root_login, "fix": _fix_ssh_root_login},
    {"id": "auth-03", "category": "authentication",
     "title": "SSH authentication attempt limit",
     "description": "Bounding authentication attempts per connection slows "
                    "automated guessing and forces an early disconnect.",
     "expected": f"MaxAuthTries <= {POLICY_SSH_MAX_AUTH_TRIES}",
     "remediation": f"Set MaxAuthTries to {POLICY_SSH_MAX_AUTH_TRIES}.",
     "check": _check_ssh_auth_tries, "fix": _fix_ssh_auth_tries},
    {"id": "svc-01", "category": "service_minimization",
     "title": "No unneeded running services",
     "description": "Every running service is reachable attack surface. "
                    "Services the lab role does not need (legacy or "
                    "convenience daemons) must be stopped.",
     "expected": "every running service is marked needed",
     "remediation": "Stop services not marked needed.",
     "check": _check_services_minimized, "fix": _fix_services_minimized},
    {"id": "svc-02", "category": "service_minimization",
     "title": "No unneeded services at boot",
     "description": "Stopping a service once is not enough: if it is "
                    "enabled at boot, the weakness returns after every "
                    "reboot. Both states must be checked.",
     "expected": "no unneeded service is enabled at boot",
     "remediation": "Disable unneeded services at boot.",
     "check": _check_services_disabled, "fix": _fix_services_disabled},
    {"id": "svc-03", "category": "service_minimization",
     "title": "Running services at latest version",
     "description": "A minimized service set still needs current versions: "
                    "known-vulnerable service versions are exploited at "
                    "scale by automated tooling.",
     "expected": "every running service matches its latest version",
     "remediation": "Update running services to their latest versions.",
     "check": _check_services_patched, "fix": _fix_services_patched},
    {"id": "pat-01", "category": "patch_cadence",
     "title": "Patched within policy window",
     "description": "The lab patch policy requires security updates within "
                    f"{POLICY_PATCH_MAX_DAYS} days. The vulnerable fixture "
                    "is deliberately far past that window.",
     "expected": f"last patch within {POLICY_PATCH_MAX_DAYS} days",
     "remediation": "Apply pending security updates; reboot into the new "
                    "kernel.",
     "check": _check_patch_cadence, "fix": _fix_patch_cadence},
    {"id": "pat-02", "category": "patch_cadence",
     "title": "Zero pending security updates",
     "description": "Known-available security updates are known exposure. "
                    "The count must reach zero at each maintenance window.",
     "expected": "no pending security updates",
     "remediation": "Install all pending security updates.",
     "check": _check_pending_updates, "fix": _fix_services_patched},
    {"id": "pat-03", "category": "patch_cadence",
     "title": "Running kernel is current",
     "description": "Patching without rebooting leaves the old, vulnerable "
                    "kernel running. Verification must confirm the running "
                    "kernel matches the latest installed.",
     "expected": "running kernel equals latest kernel",
     "remediation": "Reboot into the latest installed kernel.",
     "check": _check_kernel_current, "fix": _fix_patch_cadence},
    {"id": "perm-01", "category": "file_permissions",
     "title": "Sensitive files at policy mode",
     "description": "Overly broad file permissions (e.g. a world-readable "
                    "credential store) leak secrets to any local account. "
                    "Tracked files must match their policy mode exactly.",
     "expected": "every tracked file matches its expected mode",
     "remediation": "Reset modes to the policy values.",
     "check": _check_file_modes, "fix": _fix_file_modes},
    {"id": "perm-02", "category": "file_permissions",
     "title": "Setuid binaries allowlisted",
     "description": "A setuid binary runs with the file owner's privilege — "
                    "a setuid-root binary is a standing privilege boundary "
                    "crossing. Every one must carry a documented "
                    "justification, or the bit comes off.",
     "expected": "no unjustified setuid binaries",
     "remediation": "Remove the setuid bit from unjustified binaries.",
     "check": _check_suid_allowlist, "fix": _fix_suid_allowlist},
]

BASELINE_INDEX: dict[str, dict[str, Any]] = {b["id"]: b for b in BASELINES}
BASELINE_CATEGORIES = ("account_policy", "authentication",
                       "service_minimization", "patch_cadence",
                       "file_permissions")


def get_baseline(item_id: str) -> dict[str, Any]:
    return BASELINE_INDEX[item_id]


def coverage_audit() -> list[str]:
    """Every baseline item must carry a verification function (check), a
    simulated remediation (fix), and the documentation fields the findings
    and pages rely on. Returns a list of gaps; empty means full coverage."""
    gaps: list[str] = []
    for b in BASELINES:
        for field in ("id", "category", "title", "description",
                      "expected", "remediation"):
            if not b.get(field):
                gaps.append(f"{b.get('id', '?')}: missing {field}")
        if b.get("category") not in BASELINE_CATEGORIES:
            gaps.append(f"{b.get('id', '?')}: unknown category "
                        f"{b.get('category')!r}")
        if not callable(b.get("check")):
            gaps.append(f"{b['id']}: no verification function")
        if not callable(b.get("fix")):
            gaps.append(f"{b['id']}: no remediation function")
    return gaps


def verify_baseline(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Evaluate every baseline item against a simulated state snapshot.

    Returns one result per item: item id, category, title, passed, evidence.
    Pure function of the state — it never modifies it.
    """
    results: list[dict[str, Any]] = []
    for b in BASELINES:
        passed, evidence = b["check"](state)
        results.append({
            "item_id": b["id"],
            "category": b["category"],
            "title": b["title"],
            "expected": b["expected"],
            "passed": bool(passed),
            "evidence": evidence,
        })
    return results


def baseline_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = [r for r in results if r["passed"]]
    failed = [r for r in results if not r["passed"]]
    by_category: dict[str, dict[str, int]] = {}
    for r in results:
        cat = by_category.setdefault(r["category"], {"passed": 0, "failed": 0})
        cat["passed" if r["passed"] else "failed"] += 1
    return {
        "total": len(results),
        "passed": len(passed),
        "failed": len(failed),
        "pass_rate": (len(passed) / len(results)) if results else 0.0,
        "by_category": by_category,
    }


# ---------------------------------------------------------------------------
# Vulnerability-class records: description -> detection -> remediation ->
# verification. Detection and remediation operate on the simulated state;
# verification re-runs the mapped baseline items.
# ---------------------------------------------------------------------------

def _detect(state: dict[str, Any], item_ids: list[str]) -> tuple[bool, str]:
    """A finding is detected when any of its mapped baseline items fails."""
    failing = [r for r in verify_baseline(state)
               if r["item_id"] in item_ids and not r["passed"]]
    if failing:
        evidence = "; ".join(
            f"{r['item_id']}: {r['evidence']}" for r in failing)
        return True, evidence
    passing = [r for r in verify_baseline(state)
               if r["item_id"] in item_ids]
    return False, ("no weakness found: " +
                   "; ".join(f"{r['item_id']} passes" for r in passing))


def _remediate(state: dict[str, Any], item_ids: list[str]) -> list[str]:
    """Apply the mapped baseline fixes to a state copy. Returns evidence."""
    evidence: list[str] = []
    for item_id in item_ids:
        evidence.extend(get_baseline(item_id)["fix"](state))
    return evidence


FINDINGS: list[dict[str, Any]] = [
    {
        "id": "weak-credentials",
        "name": "Weak credentials",
        "vuln_class": "Weak authentication",
        "description": "Active accounts whose passwords fail the lab policy "
                       "are the cheapest initial access an attacker gets: "
                       "guessing replaces skill. The vulnerable fixture marks "
                       "a trainee account 'weak'; the marker is a policy "
                       "judgment on synthetic data, never a real credential.",
        "detection_method": "Enumerate active accounts in the simulated "
                            "state; flag any with a weak password marker.",
        "remediation": "Replace weak passwords with generated passphrases "
                       "meeting the policy; confirm no active account keeps "
                       "a weak marker.",
        "verification_method": "Re-run baseline items acct-02 and acct-03; "
                               "both must pass.",
        "baseline_item_ids": ["acct-02", "acct-03"],
    },
    {
        "id": "excessive-privilege",
        "name": "Excessive privilege",
        "vuln_class": "Privilege escalation (configuration)",
        "description": "Privilege the role does not need — a second uid-0 "
                       "account, or sudo granted to an ordinary trainee — "
                       "collapses the user/kernel separation the OS is built "
                       "on. One compromised low-privilege account becomes "
                       "total control.",
        "detection_method": "List uid-0 accounts (expect root only) and "
                            "sudo grants (expect root only per lab policy).",
        "remediation": "Remove uid 0 from duplicate accounts (lock them) and "
                       "revoke unneeded sudo grants.",
        "verification_method": "Re-run baseline items acct-01 and acct-04; "
                               "both must pass.",
        "baseline_item_ids": ["acct-01", "acct-04"],
    },
    {
        "id": "ssh-misconfiguration",
        "name": "SSH service misconfiguration",
        "vuln_class": "Misconfiguration",
        "description": "Password authentication, direct root login, and a "
                       "loose attempt limit on SSH hand attackers the keys "
                       "to the management plane: guessable, unaudited, "
                       "unthrottled remote access.",
        "detection_method": "Read the sshd settings in the simulated state "
                            "against the lab SSH policy.",
        "remediation": "Disable password authentication and direct root "
                       "login; cap authentication attempts at "
                       f"{POLICY_SSH_MAX_AUTH_TRIES}.",
        "verification_method": "Re-run baseline items auth-01, auth-02, "
                               "auth-03; all must pass.",
        "baseline_item_ids": ["auth-01", "auth-02", "auth-03"],
    },
    {
        "id": "unnecessary-services",
        "name": "Unnecessary services exposed",
        "vuln_class": "Misconfiguration",
        "description": "Legacy and convenience daemons left running — and "
                       "enabled at boot — are reachable code the system does "
                       "not need. The fixture runs an unneeded legacy remote "
                       "service plus a print daemon on a lab VM that prints "
                       "nothing.",
        "detection_method": "List running and boot-enabled services; flag "
                            "any not marked needed for the lab role.",
        "remediation": "Stop unneeded services and disable them at boot.",
        "verification_method": "Re-run baseline items svc-01 and svc-02; "
                               "both must pass.",
        "baseline_item_ids": ["svc-01", "svc-02"],
    },
    {
        "id": "unpatched-software",
        "name": "Unpatched software",
        "vuln_class": "Missing security updates",
        "description": "A system 120 days past its patch window, with 34 "
                       "pending security updates, a behind-version service, "
                       "and an old running kernel, is exposed to every "
                       "publicly known issue fixed since — the most "
                       "defensible-against vulnerability class there is.",
        "detection_method": "Compare days-since-patch, pending update count, "
                            "service versions, and running kernel against "
                            "policy in the simulated state.",
        "remediation": "Install all pending security updates and reboot "
                       "into the latest kernel.",
        "verification_method": "Re-run baseline items svc-03, pat-01, "
                               "pat-02, pat-03; all must pass.",
        "baseline_item_ids": ["svc-03", "pat-01", "pat-02", "pat-03"],
    },
    {
        "id": "suid-privilege-escalation",
        "name": "Unjustified setuid binaries",
        "vuln_class": "Privilege escalation (binary)",
        "description": "A setuid-root binary executes with root's privilege "
                       "regardless of who runs it — a standing crossing of "
                       "the user/kernel privilege boundary. The fixture "
                       "plants an unjustified setuid helper; every setuid "
                       "binary must carry a documented justification.",
        "detection_method": "Enumerate files with the setuid bit set; flag "
                            "any without a documented justification.",
        "remediation": "Remove the setuid bit from unjustified binaries.",
        "verification_method": "Re-run baseline items perm-01 and perm-02; "
                               "both must pass. (perm-01 covers the "
                               "world-readable credential store the same "
                               "fixture plants.)",
        "baseline_item_ids": ["perm-01", "perm-02"],
    },
]

FINDING_INDEX: dict[str, dict[str, Any]] = {f["id"]: f for f in FINDINGS}


def get_finding(finding_id: str) -> dict[str, Any]:
    return FINDING_INDEX[finding_id]


def detect_finding(state: dict[str, Any],
                   finding_id: str) -> dict[str, Any]:
    """Defensive detection: is this vulnerability class present in the
    simulated state? Returns detected + evidence. No exploitation is
    attempted — presence is read from configuration, not proven by use."""
    finding = get_finding(finding_id)
    detected, evidence = _detect(state, finding["baseline_item_ids"])
    return {
        "finding_id": finding_id,
        "name": finding["name"],
        "vuln_class": finding["vuln_class"],
        "detected": detected,
        "detection_method": finding["detection_method"],
        "evidence": evidence,
    }


def remediate_finding(state: dict[str, Any],
                      finding_id: str) -> dict[str, Any]:
    """Simulated remediation: return a NEW state with the finding's fixes
    applied, plus per-step evidence. The input state is not modified."""
    finding = get_finding(finding_id)
    new_state = copy.deepcopy(state)
    evidence = _remediate(new_state, finding["baseline_item_ids"])
    verification = verify_baseline(new_state)
    mapped = [r for r in verification
              if r["item_id"] in finding["baseline_item_ids"]]
    return {
        "finding_id": finding_id,
        "name": finding["name"],
        "state_before_label": state.get("label"),
        "state": new_state,
        "remediation": finding["remediation"],
        "remediation_evidence": evidence,
        "verification_method": finding["verification_method"],
        "verification": mapped,
        "verified": all(r["passed"] for r in mapped),
    }


def before_after_report(state: dict[str, Any],
                        finding_ids: Optional[list[str]] = None
                        ) -> dict[str, Any]:
    """Proof-of-fix record: verify before, apply remediations, verify after.

    Applies each requested finding's remediation to a deep copy of the state
    (in the given order), recording per-finding detection evidence, applied
    remediation steps, and the before/after pass-fail of every mapped
    baseline item.
    """
    ids = finding_ids or [f["id"] for f in FINDINGS]
    for fid in ids:
        if fid not in FINDING_INDEX:
            raise KeyError(f"unknown finding {fid!r}")
    before = {r["item_id"]: r for r in verify_baseline(state)}
    working = copy.deepcopy(state)
    findings_report: list[dict[str, Any]] = []
    for fid in ids:
        finding = get_finding(fid)
        detection = detect_finding(working, fid)
        step_evidence = _remediate(working, finding["baseline_item_ids"])
        findings_report.append({
            "finding_id": fid,
            "name": finding["name"],
            "vuln_class": finding["vuln_class"],
            "detected_before_fix": detection["detected"],
            "detection_evidence": detection["evidence"],
            "remediation": finding["remediation"],
            "remediation_evidence": step_evidence,
        })
    after = {r["item_id"]: r for r in verify_baseline(working)}
    item_rows: list[dict[str, Any]] = []
    for b in BASELINES:
        item_rows.append({
            "item_id": b["id"],
            "title": b["title"],
            "category": b["category"],
            "passed_before": before[b["id"]]["passed"],
            "evidence_before": before[b["id"]]["evidence"],
            "passed_after": after[b["id"]]["passed"],
            "evidence_after": after[b["id"]]["evidence"],
            "fixed": (not before[b["id"]]["passed"]
                      and after[b["id"]]["passed"]),
        })
    return {
        "state_label": state.get("label"),
        "finding_ids": ids,
        "findings": findings_report,
        "items": item_rows,
        "summary_before": baseline_summary(list(before.values())),
        "summary_after": baseline_summary(list(after.values())),
        "hardened_state": working,
    }


# ---------------------------------------------------------------------------
# Simulated lab VM states (synthetic fixtures)
# ---------------------------------------------------------------------------

def vulnerable_state(label: str = "lab-vm-vulnerable") -> dict[str, Any]:
    """The intentionally misconfigured training fixture: every baseline
    item fails, every finding detects. All data invented."""
    return {
        "label": label,
        "os": {"name": "lab-linux", "kernel": "5.4.0-generic",
               "latest_kernel": "5.15.0-generic"},
        "patch": {"last_patch_days_ago": 120, "pending_security_updates": 34},
        "accounts": [
            {"name": "root", "uid": 0, "password_set": True,
             "password_strength": "strong", "locked": False, "sudo": True,
             "last_login_days_ago": 1},
            {"name": "trainee", "uid": 1000, "password_set": True,
             "password_strength": "weak", "locked": False, "sudo": True,
             "last_login_days_ago": 2},
            {"name": "legacy", "uid": 0, "password_set": True,
             "password_strength": "weak", "locked": False, "sudo": False,
             "last_login_days_ago": 400},
        ],
        "ssh": {"enabled": True, "password_auth": True,
                "permit_root_login": True, "max_auth_tries": 6},
        "services": [
            {"name": "sshd", "running": True, "enabled": True,
             "version": "8.2p1", "latest_version": "9.3p1", "needed": True},
            {"name": "legacy-remote", "running": True, "enabled": True,
             "version": "0.9.8", "latest_version": "0.9.8", "needed": False},
            {"name": "printd", "running": True, "enabled": True,
             "version": "2.4.1", "latest_version": "2.4.1", "needed": False},
        ],
        "files": [
            {"path": "/etc/shadow", "mode": "0o644", "owner": "root",
             "suid": False, "justified": False, "expected_mode": "0o640"},
            {"path": "/opt/lab/suid-helper", "mode": "0o4755", "owner": "root",
             "suid": True, "justified": False, "expected_mode": "0o4755"},
        ],
    }


def hardened_state(label: str = "lab-vm-hardened") -> dict[str, Any]:
    """The same fixture after every remediation is applied — what the
    simulator produces from vulnerable_state(). Every baseline item passes."""
    report = before_after_report(vulnerable_state("lab-vm-vulnerable"))
    state = report["hardened_state"]
    state["label"] = label
    return state


# ---------------------------------------------------------------------------
# SQLite persistence: findings + baseline runs (migration 014)
# ---------------------------------------------------------------------------
FINDING_STATUSES = ("open", "remediated", "verified", "closed")
FINDING_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "open": ("remediated",),
    "remediated": ("verified", "open"),
    "verified": ("closed", "open"),
    "closed": ("open",),
}


class OssecError(ValueError):
    pass


def record_finding(conn: sqlite3.Connection, finding_id: str,
                   detection_evidence: str, status: str = "open",
                   actor: str = "lab-operator") -> int:
    finding = get_finding(finding_id)  # KeyError on unknown id
    if status not in FINDING_STATUSES:
        raise OssecError(f"unknown finding status {status!r}")
    created = utcnow_iso()
    cur = conn.execute(
        """INSERT INTO ossec_findings
           (finding_id, name, vuln_class, status, detection_evidence,
            remediation_evidence, verification_evidence, actor,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)""",
        (finding_id, finding["name"], finding["vuln_class"], status,
         detection_evidence, actor, created, created),
    )
    conn.commit()
    return cur.lastrowid


def transition_finding(conn: sqlite3.Connection, row_id: int, to_status: str,
                       evidence: str = "",
                       actor: str = "lab-operator") -> None:
    if to_status not in FINDING_STATUSES:
        raise OssecError(f"unknown finding status {to_status!r}")
    row = conn.execute(
        "SELECT status FROM ossec_findings WHERE id = ?", (row_id,)
    ).fetchone()
    if row is None:
        raise OssecError(f"finding row {row_id} not found")
    from_status = row["status"]
    if to_status not in FINDING_TRANSITIONS[from_status]:
        raise OssecError(
            f"illegal transition {from_status!r} -> {to_status!r}; allowed: "
            f"{list(FINDING_TRANSITIONS[from_status])}")
    column = {"remediated": "remediation_evidence",
              "verified": "verification_evidence"}.get(to_status)
    now = utcnow_iso()
    if column:
        conn.execute(
            f"UPDATE ossec_findings SET status = ?, {column} = ?, "
            f"actor = ?, updated_at = ? WHERE id = ?",
            (to_status, evidence or None, actor, now, row_id))
    else:
        conn.execute(
            "UPDATE ossec_findings SET status = ?, actor = ?, updated_at = ? "
            "WHERE id = ?",
            (to_status, actor, now, row_id))
    conn.commit()


def list_findings(conn: sqlite3.Connection,
                  status: Optional[str] = None) -> list[dict[str, Any]]:
    if status is None:
        rows = conn.execute(
            "SELECT * FROM ossec_findings ORDER BY id").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM ossec_findings WHERE status = ? ORDER BY id",
            (status,)).fetchall()
    return [dict(r) for r in rows]


def save_baseline_run(conn: sqlite3.Connection, state_label: str,
                      results: list[dict[str, Any]],
                      actor: str = "lab-operator") -> int:
    summary = baseline_summary(results)
    created = utcnow_iso()
    cur = conn.execute(
        """INSERT INTO ossec_baseline_runs
           (state_label, total_items, passed, failed, actor, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (state_label, summary["total"], summary["passed"], summary["failed"],
         actor, created),
    )
    run_id = cur.lastrowid
    for r in results:
        conn.execute(
            """INSERT INTO ossec_baseline_results
               (run_id, item_id, category, passed, evidence)
               VALUES (?, ?, ?, ?, ?)""",
            (run_id, r["item_id"], r["category"], int(r["passed"]),
             r["evidence"]),
        )
    conn.commit()
    return run_id


def list_baseline_runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM ossec_baseline_runs ORDER BY id DESC").fetchall()]


def get_baseline_run(conn: sqlite3.Connection,
                     run_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM ossec_baseline_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if row is None:
        raise OssecError(f"baseline run {run_id} not found")
    run = dict(row)
    run["results"] = [dict(r) for r in conn.execute(
        "SELECT * FROM ossec_baseline_results WHERE run_id = ? ORDER BY id",
        (run_id,)).fetchall()]
    return run


def seed_demo(conn: sqlite3.Connection, seed: int = 7) -> dict[str, int]:
    """Seed synthetic demo data: one finding row per vulnerability class
    (detection evidence from the vulnerable fixture) and baseline runs for
    the vulnerable and hardened fixtures. Idempotent on finding_id rows."""
    _ = seed  # fixtures are deterministic; seed kept for API symmetry
    vuln = vulnerable_state()
    finding_rows = 0
    for f in FINDINGS:
        exists = conn.execute(
            "SELECT 1 FROM ossec_findings WHERE finding_id = ?",
            (f["id"],)).fetchone()
        if not exists:
            detection = detect_finding(vuln, f["id"])
            record_finding(conn, f["id"], detection["evidence"], actor="seed")
            finding_rows += 1
    runs = 0
    for state in (vuln, hardened_state()):
        exists = conn.execute(
            "SELECT 1 FROM ossec_baseline_runs WHERE state_label = ?",
            (state["label"],)).fetchone()
        if not exists:
            save_baseline_run(conn, state["label"], verify_baseline(state),
                              actor="seed")
            runs += 1
    return {"findings": finding_rows, "baseline_runs": runs}
