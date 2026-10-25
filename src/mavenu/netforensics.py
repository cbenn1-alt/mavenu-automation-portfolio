"""N01 — Network Forensics: Packet Capture to Evidentiary Report.

=====================================================================
LAWFUL LAB ONLY. ALL TRAFFIC IS SYNTHETIC.
=====================================================================

This module builds an evidentiary network-forensics workflow over
*synthetic* packet captures that the module itself generates:

    capture plan  ->  synthetic capture  ->  session reconstruction  ->
    protocol notes  ->  timeline  ->  anomaly detection (documented
    baseline)  ->  scoping  ->  evidentiary report (facts vs inference)

The "capture" is NEVER a real network tap. There is no socket, pcap,
or raw-packet code anywhere in this module — packets are plain Python
dicts produced by a seeded generator, so results are deterministic and
reproducible. Do not point this module at a real network: capturing a
real network without explicit written authorization from its owner is
unlawful in most jurisdictions.

Discipline controls (the actual product of this project):

* **Ground truth:** every scripted scenario ships its expected outcome;
  tests assert the pipeline reproduces it.
* **Citation:** every anomaly and every report claim cites a packet
  index range ``[lo, hi]``; the report builder structurally rejects
  claims without a valid citation.
* **Facts vs inference:** facts are directly observed (packet counts,
  bytes, flags). Inferences are interpretations and MUST carry a
  confidence level (``low`` / ``medium`` / ``high``); an inference
  without one is rejected, exactly as in S03.
* **Documented baseline:** anomaly thresholds are named constants in
  :data:`BASELINE`, printed in the report, not magic numbers.

Status vocabulary: Implemented, Tested, Simulated, Demo.
The generator/reconstruction/timeline/anomaly-detection/scoping/
reporting pipeline is Implemented+Tested; the "captured network"
itself is Simulated (synthetic packets, not a real tap).
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import sqlite3
import statistics
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .db import utcnow_iso
from .validation import ValidationError

# ---------------------------------------------------------------------------
# Ethical banner + global constraints
# ---------------------------------------------------------------------------

ETHICAL_BANNER = (
    "LAWFUL LAB ONLY: this module generates SYNTHETIC packets for a "
    "scripted lab scenario. It contains no socket/pcap code and cannot "
    "capture a real network. Never capture a real network without explicit "
    "written authorization from its owner."
)

CONFIDENCE_LEVELS = ("low", "medium", "high")

# ---------------------------------------------------------------------------
# Scripted scenarios
# ---------------------------------------------------------------------------

SCENARIOS = (
    "baseline_clean",      # routine lab chatter only; ground truth: 0 anomalies
    "port_scan",           # attacker probes 24 ports; defense denies each
    "c2_beaconing",        # compromised host beacons every 60 s
    "data_exfiltration",   # large outbound transfer on an unusual port
)

# Synthetic lab addressing (documentation/test ranges only; no real hosts).
LAB_NET = "192.0.2.0/24"
LAB_WS01 = "192.0.2.11"    # lab workstation (the "compromised" host in scenarios)
LAB_SRV01 = "192.0.2.21"   # lab server (services LAB-HTTP / LAB-DNS)
EXT_ATK = "203.0.113.9"    # synthetic attacker VM
EXT_C2 = "203.0.113.77"    # synthetic external beacon destination
EXT_WEB = "203.0.113.50"   # synthetic external web service

PROTO_TCP = "LAB-TCP"

# TCP-ish flags used by the synthetic transport.
FLAG_SYN = "SYN"
FLAG_SYN_ACK = "SYN-ACK"
FLAG_ACK = "ACK"
FLAG_FIN = "FIN"
FLAG_RST = "RST"
FLAG_DATA = "DATA"
FLAG_DENIED = "DENIED"     # defense denied the probe (no service / rule drop)

# ---------------------------------------------------------------------------
# Synthetic application protocols (decoder stubs with documented grammars)
# ---------------------------------------------------------------------------
#
# Three toy protocols keep the decoders honest: each decoder parses a
# documented label grammar and returns structured notes, or None when the
# packet is not that protocol. Payloads are synthetic LABELS, not content.

LAB_HTTP_RE = re.compile(r"^LAB-HTTP (?P<method>GET|POST) (?P<path>/synth/\d+)$")
LAB_DNS_RE = re.compile(r"^LAB-DNS (?P<qtype>Q|R) (?P<name>[a-z0-9.-]+\.synth\.local)$")
LAB_BEACON_RE = re.compile(r"^LAB-BEACON id=(?P<bid>\d+) status=(?P<status>ok|err)$")


def decode_lab_http(pkt: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Parse a LAB-HTTP label: ``LAB-HTTP <GET|POST> /synth/<n>``."""
    m = LAB_HTTP_RE.match(str(pkt.get("payload_label", "")))
    if not m:
        return None
    return {"protocol": "LAB-HTTP", "method": m.group("method"),
            "path": m.group("path")}


def decode_lab_dns(pkt: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Parse a LAB-DNS label: ``LAB-DNS <Q|R> <name>.synth.local``."""
    m = LAB_DNS_RE.match(str(pkt.get("payload_label", "")))
    if not m:
        return None
    return {"protocol": "LAB-DNS", "qtype": m.group("qtype"),
            "name": m.group("name")}


def decode_lab_beacon(pkt: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Parse a LAB-BEACON label: ``LAB-BEACON id=<n> status=<ok|err>``."""
    m = LAB_BEACON_RE.match(str(pkt.get("payload_label", "")))
    if not m:
        return None
    return {"protocol": "LAB-BEACON", "beacon_id": int(m.group("bid")),
            "status": m.group("status")}


PROTOCOL_DECODERS = (decode_lab_http, decode_lab_dns, decode_lab_beacon)


def decode_note(pkt: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Return the first matching protocol note for a packet, else None."""
    for dec in PROTOCOL_DECODERS:
        note = dec(pkt)
        if note is not None:
            return note
    return None


# ---------------------------------------------------------------------------
# Documented anomaly baseline (named thresholds, printed in reports)
# ---------------------------------------------------------------------------

BASELINE: dict[str, Any] = {
    "name": "N01 lab baseline v1 (synthetic, documented 2026-10-23)",
    "port_scan_min_ports": 10,      # distinct dst ports from one src->dst...
    "port_scan_window_s": 120,      # ...inside this window => port-scan anomaly
    "beacon_min_packets": 5,        # min beacons to judge regularity
    "beacon_interval_cv_max": 0.15,  # coefficient of variation (std/mean)
    "beacon_min_interval_s": 5.0,   # sub-5s bursts are retransmit noise, not beacons
    "exfil_byte_threshold": 102400,  # per-session outbound bytes above this => exfil
    "normal_session_byte_cap": 51200,  # routine lab sessions stay under 50 KiB
    "expected_service_ports": [80, 443, 53, 123, 8080],
}


class NetForensicsError(Exception):
    """Workflow/state error (as opposed to a validation error)."""


def now_iso(clock: Optional[Callable[[], str]] = None) -> str:
    """Injectable clock: ``clock()`` must return an ISO-8601 string."""
    return clock() if clock is not None else utcnow_iso()


# ---------------------------------------------------------------------------
# Synthetic packet generator
# ---------------------------------------------------------------------------

def _payload_hash(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _emit(packets: list[dict[str, Any]], ts: float, src: str, dst: str,
          src_port: int, dst_port: int, flags: str, length: int,
          payload_label: str) -> dict[str, Any]:
    pkt = {
        "index": len(packets),
        "ts": ts,
        "src": src,
        "dst": dst,
        "src_port": src_port,
        "dst_port": dst_port,
        "proto": PROTO_TCP,
        "flags": flags,
        "length": length,
        "payload_label": payload_label,
        "payload_hash": _payload_hash(payload_label),
    }
    packets.append(pkt)
    return pkt


def _tcp_session(packets: list[dict[str, Any]], ts: float,
                 src: str, dst: str, src_port: int, dst_port: int,
                 data_labels: list[tuple[float, str, int, str]],
                 teardown: bool = True) -> tuple[int, int]:
    """Emit a complete synthetic TCP-ish session; return (start, end) index."""
    start = len(packets)
    _emit(packets, ts, src, dst, src_port, dst_port, FLAG_SYN, 0, "SYN")
    _emit(packets, ts + 0.001, dst, src, dst_port, src_port, FLAG_SYN_ACK, 0, "SYN-ACK")
    _emit(packets, ts + 0.002, src, dst, src_port, dst_port, FLAG_ACK, 0, "ACK")
    t = ts + 0.002
    for dt, label, length, direction in data_labels:
        t += dt
        if direction == "out":
            _emit(packets, t, src, dst, src_port, dst_port, FLAG_DATA, length, label)
        else:
            _emit(packets, t, dst, src, dst_port, src_port, FLAG_DATA, length, label)
    if teardown:
        _emit(packets, t + 0.001, src, dst, src_port, dst_port, FLAG_FIN, 0, "FIN")
        _emit(packets, t + 0.002, dst, src, dst_port, src_port, FLAG_ACK, 0, "ACK")
    return start, len(packets) - 1


def _background_traffic(packets: list[dict[str, Any]], ts: float,
                        rng: random.Random) -> None:
    """Routine lab chatter: NTP-ish poll + a couple of LAB-HTTP sessions."""
    _emit(packets, ts, LAB_WS01, LAB_SRV01, 51001, 123, FLAG_DATA, 48,
          "LAB-NTP poll")
    _emit(packets, ts + 0.01, LAB_SRV01, LAB_WS01, 123, 51001, FLAG_DATA, 48,
          "LAB-NTP reply")
    for i in range(2):
        _tcp_session(
            packets, ts + 1.0 + i * 3.0, LAB_WS01, LAB_SRV01,
            52000 + i, 80,
            [(0.01, f"LAB-HTTP GET /synth/{i}", 64, "out"),
             (0.01, f"LAB-HTTP R 200 /synth/{i}", 512, "in")],
        )


def _scenario_baseline_clean(seed: int, base_ts: float) -> tuple[list, dict]:
    packets: list[dict[str, Any]] = []
    rng = random.Random(seed)
    _background_traffic(packets, base_ts, rng)
    # A LAB-DNS lookup pair.
    _emit(packets, base_ts + 8.0, LAB_WS01, LAB_SRV01, 53001, 53,
          FLAG_DATA, 64, "LAB-DNS Q update.synth.local")
    _emit(packets, base_ts + 8.02, LAB_SRV01, LAB_WS01, 53, 53001,
          FLAG_DATA, 96, "LAB-DNS R update.synth.local")
    ground_truth = {
        "scenario": "baseline_clean",
        "expected_anomalies": [],
        "expected_sessions": 2,
        "notes": "routine lab chatter; no attack traffic injected",
    }
    return packets, ground_truth


def _scenario_port_scan(seed: int, base_ts: float) -> tuple[list, dict]:
    packets: list[dict[str, Any]] = []
    rng = random.Random(seed)
    _background_traffic(packets, base_ts, rng)
    # Attacker probes 24 ports; the lab defense denies every probe (RST).
    t = base_ts + 20.0
    probe_start = len(packets)
    scanned_ports = list(range(8000, 8024))
    for i, port in enumerate(scanned_ports):
        _emit(packets, t + i * 0.4, EXT_ATK, LAB_SRV01, 40000 + i, port,
              FLAG_SYN, 0, "SYN probe")
        _emit(packets, t + i * 0.4 + 0.05, LAB_SRV01, EXT_ATK, port, 40000 + i,
              FLAG_RST + "+" + FLAG_DENIED, 0, "RST defense-denied")
    probe_end = len(packets) - 1
    ground_truth = {
        "scenario": "port_scan",
        "expected_anomalies": ["port_scan"],
        "scanned_ports": scanned_ports,
        "probe_range": [probe_start, probe_end],
        "probe_count": len(scanned_ports) * 2,
        "notes": "24 SYN probes from 203.0.113.9, all denied by the lab",
    }
    return packets, ground_truth


def _scenario_c2_beaconing(seed: int, base_ts: float) -> tuple[list, dict]:
    packets: list[dict[str, Any]] = []
    rng = random.Random(seed)
    _background_traffic(packets, base_ts, rng)
    # Compromised host beacons every 60 s with tiny jitter (10 beacons).
    t = base_ts + 30.0
    beacon_start = len(packets)
    interval = 60.0
    for i in range(10):
        jitter = (rng.random() - 0.5) * 0.4  # +/- 0.2 s deterministic jitter
        _emit(packets, t + i * interval + jitter, LAB_WS01, EXT_C2,
              55001, 4443, FLAG_DATA, 96,
              f"LAB-BEACON id={i} status=ok")
        _emit(packets, t + i * interval + jitter + 0.05, EXT_C2, LAB_WS01,
              4443, 55001, FLAG_DATA, 64,
              f"LAB-BEACON id={i} status=ok")
    beacon_end = len(packets) - 1
    ground_truth = {
        "scenario": "c2_beaconing",
        "expected_anomalies": ["beaconing"],
        "beacon_interval_s": interval,
        "beacon_count": 10,
        "beacon_range": [beacon_start, beacon_end],
        "notes": "10 synthetic beacons at 60 s intervals (+/-0.2 s jitter)",
    }
    return packets, ground_truth


def _scenario_exfiltration(seed: int, base_ts: float) -> tuple[list, dict]:
    packets: list[dict[str, Any]] = []
    rng = random.Random(seed)
    _background_traffic(packets, base_ts, rng)
    # Large outbound transfer on an unusual high port.
    t = base_ts + 40.0
    labels = [(0.005, f"LAB-EXFIL chunk={i}", 1400, "out") for i in range(400)]
    start, end = _tcp_session(packets, t, LAB_WS01, EXT_WEB, 56001, 31337,
                              labels, teardown=True)
    ground_truth = {
        "scenario": "data_exfiltration",
        "expected_anomalies": ["byte_exfiltration"],
        "exfil_session_range": [start, end],
        "exfil_bytes_out": 400 * 1400,
        "notes": "560,000 synthetic bytes outbound on port 31337",
    }
    return packets, ground_truth


_SCENARIO_BUILDERS = {
    "baseline_clean": _scenario_baseline_clean,
    "port_scan": _scenario_port_scan,
    "c2_beaconing": _scenario_c2_beaconing,
    "data_exfiltration": _scenario_exfiltration,
}


def generate_capture(scenario: str, seed: int = 20261023,
                     base_ts: float = 1790000000.0) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Generate a synthetic capture for a scripted scenario.

    Returns ``(packets, ground_truth)``. Packets are dicts with
    ``index, ts, src, dst, src_port, dst_port, proto, flags, length,
    payload_label, payload_hash``. Deterministic: same (scenario, seed)
    always yields identical packets.
    """
    if scenario not in _SCENARIO_BUILDERS:
        raise NetForensicsError(
            f"unknown scenario {scenario!r}; expected one of {sorted(_SCENARIO_BUILDERS)}")
    if not isinstance(seed, int):
        raise NetForensicsError("seed must be an int")
    return _SCENARIO_BUILDERS[scenario](seed, base_ts)


# ---------------------------------------------------------------------------
# Session reconstruction (5-tuple reassembly)
# ---------------------------------------------------------------------------

def session_key(pkt: dict[str, Any]) -> tuple:
    return (pkt["src"], pkt["dst"], pkt["src_port"], pkt["dst_port"], pkt["proto"])


def reconstruct_sessions(packets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group packets into sessions by bidirectional 5-tuple.

    Both directions of a conversation share one session, keyed on the
    unordered endpoint pair; the SYN sender (or first packet's source) is
    recorded as the initiator. A session is "handshake complete" when SYN
    (initiator), SYN-ACK (responder), ACK (initiator) appear in order.
    Teardown is seen on FIN or RST from either side. One-sided flows
    (single DATA packets, denied probes) are sessions too, flagged
    ``handshake_complete=False``.
    """
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for pkt in packets:
        ep_a = (pkt["src"], pkt["src_port"])
        ep_b = (pkt["dst"], pkt["dst_port"])
        groups.setdefault((pkt["proto"], frozenset((ep_a, ep_b))), []).append(pkt)
    sessions = []
    for key, pkts in groups.items():
        pkts = sorted(pkts, key=lambda p: p["index"])
        syns = [p for p in pkts if p["flags"] == FLAG_SYN]
        initiator = syns[0]["src"] if syns else pkts[0]["src"]
        other_srcs = {p["src"] for p in pkts} - {initiator}
        responder = next(iter(other_srcs)) if other_srcs else initiator
        ordered_flags = [(p["flags"], p["src"]) for p in pkts]
        handshake = False
        try:
            i_syn = next(i for i, (f, s) in enumerate(ordered_flags)
                         if f == FLAG_SYN and s == initiator)
            i_synack = next(i for i, (f, s) in enumerate(ordered_flags)
                            if f == FLAG_SYN_ACK and s == responder)
            i_ack = next(i for i, (f, s) in enumerate(ordered_flags)
                         if f == FLAG_ACK and s == initiator)
            handshake = i_syn < i_synack < i_ack
        except StopIteration:
            handshake = False
        teardown = any(FLAG_FIN in f or FLAG_RST in f for f, _ in ordered_flags)
        init_ports = {p["src_port"] for p in pkts if p["src"] == initiator}
        resp_ports = {p["dst_port"] for p in pkts if p["src"] == initiator}
        sessions.append({
            "session_key": "|".join([key[0], initiator, responder,
                                     str(sorted(init_ports)[0]) if init_ports else "?",
                                     str(sorted(resp_ports)[0]) if resp_ports else "?"]),
            "src": initiator, "dst": responder,
            "src_port": sorted(init_ports)[0] if init_ports else 0,
            "dst_port": sorted(resp_ports)[0] if resp_ports else 0,
            "proto": key[0],
            "start_index": pkts[0]["index"],
            "end_index": pkts[-1]["index"],
            "packet_count": len(pkts),
            "total_bytes": sum(p["length"] for p in pkts),
            "bytes_out": sum(p["length"] for p in pkts if p["src"] == initiator),
            "bytes_in": sum(p["length"] for p in pkts if p["src"] != initiator),
            "start_ts": pkts[0]["ts"],
            "end_ts": pkts[-1]["ts"],
            "handshake_complete": handshake,
            "teardown_seen": teardown,
            "protocol_note": _session_protocol_note(pkts),
        })
    sessions.sort(key=lambda s: s["start_index"])
    return sessions


def _session_protocol_note(pkts: list[dict[str, Any]]) -> Optional[str]:
    notes = []
    seen = set()
    for p in pkts:
        note = decode_note(p)
        if note and note["protocol"] not in seen:
            seen.add(note["protocol"])
            notes.append(note["protocol"])
    return ",".join(notes) if notes else None


# ---------------------------------------------------------------------------
# Timeline builder
# ---------------------------------------------------------------------------

def derive_alerts(anomalies: list[dict[str, Any]],
                  packets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert anomalies to S01-style alert events for the timeline."""
    alerts = []
    for a in anomalies:
        alerts.append({
            "ts": packets[a["start_index"]]["ts"],
            "kind": "alert",
            "alert_type": a["type"],
            "severity": "high" if a["type"] in ("port_scan", "byte_exfiltration")
            else "medium",
            "summary": a["summary"],
            "packet_range": a["packet_range"],
        })
    return alerts


def build_timeline(packets: list[dict[str, Any]],
                   sessions: list[dict[str, Any]],
                   alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge session markers + alert events into one chronological timeline."""
    events: list[dict[str, Any]] = []
    if packets:
        events.append({
            "ts": packets[0]["ts"], "kind": "capture_start",
            "summary": f"capture begins (packet 0 of {len(packets)})",
            "packet_range": [0, 0],
        })
    for s in sessions:
        events.append({
            "ts": s["start_ts"], "kind": "session_start",
            "summary": (f"session {s['src']}:{s['src_port']} -> "
                        f"{s['dst']}:{s['dst_port']} "
                        f"({s['packet_count']} packets, {s['total_bytes']} bytes)"),
            "packet_range": [s["start_index"], s["end_index"]],
            "session_key": s["session_key"],
        })
    events.extend(alerts)
    if packets:
        events.append({
            "ts": packets[-1]["ts"], "kind": "capture_end",
            "summary": f"capture ends (packet {len(packets) - 1})",
            "packet_range": [len(packets) - 1, len(packets) - 1],
        })
    events.sort(key=lambda e: (e["ts"], e["kind"]))
    return events


# ---------------------------------------------------------------------------
# Anomaly detection against the documented baseline
# ---------------------------------------------------------------------------

def detect_anomalies(packets: list[dict[str, Any]],
                     sessions: list[dict[str, Any]],
                     baseline: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Run all three detectors; every anomaly cites a packet range."""
    baseline = baseline or BASELINE
    anomalies: list[dict[str, Any]] = []
    anomalies.extend(_detect_port_scan(packets, baseline))
    anomalies.extend(_detect_beaconing(packets, baseline))
    anomalies.extend(_detect_exfiltration(sessions, baseline))
    anomalies.sort(key=lambda a: a["start_index"])
    return anomalies


def _detect_port_scan(packets: list[dict[str, Any]],
                      baseline: dict[str, Any]) -> list[dict[str, Any]]:
    min_ports = baseline["port_scan_min_ports"]
    window = baseline["port_scan_window_s"]
    out = []
    # Group SYN probes by (src, dst).
    probes: dict[tuple, list[dict[str, Any]]] = {}
    for p in packets:
        if p["flags"] == FLAG_SYN and p["payload_label"] == "SYN probe":
            probes.setdefault((p["src"], p["dst"]), []).append(p)
    for (src, dst), plist in probes.items():
        plist.sort(key=lambda p: p["ts"])
        ports = {p["dst_port"] for p in plist}
        span = plist[-1]["ts"] - plist[0]["ts"]
        if len(ports) >= min_ports and span <= window:
            # Include the denial replies (RST+DENIED, emitted right after
            # each probe) in the cited range.
            lo = plist[0]["index"]
            replies = [q["index"] for q in packets
                       if FLAG_DENIED in q["flags"]
                       and q["src"] == dst and q["dst"] == src]
            hi = max(replies) if replies else plist[-1]["index"]
            out.append({
                "type": "port_scan",
                "summary": (f"{len(ports)} distinct ports probed by {src} "
                            f"against {dst} within {span:.1f}s "
                            f"(threshold: >={min_ports} ports / {window}s); "
                            "all probes denied by the lab defense"),
                "detail": {"src": src, "dst": dst,
                           "distinct_ports": sorted(ports),
                           "probe_count": len(plist), "span_s": round(span, 3)},
                "start_index": lo,
                "end_index": hi,
                "packet_range": [lo, hi],
                "confidence": "high",
            })
    return out


def _detect_beaconing(packets: list[dict[str, Any]],
                      baseline: dict[str, Any]) -> list[dict[str, Any]]:
    min_n = baseline["beacon_min_packets"]
    cv_max = baseline["beacon_interval_cv_max"]
    min_interval = baseline["beacon_min_interval_s"]
    out = []
    beacons: dict[tuple, list[dict[str, Any]]] = {}
    for p in packets:
        # Only the outbound beacon frames (lab host -> external) define the
        # interval; replies are cited in the range but excluded from the
        # interval math.
        if (decode_lab_beacon(p) and p["length"] <= 128
                and p["src"].startswith("192.0.2.")):
            key = (p["src"], p["dst"], p["dst_port"])
            beacons.setdefault(key, []).append(p)
    for (src, dst, dport), blist in beacons.items():
        blist.sort(key=lambda p: p["ts"])
        if len(blist) < min_n:
            continue
        gaps = [b["ts"] - a["ts"] for a, b in zip(blist, blist[1:])]
        mean_gap = statistics.fmean(gaps)
        if mean_gap < min_interval:
            continue
        cv = (statistics.pstdev(gaps) / mean_gap) if mean_gap else float("inf")
        if cv <= cv_max:
            # Cite the full conversation: extend the range to cover replies
            # interleaved between the first and last beacon frame.
            lo, hi = blist[0]["index"], blist[-1]["index"]
            between = [q["index"] for q in packets
                       if lo <= q["index"] <= hi + 5
                       and {q["src"], q["dst"]} == {src, dst}]
            hi = max(between) if between else hi
            out.append({
                "type": "beaconing",
                "summary": (f"{len(blist)} LAB-BEACON frames {src} -> {dst}:{dport} "
                            f"at {mean_gap:.2f}s mean interval "
                            f"(CV {cv:.3f} <= {cv_max}); matches C2-beacon profile"),
                "detail": {"src": src, "dst": dst, "dst_port": dport,
                           "beacon_count": len(blist),
                           "mean_interval_s": round(mean_gap, 3),
                           "interval_cv": round(cv, 4)},
                "start_index": lo,
                "end_index": hi,
                "packet_range": [lo, hi],
                "confidence": "high",
            })
    return out


def _detect_exfiltration(sessions: list[dict[str, Any]],
                        baseline: dict[str, Any]) -> list[dict[str, Any]]:
    threshold = baseline["exfil_byte_threshold"]
    out = []
    for s in sessions:
        # Outbound = from a lab host (192.0.2.x) toward an external address.
        outbound = s["src"].startswith("192.0.2.") and not s["dst"].startswith("192.0.2.")
        if outbound and s["bytes_out"] > threshold:
            out.append({
                "type": "byte_exfiltration",
                "summary": (f"session {s['src']}:{s['src_port']} -> "
                            f"{s['dst']}:{s['dst_port']} moved {s['bytes_out']} "
                            f"bytes outbound (threshold {threshold})"),
                "detail": {"session_key": s["session_key"],
                           "src": s["src"], "dst": s["dst"],
                           "bytes_out": s["bytes_out"],
                           "threshold": threshold,
                           "dst_port": s["dst_port"]},
                "start_index": s["start_index"],
                "end_index": s["end_index"],
                "packet_range": [s["start_index"], s["end_index"]],
                "confidence": "medium",
            })
    return out


# ---------------------------------------------------------------------------
# Scoping
# ---------------------------------------------------------------------------

def scope_incident(anomalies: list[dict[str, Any]],
                   sessions: list[dict[str, Any]],
                   packets: list[dict[str, Any]],
                   margin_s: float = 60.0) -> dict[str, Any]:
    """Derive incident scope from anomalies: hosts, sessions, time window."""
    if not anomalies:
        return {
            "affected_hosts": [],
            "affected_sessions": [],
            "start_ts": None, "end_ts": None,
            "start_index": None, "end_index": None,
            "anomaly_types": [],
            "summary": "no anomalies detected; no incident scope to declare",
        }
    hosts: set[str] = set()
    sess_keys: set[str] = set()
    for a in anomalies:
        d = a.get("detail", {})
        for k in ("src", "dst"):
            if d.get(k):
                hosts.add(d[k])
        if d.get("session_key"):
            sess_keys.add(d["session_key"])
        # Port-scan probes that were denied still implicate the target host.
    lo = min(a["start_index"] for a in anomalies)
    hi = max(a["end_index"] for a in anomalies)
    start_ts = packets[lo]["ts"] - margin_s
    end_ts = packets[hi]["ts"] + margin_s
    return {
        "affected_hosts": sorted(hosts),
        "affected_sessions": sorted(sess_keys),
        "start_ts": start_ts,
        "end_ts": end_ts,
        "start_index": lo,
        "end_index": hi,
        "anomaly_types": sorted({a["type"] for a in anomalies}),
        "summary": (f"{len(anomalies)} anomalie(s) "
                    f"({', '.join(sorted({a['type'] for a in anomalies}))}) "
                    f"involving {len(hosts)} host(s), packet range [{lo}, {hi}]"),
    }


# ---------------------------------------------------------------------------
# Evidentiary report: facts vs inference, every claim cites a packet range
# ---------------------------------------------------------------------------

def _validate_claim(claim: dict[str, Any], packet_count: int, kind: str) -> None:
    pr = claim.get("packet_range")
    if (not isinstance(pr, (list, tuple)) or len(pr) != 2
            or not all(isinstance(x, int) for x in pr)
            or not (0 <= pr[0] <= pr[1] < packet_count)):
        raise NetForensicsError(
            f"{kind} claim missing a valid packet_range [lo, hi]: "
            f"{claim.get('statement', claim)!r}")
    if kind == "inference":
        if claim.get("confidence") not in CONFIDENCE_LEVELS:
            raise NetForensicsError(
                "inference without a confidence level is rejected: "
                f"{claim.get('statement', claim)!r} "
                f"(must be one of {CONFIDENCE_LEVELS})")


def build_report(capture_ref: str, scenario: str, seed: int,
                 packets: list[dict[str, Any]],
                 sessions: list[dict[str, Any]],
                 anomalies: list[dict[str, Any]],
                 scope: dict[str, Any],
                 facts: list[dict[str, Any]],
                 inferences: list[dict[str, Any]],
                 ground_truth: Optional[dict[str, Any]] = None,
                 clock: Optional[Callable[[], str]] = None) -> dict[str, Any]:
    """Assemble the evidentiary report.

    Facts = directly observed (counts, bytes, flags). Inferences =
    interpretations and MUST carry confidence; rejected otherwise.
    Every claim MUST cite a valid ``packet_range``; rejected otherwise.
    """
    n = len(packets)
    for f in facts:
        _validate_claim(f, n, "fact")
    for i in inferences:
        _validate_claim(i, n, "inference")
    return {
        "capture_ref": capture_ref,
        "scenario": scenario,
        "seed": seed,
        "ethical_banner": ETHICAL_BANNER,
        "synthetic": True,
        "created_at": now_iso(clock),
        "packet_count": n,
        "baseline": BASELINE,
        "scope": scope,
        "facts": facts,
        "inferences": inferences,
        "anomalies": [
            {k: a[k] for k in ("type", "summary", "packet_range", "confidence")}
            for a in anomalies
        ],
        "ground_truth_match": (
            sorted(a["type"] for a in anomalies)
            == sorted((ground_truth or {}).get("expected_anomalies", []))
            if ground_truth is not None else None
        ),
    }


def auto_facts(packets: list[dict[str, Any]],
               sessions: list[dict[str, Any]],
               anomalies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Derive the mechanical fact claims for a capture (observed only)."""
    facts: list[dict[str, Any]] = [{
        "statement": f"capture contains {len(packets)} synthetic packets",
        "packet_range": [0, len(packets) - 1] if packets else [0, 0],
    }]
    for s in sessions:
        facts.append({
            "statement": (f"session {s['src']}:{s['src_port']} -> "
                          f"{s['dst']}:{s['dst_port']}: {s['packet_count']} packets, "
                          f"{s['total_bytes']} bytes, handshake_complete="
                          f"{s['handshake_complete']}, teardown_seen={s['teardown_seen']}"),
            "packet_range": [s["start_index"], s["end_index"]],
        })
    for a in anomalies:
        facts.append({
            "statement": f"anomaly detected: {a['summary']}",
            "packet_range": list(a["packet_range"]),
        })
    return facts


# ---------------------------------------------------------------------------
# SQLite persistence
# ---------------------------------------------------------------------------

def _require_columns(conn: sqlite3.Connection) -> None:
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    missing = {"netforensics_captures", "netforensics_packets",
               "netforensics_sessions", "netforensics_anomalies",
               "netforensics_reports"} - tables
    if missing:
        raise NetForensicsError(
            f"netforensics tables missing ({sorted(missing)}); "
            "run migrations (018_netforensics) first")


def save_capture(conn: sqlite3.Connection, capture_ref: str, scenario: str,
                 seed: int, packets: list[dict[str, Any]],
                 clock: Optional[Callable[[], str]] = None) -> int:
    _require_columns(conn)
    if not capture_ref or not capture_ref.strip():
        raise ValidationError("capture_ref is required")
    try:
        cur = conn.execute(
            "INSERT INTO netforensics_captures "
            "(capture_ref, scenario, seed, packet_count, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (capture_ref, scenario, seed, len(packets), now_iso(clock)))
    except sqlite3.IntegrityError as exc:
        raise NetForensicsError(f"capture_ref {capture_ref!r} already exists") from exc
    cid = cur.lastrowid
    conn.executemany(
        "INSERT INTO netforensics_packets "
        "(capture_id, pkt_index, ts, src, dst, src_port, dst_port, proto, "
        " flags, length, payload_label, payload_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(cid, p["index"], p["ts"], p["src"], p["dst"], p["src_port"],
          p["dst_port"], p["proto"], p["flags"], p["length"],
          p["payload_label"], p["payload_hash"]) for p in packets])
    conn.commit()
    return cid


def save_sessions(conn: sqlite3.Connection, capture_id: int,
                  sessions: list[dict[str, Any]]) -> int:
    _require_columns(conn)
    conn.executemany(
        "INSERT INTO netforensics_sessions "
        "(capture_id, session_key, start_index, end_index, packet_count, "
        " total_bytes, handshake_complete, teardown_seen, protocol_note) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(capture_id, s["session_key"], s["start_index"], s["end_index"],
          s["packet_count"], s["total_bytes"],
          int(s["handshake_complete"]), int(s["teardown_seen"]),
          s["protocol_note"]) for s in sessions])
    conn.commit()
    return len(sessions)


def save_anomalies(conn: sqlite3.Connection, capture_id: int,
                   anomalies: list[dict[str, Any]]) -> int:
    _require_columns(conn)
    conn.executemany(
        "INSERT INTO netforensics_anomalies "
        "(capture_id, anomaly_type, summary, detail_json, start_index, "
        " end_index, confidence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(capture_id, a["type"], a["summary"], json.dumps(a["detail"]),
          a["start_index"], a["end_index"], a["confidence"]) for a in anomalies])
    conn.commit()
    return len(anomalies)


def save_report(conn: sqlite3.Connection, capture_id: int,
                report_ref: str, report: dict[str, Any],
                clock: Optional[Callable[[], str]] = None) -> int:
    _require_columns(conn)
    if not report_ref or not report_ref.strip():
        raise ValidationError("report_ref is required")
    try:
        cur = conn.execute(
            "INSERT INTO netforensics_reports "
            "(capture_id, report_ref, report_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            (capture_id, report_ref, json.dumps(report), now_iso(clock)))
    except sqlite3.IntegrityError as exc:
        raise NetForensicsError(f"report_ref {report_ref!r} already exists") from exc
    conn.commit()
    return cur.lastrowid


def list_captures(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    _require_columns(conn)
    return [dict(r) for r in conn.execute(
        "SELECT * FROM netforensics_captures ORDER BY id DESC")]


def get_capture(conn: sqlite3.Connection, capture_id: int) -> dict[str, Any]:
    _require_columns(conn)
    row = conn.execute(
        "SELECT * FROM netforensics_captures WHERE id = ?", (capture_id,)).fetchone()
    if row is None:
        raise NetForensicsError(f"capture {capture_id} not found")
    return dict(row)


def list_packets(conn: sqlite3.Connection, capture_id: int) -> list[dict[str, Any]]:
    _require_columns(conn)
    return [dict(r) for r in conn.execute(
        "SELECT * FROM netforensics_packets WHERE capture_id = ? "
        "ORDER BY pkt_index", (capture_id,))]


def list_sessions(conn: sqlite3.Connection, capture_id: int) -> list[dict[str, Any]]:
    _require_columns(conn)
    return [dict(r) for r in conn.execute(
        "SELECT * FROM netforensics_sessions WHERE capture_id = ? "
        "ORDER BY start_index", (capture_id,))]


def list_anomalies(conn: sqlite3.Connection, capture_id: int) -> list[dict[str, Any]]:
    _require_columns(conn)
    return [dict(r) for r in conn.execute(
        "SELECT * FROM netforensics_anomalies WHERE capture_id = ? "
        "ORDER BY start_index", (capture_id,))]


def get_report(conn: sqlite3.Connection, capture_id: int) -> dict[str, Any]:
    _require_columns(conn)
    row = conn.execute(
        "SELECT * FROM netforensics_reports WHERE capture_id = ? "
        "ORDER BY id DESC LIMIT 1", (capture_id,)).fetchone()
    if row is None:
        raise NetForensicsError(f"no report stored for capture {capture_id}")
    d = dict(row)
    d["report"] = json.loads(d["report_json"])
    return d


def run_full_pipeline(scenario: str, seed: int = 20261023,
                      capture_ref: Optional[str] = None,
                      clock: Optional[Callable[[], str]] = None
                      ) -> dict[str, Any]:
    """In-memory end-to-end run: capture -> sessions -> timeline -> anomalies
    -> scope -> report. Returns every artifact (nothing persisted)."""
    packets, ground_truth = generate_capture(scenario, seed)
    sessions = reconstruct_sessions(packets)
    anomalies = detect_anomalies(packets, sessions)
    alerts = derive_alerts(anomalies, packets)
    timeline = build_timeline(packets, sessions, alerts)
    scope = scope_incident(anomalies, sessions, packets)
    facts = auto_facts(packets, sessions, anomalies)
    inferences = _scripted_inferences(scenario, anomalies, len(packets))
    report = build_report(
        capture_ref or f"{scenario}-{seed}", scenario, seed,
        packets, sessions, anomalies, scope, facts, inferences,
        ground_truth=ground_truth, clock=clock)
    return {
        "packets": packets, "ground_truth": ground_truth,
        "sessions": sessions, "anomalies": anomalies,
        "alerts": alerts, "timeline": timeline, "scope": scope,
        "report": report,
    }


def _scripted_inferences(scenario: str, anomalies: list[dict[str, Any]],
                         packet_count: int) -> list[dict[str, Any]]:
    """Labeled, scenario-aware inferences for the demo report.

    In the real tool these would be analyst-authored; here they are
    generated from the scenario script and explicitly marked synthetic.
    Every inference carries a confidence level (required)."""
    inf = []
    for a in anomalies:
        lo, hi = a["packet_range"]
        if a["type"] == "port_scan":
            inf.append({
                "statement": ("the probe pattern is consistent with a scripted "
                              "reconnaissance scan; all probes were denied, so "
                              "no service fingerprinting succeeded"),
                "packet_range": [lo, hi], "confidence": "medium"})
        elif a["type"] == "beaconing":
            inf.append({
                "statement": ("the regular outbound beaconing is consistent "
                              "with a simulated C2 heartbeat from the lab "
                              "workstation"),
                "packet_range": [lo, hi], "confidence": "medium"})
        elif a["type"] == "byte_exfiltration":
            inf.append({
                "statement": ("the large outbound transfer on a non-standard "
                              "port is consistent with a simulated data "
                              "exfiltration; content was synthetic labels only"),
                "packet_range": [lo, hi], "confidence": "medium"})
    if not anomalies:
        inf.append({
            "statement": ("no anomalous patterns observed; the capture is "
                          "consistent with routine lab activity"),
            "packet_range": [0, packet_count - 1] if packet_count else [0, 0],
            "confidence": "low"})
    return inf
