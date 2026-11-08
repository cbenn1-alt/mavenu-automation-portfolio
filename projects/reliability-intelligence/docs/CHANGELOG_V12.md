# V12 change record and security delta

**Added:** 4-group / 21-field V12 strict synthetic schema contract, deterministic verifier, 16 negative in-memory cases, 34 regression tests, report and evidence documentation. CI now runs V8–V12 and retains the V12 report.

**Unchanged:** Pinned V9 application runtime 0.9.0, API schema 1.3.0, V10 frozen 18-file source/configuration baseline, V11 draft dictionary, synthetic fixtures and no customer/OT interfaces.

**Security:** No new credentials, customer records, live systems, controls, write routes or persistent operational audit. Extra source fields and unsigned claims are rejected. No formal human sign-off has been generated.

**Rollback:** Revert V12 scripts/tests/docs and CI changes. No migration or customer state exists.
