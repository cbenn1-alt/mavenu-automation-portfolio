# Q10 — Webhook Integration Hub: Demo Script

**Time:** ~5 minutes. **Cost:** $0. **Prereqs:** `.venv`, port 8080 free.
Everything below uses synthetic data and the documented test-only secret.

## 1. Start the app and open the dashboard (30s)

```bash
cd ~/workspace/mavenu-portfolio
.venv/bin/python run.py
# open http://localhost:8080/project_q10
```

Click **"Seed demo routing rules"**. The dashboard now shows three rules.

## 2. Send a signed lead event (60s)

```bash
BODY='{"source":"demo-form","event_type":"lead.created","event_id":"demo-001","payload":{"name":"Sample Lead","amount":1500}}'
SIG=$(python3 -c "import hmac,hashlib,sys; print('sha256='+hmac.new(b'test-secret-demo-form-001', sys.argv[1].encode(), hashlib.sha256).hexdigest())" "$BODY")
curl -s -X POST http://localhost:8080/api/webhooks/events \
  -H 'Content-Type: application/json' \
  -H "X-Webhook-Signature: $SIG" -d "$BODY" | python3 -m json.tool
```

Point out in the 201 response: `verified: true`, and `routing.matched_rules`
= `form-leads-to-crm` + `high-value-leads-to-sheet` (the amount ≥ 1000
condition fired), each with its actions.

## 3. Show the lineage (30s)

```bash
curl -s http://localhost:8080/api/webhooks/events/EVT-000001 | python3 -c "
import json,sys; d=json.load(sys.stdin)
print([(l['from_state'],l['to_state']) for l in d['lineage']])"
# [(None, 'received'), ('received', 'routed'), ('routed', 'queued')]
```

Reload `/project_q10` — the event is `queued`, deliveries pending.

## 4. Run delivery (30s)

```bash
curl -s -X POST http://localhost:8080/api/webhooks/deliver/run
# {"delivery_loop": {"attempted": 2, "delivered": 2, ...}}
```

Reload the dashboard: event is `delivered`, lineage shows the full chain.
Emphasize: the "endpoints" are in-process stubs — no network, no SaaS.

## 5. Show strict-mode rejection (45s)

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:8080/api/webhooks/events \
  -H 'Content-Type: application/json' \
  -d '{"source":"demo-form","event_type":"lead.created","event_id":"evil-1","payload":{}}'
# 401
```

No signature → 401, stored as `rejected`, never routed. "This is what a
forged webhook looks like to the hub."

## 6. Show dry-run (60s)

```bash
curl -s -X POST http://localhost:8080/api/webhooks/routes/dry-run \
  -H 'Content-Type: application/json' \
  -d '{"source":"demo-form","event_type":"lead.created","event_id":"dry-1","payload":{"amount":50}}' \
  | python3 -m json.tool
```

`would_forward_to: ["stub:crm-sink"]` only — the high-value rule doesn't
fire at amount 50. "Every rule is proven before it touches anything real."

## 7. Show the dead letter + replay (60s)

Create a rule forwarding to a bogus endpoint, send an event, run delivery,
then open `/project_q10/dead-letters`:

```bash
curl -s -X POST http://localhost:8080/api/webhooks/routes \
  -H 'Content-Type: application/json' \
  -d '{"name":"demo-broken","event_type":"demo.broken","actions":[{"type":"forward","endpoint":"stub:ghost"}]}'
BODY='{"source":"demo-form","event_type":"demo.broken","event_id":"demo-002","payload":{}}'
SIG=$(python3 -c "import hmac,hashlib,sys; print('sha256='+hmac.new(b'test-secret-demo-form-001', sys.argv[1].encode(), hashlib.sha256).hexdigest())" "$BODY")
curl -s -X POST http://localhost:8080/api/webhooks/events -H 'Content-Type: application/json' -H "X-Webhook-Signature: $SIG" -d "$BODY" >/dev/null
curl -s -X POST http://localhost:8080/api/webhooks/deliver/run >/dev/null
```

Dead letter reason: `unknown_endpoint`. Replay it:

```bash
ID=$(curl -s http://localhost:8080/api/webhooks/dead-letters | python3 -c "
import json,sys; ds=[d for d in json.load(sys.stdin)['dead_letters'] if d['event_id']=='demo-002']; print(ds[0]['id'])")
curl -s -X POST http://localhost:8080/api/webhooks/dead-letters/$ID/replay | python3 -m json.tool
```

Clean up the demo rule afterwards:
`curl -s -X DELETE http://localhost:8080/api/webhooks/routes/<id>`.

## Talking points

- **Verify → route → deliver → audit** is the whole architecture; the
  append-only lineage log *is* the system of record.
- **Dry-run parity** is tested, not claimed — the demo shows it live.
- **Honest boundaries**: test-only secrets, stub endpoints, synthetic
  data — all labeled. A real deployment swaps in real secrets
  (`MAVENU_WEBHOOK_SECRETS`), real delivery adapters, and a scheduler
  for the loop; the code is structured for exactly that swap.
