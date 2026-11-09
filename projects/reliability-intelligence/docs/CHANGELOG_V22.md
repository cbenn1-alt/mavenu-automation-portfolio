# V22 change / security delta / rollback

Added JSON identity policy, strict ASCII case-sensitive token validation, controlled synthetic reference-data categories, 13 scoped uniqueness and nine FK checks, 25 copied-fixture negative cases, 102 regression tests, verifier/evidence package, and V8–V22 clean-archive CI integration.

Preserved V9 frozen application runtime 0.9.0 and read-only API v1/schema 1.3.0; V10 frozen 18-file source; V11–V21 contracts and code; no production persistence. V21 SQLite :memory: DDL is unchanged; V22 uses it only for uniqueness/link smoke checks.

Security: no actual tenant authentication or row authorization, production database, external identity provider, CMMS/ERP connector, OT/SCADA command, real customer information or independently approved reference taxonomy. False sign-off/production access claims and unknown external records fail closed.

Rollback V22-only files and workflow steps; no data migration or recovery is required. V10/V20 formal phase gate and V21/V22 human reviews remain outstanding.
