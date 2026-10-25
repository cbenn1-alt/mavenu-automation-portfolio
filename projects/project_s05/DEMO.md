# S05 — Demo Script

> **⚠ EDUCATIONAL DEMO ONLY — NOT PRODUCTION CRYPTOGRAPHY.**
> All data below is synthetic.

## 5-minute walkthrough (for a hiring manager)

**0:00 — The problem (30s).** "Developers copy-paste crypto and get it
subtly wrong — ECB mode, hardcoded IVs, home-rolled encryption. This
project shows the *correct* patterns, each standing next to the classic
mistake it prevents."

**0:30 — Known answers (60s).** Open `/api/crypto/hash`, hash `616263`
("abc") → `ba7816bf…20015ad`, the NIST vector. Then
`/api/crypto/pitfalls` — the 8-entry catalog. Point at P-HOMEROLL: "we
invented nothing; the one teaching construction is bannered EDUCATIONAL
with a pointer to audited libraries."

**1:30 — Encrypt → tamper → fail closed (90s).** `POST
/api/crypto/encrypt` with `{"plaintext_hex":"68656c6c6f"}` — note the
fresh synthetic key and the envelope fields (nonce, ciphertext, tag).
Flip one hex digit of the ciphertext, `POST /api/crypto/decrypt` →
422 `auth_failed`. "100% tamper detection — flipped bit, modified tag,
wrong key, all raise; nothing ever decrypts garbage."

**3:00 — Key lifecycle (90s).** `/project_s05/keymgmt` → "Run guided
demo": sign → verify → tamper-check fails → rotate (old signature still
verifies with the retired key) → destroy (wiped + tombstoned) → destroyed
key refuses with `KeyDestroyedError`. "Rotation without stranding data;
destruction that actually destroys."

**4:30 — Honest boundaries (30s).** "Asymmetric signatures and
certificate validation are documented as design patterns — design-only,
not code, because stdlib has no public-key tooling and we invent none.
The MAC workflow is honestly labeled symmetric. Nothing here is
production crypto; the README forbids production use without expert
review."

## Click path

1. `/project_s05` → read the banner table (REAL / EDUCATIONAL-ONLY /
   DESIGN-ONLY / SYNTHETIC / NOT claimed).
2. `/project_s05/primitives` → the five correct-use summaries.
3. `/project_s05/pitfalls` → the 8 classic mistakes with "avoided by".
4. `/project_s05/keymgmt` → "Run guided demo" → watch the 8-step sign
   workflow and the encrypt→tamper→reject narrative.

## One-liner (Python)

```bash
cd ~/workspace/mavenu-portfolio && .venv/bin/python - <<'EOF'
from mavenu import crypto_demo as c
key = c.generate_key()                       # secrets, 256-bit
env = c.encrypt(key, b"synthetic payload")   # encrypt-then-MAC (educational)
assert c.decrypt(key, env) == b"synthetic payload"
tampered = dict(env); b = bytearray(bytes.fromhex(tampered["ciphertext"])); b[0] ^= 1
tampered["ciphertext"] = bytes(b).hex()
try:
    c.decrypt(key, tampered)
except c.TamperDetectedError:
    print("tamper rejected — fails closed")
EOF
```
