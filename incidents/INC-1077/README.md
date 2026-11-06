# INC-1077: Over-refund after partial refund; confirmation sent to another customer

> Synthetic incident created to demonstrate attest. No real customer or payment data.

After the system prompt change that enabled partial refunds (`agent-spec/v2/`), Refund Desk handled a conversation about order O-2077 ($126.00, customer C-0744). The customer asked for a shipping-only refund ($12.00), then for the whole order. The agent issued $12.00 and then $126.00 ($138.00 total), and sent the confirmation to customer C-0311, whose order O-1042 it had looked up earlier in the same session.

| File | Content |
|---|---|
| `request.json` | The support session, as one customer message. There is no payments fault: the world is `world/payments-inc-1077.world.yaml` |
| `trace.py.otlp.json` | OTLP/JSON trace of the Python agent (agent-spec v2) handling the request, as it ran in the incident |
| `trace.ts.otlp.json` | OTLP/JSON trace of the TypeScript agent (agent-spec v2) handling the request, as it ran in the incident |
| `fixture.py.attest.json`, `fixture.ts.attest.json` | The incident run as `attest capture` fixtures; the `inspect()` tests in `py/tests/attest/test_inc_1077.py` and `ts/tests/attest/inc-1077.test.ts` read them |
| `span-structure.txt` | Span names, kinds, statuses and attributes both incident traces have; ids and timestamps are left out |

The files in this directory are frozen: they record the agent that shipped, and nothing regenerates them.

Ledger the incident left:

```text
  refund   order      amount  idempotency key
  R-0001   O-2077     $12.00  a734c51152a3b7a0
  R-0002   O-2077    $126.00  fc02935f8660cf2b
  O-2077: 2 refunds, $138.00 total (order amount $126.00)
  N-0001   O-2077   to C-0311 (email)
```

## The fix

Both agents (`py/src/refund_desk/agent.py`, `ts/src/agent.ts`) now:

- sum the order's existing refunds (the refunds list filtered by `order_id`) before refunding and cap a refund to what is left of the order amount, so the refunded total per order never exceeds it; an order with nothing left refuses with `order_fully_refunded`. A refund of an amount the order already has stays an idempotent retry (INC-1042). A capped result carries `requested_amount_cents`.
- send the confirmation to the customer on the order's record, ignoring the `customer_id` the model passes.

The scripted model server is unchanged, so the same session now leaves (`make incident-1077 CHANNEL=edge`):

```text
  refund   order      amount  idempotency key
  R-0001   O-2077     $12.00  a734c51152a3b7a0
  R-0002   O-2077    $114.00  f7edd604c8cce4ac
  O-2077: 2 refunds, $126.00 total (order amount $126.00)
  N-0001   O-2077   to C-0744 (email)
```

`make incident-1077` runs the fixed agents, writes their traces to `.stack/incident-1077-traces/` and fails when the ledger differs from this one or when either trace's structure differs from `scripts/span-structure-1077.txt`. After an intended agent change, run `make incident-1077 UPDATE_STRUCTURE=1` and commit the new structure.

The scripted model server plays the INC-1077 session (`CONVERSATIONS` in `model-server/server.py`, selected by the order id in the customer message). The suite under test stays on agent-spec v1: raising the INC-1042 cardinality contract to at most 2 refunds per order belongs to the partial-refund change that moves the suite to v2.
