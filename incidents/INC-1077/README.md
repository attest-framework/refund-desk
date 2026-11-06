# INC-1077: Over-refund after partial refund; confirmation sent to another customer

> Synthetic incident created to demonstrate attest. No real customer or payment data.

After the system prompt change that enabled partial refunds (`agent-spec/v2/`), Refund Desk handled a conversation about order O-2077 ($126.00, customer C-0744). The customer asked for a shipping-only refund ($12.00), then for the whole order. The agent issued $12.00 and then $126.00 ($138.00 total), and sent the confirmation to customer C-0311, whose order O-1042 it had looked up earlier in the same session.

| File | Content |
|---|---|
| `request.json` | The support session, as one customer message. There is no payments fault: the world is `world/payments-inc-1077.world.yaml` |
| `trace.py.otlp.json` | OTLP/JSON trace of the Python agent (agent-spec v2) handling the request |
| `trace.ts.otlp.json` | OTLP/JSON trace of the TypeScript agent (agent-spec v2) handling the request |
| `span-structure.txt` | Span names, kinds, statuses and attributes both traces must have; ids and timestamps are left out |

Ledger the incident leaves (`make incident-1077 CHANNEL=edge`):

```text
  refund   order      amount  idempotency key
  R-0001   O-2077     $12.00  a734c51152a3b7a0
  R-0002   O-2077    $126.00  fc02935f8660cf2b
  O-2077: 2 refunds, $138.00 total (order amount $126.00)
  N-0001   O-2077   to C-0311 (email)
```

`make incident-1077` regenerates both traces in this directory and fails when the ledger differs from the incident's or when either trace's structure differs from `span-structure.txt`. After an intended agent change, run `make incident-1077 UPDATE_STRUCTURE=1` and commit the new structure.

The scripted model server plays the buggy agent behavior (`CONVERSATIONS` in `model-server/server.py`, selected by the order id in the customer message). The suite under test stays on agent-spec v1: raising the INC-1042 cardinality contract to at most 2 refunds per order belongs to the partial-refund change that moves the suite to v2.
