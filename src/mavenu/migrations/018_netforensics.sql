-- 018_netforensics.sql — Project N01 (Network Forensics).
--
-- ALL DATA IS SYNTHETIC DEMONSTRATION DATA. Every capture, packet,
-- session, anomaly, and report stored here is generated fixture material
-- for the N01 method demonstration. Packets are plain rows produced by
-- the seeded generator in netforensics.py — this schema stores synthetic
-- dicts, never a real network tap. No real network, host, or person is
-- represented. Lawful-lab scope only: never capture a real network
-- without explicit written authorization from its owner.
--
-- Design notes:
--   * netforensics_captures: one row per synthetic capture run
--     (scenario + seed are the reproducibility key; capture_ref unique).
--   * netforensics_packets: the synthetic packets themselves
--     (ts, 5-tuple, flags, length, synthetic payload label + SHA-256).
--   * netforensics_sessions: 5-tuple reassembly output with
--     handshake/teardown flags and protocol notes.
--   * netforensics_anomalies: detector output, each citing a packet
--     index range [start_index, end_index].
--   * netforensics_reports: the evidentiary report JSON (facts vs
--     inference, every claim citing a packet range).

CREATE TABLE netforensics_captures (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_ref     TEXT NOT NULL UNIQUE,
    scenario        TEXT NOT NULL
                    CHECK (scenario IN ('baseline_clean','port_scan',
                                       'c2_beaconing','data_exfiltration')),
    seed            INTEGER NOT NULL,
    packet_count    INTEGER NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_nf_captures_scenario ON netforensics_captures(scenario);

CREATE TABLE netforensics_packets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id      INTEGER NOT NULL REFERENCES netforensics_captures(id),
    pkt_index       INTEGER NOT NULL,
    ts              REAL NOT NULL,
    src             TEXT NOT NULL,
    dst             TEXT NOT NULL,
    src_port        INTEGER NOT NULL,
    dst_port        INTEGER NOT NULL,
    proto           TEXT NOT NULL,
    flags           TEXT NOT NULL,
    length          INTEGER NOT NULL,
    payload_label   TEXT NOT NULL,
    payload_hash    TEXT NOT NULL,
    UNIQUE (capture_id, pkt_index)
);
CREATE INDEX idx_nf_packets_capture ON netforensics_packets(capture_id);

CREATE TABLE netforensics_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id      INTEGER NOT NULL REFERENCES netforensics_captures(id),
    session_key     TEXT NOT NULL,
    start_index     INTEGER NOT NULL,
    end_index       INTEGER NOT NULL,
    packet_count    INTEGER NOT NULL,
    total_bytes     INTEGER NOT NULL,
    handshake_complete INTEGER NOT NULL CHECK (handshake_complete IN (0,1)),
    teardown_seen   INTEGER NOT NULL CHECK (teardown_seen IN (0,1)),
    protocol_note   TEXT
);
CREATE INDEX idx_nf_sessions_capture ON netforensics_sessions(capture_id);

CREATE TABLE netforensics_anomalies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id      INTEGER NOT NULL REFERENCES netforensics_captures(id),
    anomaly_type    TEXT NOT NULL
                    CHECK (anomaly_type IN ('port_scan','beaconing',
                                           'byte_exfiltration')),
    summary         TEXT NOT NULL,
    detail_json     TEXT NOT NULL,
    start_index     INTEGER NOT NULL,
    end_index       INTEGER NOT NULL,
    confidence      TEXT NOT NULL CHECK (confidence IN ('low','medium','high'))
);
CREATE INDEX idx_nf_anomalies_capture ON netforensics_anomalies(capture_id);

CREATE TABLE netforensics_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    capture_id      INTEGER NOT NULL REFERENCES netforensics_captures(id),
    report_ref      TEXT NOT NULL UNIQUE,
    report_json     TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX idx_nf_reports_capture ON netforensics_reports(capture_id);
