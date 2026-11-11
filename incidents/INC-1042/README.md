# INC-1042: Customer refunded twice after payment gateway timeout

> Synthetic incident created to demonstrate attest. No real customer or payment data.

Reported in [issue #2](https://github.com/attest-framework/refund-desk/issues/2).

| File | Content |
|---|---|
| `request.json` | The customer message. The fault is in `world/payments-inc-1042.world.yaml` |
| `trace.py.otlp.json` | OTLP/JSON trace of the Python agent handling the request |
| `trace.ts.otlp.json` | OTLP/JSON trace of the TypeScript agent handling the request |
| `span-structure.txt` | Span names, kinds, statuses and attributes both traces must have; ids and timestamps are left out |
| `corrected.otlp.json` | OTLP/JSON trace of the Python agent handling the same customer message without the payments fault (it predates the world): one `issue_refund` for O-1042. The reproduction tests (`py/reproduction/`, `ts/reproduction/`) check that the INC-1042 contract passes on it |

These files are frozen evidence of the original incident. `make incident` runs the fixed agents, writes new traces to `.stack/incident-traces/` and compares their structure against `scripts/span-structure.txt`, not this directory's historical snapshot. After an intended agent change, `make incident UPDATE_STRUCTURE=1` updates `scripts/span-structure.txt`; it never regenerates the frozen incident traces.
