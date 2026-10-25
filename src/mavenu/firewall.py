"""S01 — Network Security: firewall ruleset as code + deterministic packet simulator.

This is the EXECUTABLE version of the defensive lab test plan. The ruleset
below is the lab's firewall policy expressed as ordered, commented data;
``evaluate()`` decides what the lab firewall would do with a packet,
exactly as the ordered ruleset prescribes (first match wins, default-deny).

Lawful-lab scope only: every IP address is invented (RFC 1918 lab space).
Nothing here sends a packet, scans, or probes anything. Do not apply these
rules to, or test them against, any network you do not own.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Lab addressing plan (synthetic — a documented design, not a live network)
# ---------------------------------------------------------------------------
SUBNETS = {
    "OFFICE": "10.10.10.0/24",   # staff workstations / office devices (VLAN 10)
    "GUEST": "10.10.20.0/24",    # guest Wi-Fi, internet-only (VLAN 20)
    "IOT": "10.10.30.0/24",      # printers, cameras, sensors (VLAN 30)
    "MGMT": "10.10.99.0/24",     # firewall/switch admin interfaces (VLAN 99)
}
ADMIN_WORKSTATION = "10.10.10.50"  # the one office host allowed into MGMT
GATEWAYS = {
    "OFFICE": "10.10.10.1",
    "GUEST": "10.10.20.1",
    "IOT": "10.10.30.1",
    "MGMT": "10.10.99.1",
}
# "WAN" = any public (non-RFC-1918) address: the internet side of the lab.
PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
]
RULESET_VERSION = "1.0.0"


def zone_of(ip: str) -> str:
    """Resolve an IP to its lab zone (WAN for anything public)."""
    addr = ipaddress.ip_address(ip)
    for zone, cidr in SUBNETS.items():
        if addr in ipaddress.ip_network(cidr):
            return zone
    return "WAN"


def is_private(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return any(addr in net for net in PRIVATE_NETS)


# ---------------------------------------------------------------------------
# Ruleset (ordered; first match wins; default-deny)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FirewallRule:
    rule_id: str
    order: int
    action: str                      # "allow" | "deny"
    src: str                         # zone name, "IP:<addr>", "private", or "any"
    dst: str                         # same grammar
    proto: str                       # "tcp" | "udp" | "icmp" | "any"
    ports: Optional[tuple[int, ...]] = None  # None = any port
    established: Optional[bool] = None       # True: established only; None: either
    description: str = ""
    exception_reason: Optional[str] = None   # mandatory for allow rules
    log: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "order": self.order,
            "action": self.action,
            "src": self.src,
            "dst": self.dst,
            "proto": self.proto,
            "ports": list(self.ports) if self.ports else None,
            "established": self.established,
            "description": self.description,
            "exception_reason": self.exception_reason,
            "log": self.log,
        }


RULESET: tuple[FirewallRule, ...] = (
    FirewallRule(
        rule_id="allow-established", order=1, action="allow",
        src="any", dst="any", proto="any", established=True,
        description="Return traffic for sessions initiated from inside the lab.",
        exception_reason="Stateful return traffic: required for any outbound "
                         "connection to receive replies. Cannot be abused to "
                         "initiate new sessions (established flag only).",
    ),
    FirewallRule(
        rule_id="allow-guest-gw-dns", order=2, action="allow",
        src="GUEST", dst="IP:10.10.20.1", proto="udp", ports=(53,),
        description="Guests resolve names through the lab gateway only.",
        exception_reason="Guest devices need DNS to use the internet; pinned to "
                         "the gateway resolver so guest DNS cannot reach other "
                         "internal hosts.",
    ),
    FirewallRule(
        rule_id="allow-iot-gw-dns", order=3, action="allow",
        src="IOT", dst="IP:10.10.30.1", proto="udp", ports=(53,),
        description="IoT devices resolve names through the lab gateway only.",
        exception_reason="IoT firmware update checks need name resolution; "
                         "pinned to the gateway resolver, UDP/53 only.",
    ),
    FirewallRule(
        rule_id="deny-guest-internal", order=4, action="deny",
        src="GUEST", dst="private", proto="any", log=True,
        description="Guest network may not reach any internal address "
                    "(office, IoT, management).",
    ),
    FirewallRule(
        rule_id="deny-iot-internal", order=5, action="deny",
        src="IOT", dst="private", proto="any", log=True,
        description="IoT devices may not initiate connections into internal "
                    "networks (compromised-device containment).",
    ),
    FirewallRule(
        rule_id="allow-office-web", order=6, action="allow",
        src="OFFICE", dst="WAN", proto="tcp", ports=(80, 443),
        description="Staff web access outbound.",
        exception_reason="Business web use; TLS/HTTP only, no other outbound "
                         "TCP from office workstations.",
    ),
    FirewallRule(
        rule_id="allow-office-dns", order=7, action="allow",
        src="OFFICE", dst="WAN", proto="any", ports=(53,),
        description="Staff name resolution to upstream resolvers.",
        exception_reason="DNS is required for all outbound connectivity; "
                         "port 53 only.",
    ),
    FirewallRule(
        rule_id="allow-guest-web", order=8, action="allow",
        src="GUEST", dst="WAN", proto="tcp", ports=(80, 443),
        description="Guest internet access (after the internal-deny above).",
        exception_reason="Guests are internet-only by design; HTTPS/HTTP are "
                         "the expected guest protocols.",
    ),
    FirewallRule(
        rule_id="allow-admin-mgmt", order=9, action="allow",
        src="IP:10.10.10.50", dst="MGMT", proto="tcp", ports=(22, 443),
        description="Admin workstation may reach management interfaces.",
        exception_reason="Single pinned admin host for firewall/switch "
                         "administration; SSH + HTTPS only. All other office "
                         "hosts are denied by the next rule.",
    ),
    FirewallRule(
        rule_id="deny-office-mgmt", order=10, action="deny",
        src="OFFICE", dst="MGMT", proto="any", log=True,
        description="No other office host may reach the management VLAN.",
    ),
    FirewallRule(
        rule_id="allow-iot-updates", order=11, action="allow",
        src="IOT", dst="WAN", proto="tcp", ports=(443,),
        description="IoT firmware/cloud updates over TLS only.",
        exception_reason="IoT devices need vendor cloud endpoints for "
                         "firmware updates; TLS-only keeps the window narrow. "
                         "HTTP (80) deliberately excluded.",
    ),
    FirewallRule(
        rule_id="deny-wan-inbound", order=12, action="deny",
        src="WAN", dst="private", proto="any", log=True,
        description="No inbound services are exposed; unsolicited WAN traffic "
                    "is denied and logged (background internet noise).",
    ),
    FirewallRule(
        rule_id="deny-inter-vlan", order=13, action="deny",
        src="private", dst="private", proto="any", log=True,
        description="Catch-all: no other inter-VLAN traffic is permitted. "
                    "Anything not explicitly allowed above dies here.",
    ),
)
# Implicit final rule: deny everything else (default-deny).
DEFAULT_DENY = True


# ---------------------------------------------------------------------------
# Packet simulator (the "lab test plan" executed against the ruleset)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Packet:
    """A SYNTHETIC packet: invented addresses, never transmitted."""
    src_ip: str
    dst_ip: str
    proto: str            # "tcp" | "udp" | "icmp"
    dst_port: Optional[int] = None
    established: bool = False
    label: str = ""       # test-plan label, e.g. "office -> WAN https"


@dataclass
class EvalResult:
    action: str           # "allow" | "deny"
    rule_id: Optional[str]
    rule_order: Optional[int]
    trace: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "rule_id": self.rule_id,
            "rule_order": self.rule_order,
            "trace": self.trace,
        }


def _match_endpoint(spec: str, ip: str) -> bool:
    if spec == "any":
        return True
    if spec == "private":
        return is_private(ip)
    if spec.startswith("IP:"):
        return ip == spec[3:]
    # otherwise a zone name
    return zone_of(ip) == spec


def _rule_matches(rule: FirewallRule, pkt: Packet) -> bool:
    if not _match_endpoint(rule.src, pkt.src_ip):
        return False
    if not _match_endpoint(rule.dst, pkt.dst_ip):
        return False
    if rule.proto != "any" and rule.proto != pkt.proto:
        return False
    if rule.ports is not None:
        if pkt.dst_port is None or pkt.dst_port not in rule.ports:
            return False
    if rule.established is True and not pkt.established:
        return False
    if rule.established is False and pkt.established:
        return False
    return True


def evaluate(pkt: Packet,
             rules: tuple[FirewallRule, ...] = RULESET) -> EvalResult:
    """First-match-wins evaluation with default-deny.

    Returns the verdict AND the full trace (every rule's match/no-match) so
    the allow/deny matrix is auditable rule by rule.
    """
    trace: list[str] = []
    for rule in sorted(rules, key=lambda r: r.order):
        hit = _rule_matches(rule, pkt)
        trace.append(f"rule {rule.order} ({rule.rule_id}): "
                     f"{'MATCH' if hit else 'no match'}")
        if hit:
            return EvalResult(action=rule.action, rule_id=rule.rule_id,
                              rule_order=rule.order, trace=trace)
    trace.append("implicit final rule: default-deny")
    return EvalResult(action="deny", rule_id=None, rule_order=None, trace=trace)


# ---------------------------------------------------------------------------
# Config linters (the "config review checklist" as code)
# ---------------------------------------------------------------------------
def lint_default_deny(rules: tuple[FirewallRule, ...] = RULESET) -> list[str]:
    """The checklist item: the ruleset must end in an explicit deny posture."""
    errors: list[str] = []
    if not DEFAULT_DENY:
        errors.append("default-deny is not enabled: unmatched traffic would "
                      "be allowed")
    ordered = sorted(rules, key=lambda r: r.order)
    if ordered and ordered[-1].action != "deny":
        errors.append("last explicit rule is not a deny: the ruleset does not "
                      "end in an explicit deny posture")
    return errors


def lint_allow_reasons(rules: tuple[FirewallRule, ...] = RULESET) -> list[str]:
    """Every allow rule must carry a documented exception reason."""
    return [
        f"allow rule {r.rule_id} has no documented exception reason"
        for r in rules if r.action == "allow" and not r.exception_reason
    ]


def _subsumes(earlier: FirewallRule, later: FirewallRule) -> bool:
    """True if `earlier` matches every packet `later` would match.

    Conservative componentwise check: an endpoint spec subsumes another if
    it is "any", identical, or (zone/private) a superset relationship we can
    prove from the addressing plan:
      - "any" subsumes everything
      - "private" subsumes any lab zone name and "IP:<rfc1918>"
    """

    def endpoint_subsumes(a: str, b: str) -> bool:
        if a == "any":
            return True
        if a == b:
            return True
        if a == "private":
            if b in SUBNETS or b == "private":
                return True
            if b.startswith("IP:"):
                return is_private(b[3:])
        return False

    if not endpoint_subsumes(earlier.src, later.src):
        return False
    if not endpoint_subsumes(earlier.dst, later.dst):
        return False
    if earlier.proto != "any" and earlier.proto != later.proto:
        return False
    if earlier.ports is not None:
        if later.ports is None:
            return False
        if not set(later.ports) <= set(earlier.ports):
            return False
    if earlier.established is True and later.established is not True:
        return False
    if earlier.established is False and later.established is not False:
        return False
    return True


def find_shadowed(rules: tuple[FirewallRule, ...] = RULESET
                  ) -> list[tuple[FirewallRule, FirewallRule, str]]:
    """Find unreachable rules: (later_rule, earlier_rule, kind).

    kind = "shadowed" (earlier matches superset with a DIFFERENT action, so
    the later rule can never fire) or "redundant" (same action, later rule
    adds nothing).
    """
    ordered = sorted(rules, key=lambda r: r.order)
    findings: list[tuple[FirewallRule, FirewallRule, str]] = []
    for i, later in enumerate(ordered):
        for earlier in ordered[:i]:
            if _subsumes(earlier, later):
                kind = ("redundant" if earlier.action == later.action
                        else "shadowed")
                findings.append((later, earlier, kind))
                break  # first subsuming earlier rule explains the unreachability
    return findings


def lint(rules: tuple[FirewallRule, ...] = RULESET) -> list[str]:
    """Full config review checklist as one call; empty list = clean."""
    errors = lint_default_deny(rules) + lint_allow_reasons(rules)
    for later, earlier, kind in find_shadowed(rules):
        errors.append(f"rule {later.rule_id} is {kind} by earlier rule "
                      f"{earlier.rule_id} (unreachable)")
    # hygiene: orders unique and strictly increasing
    orders = [r.order for r in rules]
    if len(set(orders)) != len(orders):
        errors.append("duplicate rule order values: evaluation order is "
                      "ambiguous")
    if orders != sorted(orders):
        errors.append("rules are not listed in ascending order")
    return errors


def allow_deny_matrix(packets: list[Packet],
                      rules: tuple[FirewallRule, ...] = RULESET
                      ) -> list[dict[str, Any]]:
    """Evaluate each packet; returns one row per packet with its verdict.

    The lab test plan: for every rule there must be >= 1 packet whose
    verdict names that rule (full coverage of deny rules, zero allow rules
    untested).
    """
    rows = []
    for pkt in packets:
        res = evaluate(pkt, rules)
        rows.append({
            "label": pkt.label or f"{pkt.src_ip}->{pkt.dst_ip} "
                                  f"{pkt.proto}/{pkt.dst_port}",
            "src": pkt.src_ip, "dst": pkt.dst_ip, "proto": pkt.proto,
            "dst_port": pkt.dst_port, "established": pkt.established,
            "verdict": res.action, "rule_id": res.rule_id,
            "rule_order": res.rule_order,
        })
    return rows


# The canonical lab test plan: one representative packet per ruleset rule,
# plus a default-deny probe. Every deny rule is verified; zero allow rules
# are left untested. Web UI and tests both consume this list so the matrix
# shown is exactly the matrix asserted.
LAB_TEST_PACKETS: tuple[Packet, ...] = (
    Packet("10.10.10.20", "93.184.216.34", "tcp", 443, established=True,
           label="T01 office reply traffic (established)"),
    Packet("10.10.20.5", "10.10.20.1", "udp", 53,
           label="T02 guest -> gateway DNS"),
    Packet("10.10.30.5", "10.10.30.1", "udp", 53,
           label="T03 iot -> gateway DNS"),
    Packet("10.10.20.5", "10.10.10.10", "tcp", 445,
           label="T04 guest -> office SMB (must deny)"),
    Packet("10.10.30.8", "10.10.10.1", "tcp", 22,
           label="T05 iot -> office SSH (must deny)"),
    Packet("10.10.10.20", "93.184.216.34", "tcp", 443,
           label="T06 office -> WAN https"),
    Packet("10.10.10.20", "8.8.8.8", "udp", 53,
           label="T07 office -> WAN DNS"),
    Packet("10.10.20.5", "93.184.216.34", "tcp", 443,
           label="T08 guest -> WAN https"),
    Packet("10.10.10.50", "10.10.99.1", "tcp", 22,
           label="T09 admin workstation -> mgmt SSH"),
    Packet("10.10.10.20", "10.10.99.1", "tcp", 22,
           label="T10 office host -> mgmt SSH (must deny)"),
    Packet("10.10.30.8", "93.184.216.34", "tcp", 443,
           label="T11 iot -> WAN https (firmware update)"),
    Packet("203.0.113.9", "10.10.10.20", "tcp", 3389,
           label="T12 WAN -> office RDP probe (must deny)"),
    Packet("10.10.10.20", "10.10.20.5", "tcp", 80,
           label="T13 office -> guest http (must deny)"),
    Packet("10.10.10.20", "93.184.216.34", "icmp",
           label="T14 office -> WAN ping (default-deny probe)"),
)

EXPECTED_VERDICTS: dict[str, tuple[str, Optional[str]]] = {
    # label-prefix -> (action, rule_id)
    "T01": ("allow", "allow-established"),
    "T02": ("allow", "allow-guest-gw-dns"),
    "T03": ("allow", "allow-iot-gw-dns"),
    "T04": ("deny", "deny-guest-internal"),
    "T05": ("deny", "deny-iot-internal"),
    "T06": ("allow", "allow-office-web"),
    "T07": ("allow", "allow-office-dns"),
    "T08": ("allow", "allow-guest-web"),
    "T09": ("allow", "allow-admin-mgmt"),
    "T10": ("deny", "deny-office-mgmt"),
    "T11": ("allow", "allow-iot-updates"),
    "T12": ("deny", "deny-wan-inbound"),
    "T13": ("deny", "deny-inter-vlan"),
    "T14": ("deny", None),  # implicit default-deny
}


def matrix_coverage(matrix: list[dict[str, Any]],
                    rules: tuple[FirewallRule, ...] = RULESET
                    ) -> dict[str, Any]:
    """Which rules were exercised by the matrix, and which were not."""
    hit = {row["rule_id"] for row in matrix if row["rule_id"]}
    return {
        "rules_total": len(rules),
        "rules_hit": len(hit),
        "unhit_allow": sorted(r.rule_id for r in rules
                              if r.action == "allow" and r.rule_id not in hit),
        "unhit_deny": sorted(r.rule_id for r in rules
                             if r.action == "deny" and r.rule_id not in hit),
    }
