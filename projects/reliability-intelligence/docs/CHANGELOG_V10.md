# V10 change and security-delta record

**Change:** Freeze the V9 synthetic prototype baseline and open its risk list. Add controlled unsigned decision record, 18-file Git object integrity verification, 23 negative/governance tests, and GitHub Actions evidence.

**Unchanged:** V9 application code, API schema 1.3.0, runtime version 0.9.0, synthetic fixtures, V6 replay, WSGI-only local transport and read-only API methods.

**Security delta:** Documentation/tests only, no customer data, secrets, authorization, exposure, filesystem write-back or OT connection introduced. No industrial use authorized.

**Rollback:** Revert the V10 documentation, tests and workflow changes. Original V9 source and fixtures remain pinned and do not need database migration. An integrity failure must never be fixed by silently updating the expected hash.

**Decision scope:** Formal V10 and V11–V20 promotion recommended BLOCKED; internal synthetic-only exploratory work is permissible but not a signed phase advancement.
