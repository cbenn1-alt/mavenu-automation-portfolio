-- Mavenu Reliability Intelligence V21
-- Candidate canonical entity/relationship schema for synthetic-only review.
-- NOT an approved deployment migration, customer source model, or durable DB.
-- V10 formal phase promotion and V20 data-quality sign-off are BLOCKED.
-- SQLite :memory: only. V22 identity and V23 reversible migration not built.
PRAGMA foreign_keys = ON;

CREATE TABLE tenant (
    tenant_id TEXT PRIMARY KEY NOT NULL CHECK(tenant_id LIKE 'SYN-%'),
    tenant_label TEXT NOT NULL,
    source_scope TEXT NOT NULL CHECK(source_scope = 'synthetic_only')
) WITHOUT ROWID;

CREATE TABLE site (
    tenant_id TEXT NOT NULL,
    site_id TEXT NOT NULL CHECK(site_id LIKE 'SYN-SITE-%'),
    site_label TEXT NOT NULL,
    fictional_flag INTEGER NOT NULL CHECK(fictional_flag = 1),
    PRIMARY KEY (tenant_id, site_id),
    FOREIGN KEY (tenant_id) REFERENCES tenant(tenant_id)
) WITHOUT ROWID;

CREATE TABLE asset (
    tenant_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    asset_id TEXT NOT NULL CHECK(asset_id LIKE 'SYN-ASSET-%'),
    asset_class TEXT NOT NULL,
    cohort TEXT NOT NULL,
    synthetic_flag INTEGER NOT NULL CHECK(synthetic_flag = 1),
    PRIMARY KEY (tenant_id, site_id, asset_id),
    FOREIGN KEY (tenant_id, site_id)
       REFERENCES site(tenant_id, site_id)
) WITHOUT ROWID;

CREATE TABLE maintenance_case (
    tenant_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    case_id TEXT NOT NULL CHECK(case_id LIKE 'SYN-CASE-%'),
    asset_id TEXT NOT NULL,
    work_order_ref TEXT NOT NULL CHECK(work_order_ref LIKE 'SYN-WO-%'),
    occurred_at_utc TEXT NOT NULL CHECK(
        length(occurred_at_utc) = 20 AND substr(occurred_at_utc, 20, 1) = 'Z'
    ),
    failure_code TEXT NOT NULL,
    downtime_seconds INTEGER NOT NULL
       CHECK(downtime_seconds >= 0 AND downtime_seconds <= 864000),
    repair_cost_cents INTEGER NOT NULL
       CHECK(repair_cost_cents >= 0 AND repair_cost_cents <= 100000000),
    review_state TEXT NOT NULL CHECK(review_state = 'fixture_only'),
    synthetic_flag INTEGER NOT NULL CHECK(synthetic_flag = 1),
    PRIMARY KEY (tenant_id, site_id, case_id),
    UNIQUE (tenant_id, site_id, work_order_ref),
    FOREIGN KEY (tenant_id, site_id, asset_id)
       REFERENCES asset(tenant_id, site_id, asset_id)
) WITHOUT ROWID;

CREATE TABLE evidence_reference (
    tenant_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    evidence_ref TEXT NOT NULL CHECK(evidence_ref LIKE 'SYN-EV-%'),
    external_document_verified INTEGER NOT NULL CHECK(external_document_verified = 0),
    PRIMARY KEY (tenant_id, site_id, case_id, evidence_ref),
    FOREIGN KEY (tenant_id, site_id, case_id)
       REFERENCES maintenance_case(tenant_id, site_id, case_id)
) WITHOUT ROWID;

CREATE TABLE scripted_review (
    tenant_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    reviewer_id TEXT NOT NULL CHECK(reviewer_id LIKE 'SYN-REVIEWER-%'),
    disposition TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    human_executed INTEGER NOT NULL CHECK(human_executed = 0),
    PRIMARY KEY (tenant_id, site_id, case_id, reviewer_id),
    FOREIGN KEY (tenant_id, site_id, case_id)
       REFERENCES maintenance_case(tenant_id, site_id, case_id)
) WITHOUT ROWID;

CREATE TABLE reference_label (
    tenant_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    expected_review_label TEXT NOT NULL,
    independently_validated INTEGER NOT NULL CHECK(independently_validated = 0),
    PRIMARY KEY (tenant_id, site_id, case_id),
    FOREIGN KEY (tenant_id, site_id, case_id)
       REFERENCES maintenance_case(tenant_id, site_id, case_id)
) WITHOUT ROWID;

CREATE TABLE source_document (
    tenant_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    source_document_id TEXT NOT NULL CHECK(source_document_id LIKE 'SYN-DOC-%'),
    fixture_path TEXT NOT NULL CHECK(fixture_path IN (
        'fixtures/cases.json',
        'fixtures/demo_review_script.json',
        'fixtures/reference_labels.json'
    )),
    raw_sha256 TEXT NOT NULL CHECK(length(raw_sha256) = 64),
    fixture_set_id TEXT NOT NULL CHECK(fixture_set_id = 'SYN-RI-V5-20261107-A'),
    origin_kind TEXT NOT NULL
       CHECK(origin_kind = 'committed_synthetic_fixture_reconstruction'),
    observed_ingestion_at_utc TEXT CHECK(observed_ingestion_at_utc IS NULL),
    PRIMARY KEY (tenant_id, site_id, source_document_id),
    UNIQUE (tenant_id, site_id, fixture_path),
    FOREIGN KEY (tenant_id, site_id)
       REFERENCES site(tenant_id, site_id)
) WITHOUT ROWID;

CREATE TABLE record_origin (
    tenant_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    trace_id TEXT NOT NULL CHECK(trace_id LIKE 'SYN-LINEAGE-%'),
    source_document_id TEXT NOT NULL,
    source_dataset TEXT NOT NULL CHECK(source_dataset IN (
       'asset_records', 'case_records',
       'scripted_review_entries', 'seeded_reference_labels'
    )),
    source_record_id TEXT NOT NULL CHECK(source_record_id LIKE 'SYN-%'),
    source_json_pointer TEXT NOT NULL CHECK(source_json_pointer LIKE '/%'),
    source_record_sha256 TEXT NOT NULL CHECK(length(source_record_sha256) = 64),
    normalized_record_sha256 TEXT NOT NULL CHECK(length(normalized_record_sha256) = 64),
    observed_ingestion_at_utc TEXT CHECK(observed_ingestion_at_utc IS NULL),
    customer_source_observed INTEGER NOT NULL CHECK(customer_source_observed = 0),
    PRIMARY KEY (tenant_id, site_id, trace_id),
    UNIQUE (tenant_id, site_id, source_document_id, source_dataset, source_record_id),
    FOREIGN KEY (tenant_id, site_id, source_document_id)
       REFERENCES source_document(tenant_id, site_id, source_document_id)
) WITHOUT ROWID;

CREATE TABLE transform_step (
    tenant_id TEXT NOT NULL,
    site_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    step_ordinal INTEGER NOT NULL CHECK(step_ordinal BETWEEN 1 AND 3),
    rule_id TEXT NOT NULL CHECK(rule_id IN (
        'V15_UTC_EXPLICIT', 'V15_HOURS_EXACT', 'V15_USD_EXACT_CENTS'
    )),
    source_field TEXT NOT NULL,
    target_field TEXT NOT NULL,
    source_value_sha256 TEXT NOT NULL CHECK(length(source_value_sha256) = 64),
    canonical_value_sha256 TEXT NOT NULL CHECK(length(canonical_value_sha256) = 64),
    PRIMARY KEY (tenant_id, site_id, trace_id, step_ordinal),
    FOREIGN KEY (tenant_id, site_id, trace_id)
       REFERENCES record_origin(tenant_id, site_id, trace_id)
) WITHOUT ROWID;
