# N02 — Security

> **⚠ FICTIONAL COMPANY — SYNTHETIC DATA. ILLUSTRATIVE SCORES ONLY.**

## 1. Data classification

Everything N02 stores and displays is synthetic: a fictional company,
invented assets/threats/ratings/costs/efforts. There is no real
organization, no real assessment, and no real PII anywhere in the
module, fixtures, migrations, tests, or docs. The ethical banner is
embedded in the module, the API responses, and every web page.

## 2. Input validation

- `score_risk()` / `_check_level()` reject any likelihood/impact value
  that is not an integer 1–5 (`RiskError` → rendered as HTTP 400 by the
  web layer's `ValidationError` handler).
- `band_for_score()` rejects scores outside 1–25 (no silent clamping).
- `build_register()` structurally validates the fixture: unique risk
  ids, known asset/threat ids, threat applicability to the asset type,
  ≥1 control ref per entry, every ref resolving against the live S01/S02
  registry, `GAP` requiring a written reason, written rationales required.
- `apply_remediations()` rejects any effect that would *raise* a level
  and any effect naming an unknown risk.
- `seed_demo()` is deterministic and idempotent; the web seed endpoints
  take no user input.

## 3. SQL safety

Parameterized queries only (no string-interpolated SQL). The one dynamic
table name (`DELETE FROM {table}` in `seed_demo`) iterates a hardcoded
tuple of N02 table names — not user input. Migration SQL is static DDL.

## 4. Money handling

Remediation costs are INTEGER cents in the DB and `Decimal` in Python
(`Decimal(cents)/100`, quantized to 2 dp) — no float money math. All
costs/efforts are labeled "synthetic estimate".

## 5. Audit trail

Web seeding emits a structured log line via `log_system_event("n02.seeded",
summary)` — identifiers and counts only, no sensitive content.

## 6. What N02 does NOT do

- No network calls, no subprocesses, no file I/O beyond the SQLite DB.
- No authentication/authorization surface of its own: the workbook is
  read-mostly demo content behind the portfolio app's existing surface.
- No assessment of any real system; the module cannot be pointed at one
  (there is nothing to point — it only ever scores its synthetic fixture).

## 7. Residual risk of the project itself

The honest risk is misinterpretation: someone treating illustrative
scores as an audit opinion. Mitigations: the banner in the module
docstring, the README, every web page, every API response, and the
residual-risk memo; REQUIREMENTS.md §14 non-goals; EVIDENCE_MATRIX.md
"deliberately NOT claimed".
