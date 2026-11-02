# Refund Desk

> **Synthetic.** Everything in this repository is invented to demonstrate [attest](https://github.com/attest-framework/attest): the company, the customers, the orders, the payments and the incidents. No real customer or payment data is used, and no paid model API is called.

Refund Desk is a small customer-support agent, written in Python and TypeScript, that looks up orders, issues refunds and notifies customers. It runs against a scripted OpenAI-compatible model server and a fake payments API, so every run is free and reproducible.

## Role of this repository

| Repo | Role | Tracks |
|---|---|---|
| [`attest-examples`](https://github.com/attest-framework/attest-examples) | One small, copyable example per feature or framework | Latest published release |
| `refund-desk` (this repo) | One end-to-end story: incident → reproduction → fix → blocked regression | attest `main` until 1.0.0, then 1.0.x |

Start with `attest-examples` to copy a working setup for your framework. Read this repository to follow one incident from the first report to a merge gate that blocks its regression.

## Run it

Requires [uv](https://docs.astral.sh/uv/), Node.js 22+ and [pnpm](https://pnpm.io/). No API key.

```bash
make setup      # uv sync (py/) and pnpm install (ts/), with attest pinned to the latest verified release
make incident   # reproduce INC-1042 in Python and TypeScript, print the payments ledger, regenerate the traces
make check      # lint, type-check and run the attest tests in both languages
```

| Path | What it is |
|---|---|
| `py/`, `ts/` | The Refund Desk agent: an OpenAI chat-completions tool loop with `lookup_order`, `issue_refund` and `notify_customer`, plus its pytest / Vitest attest tests |
| `agent-spec/` | System prompt and tool schemas shared by both agents |
| `model-server/` | Scripted OpenAI-compatible server: replies per scenario, a seeded `--flaky P` fault, scripted judge replies for attest's layer 6, and a request counter at `/_admin/stats` |
| `payments/` | Fake payments API with an in-memory ledger and fault scripts (`payments/faults/`) |
| `incidents/INC-1042/` | The incident request, both OTLP/JSON traces and their expected span structure |
| `stack.mk` | Ports, URLs and the placeholder keys the scripted server ignores |

`make incident` and `make check` start both servers through `scripts/stack.py` and stop them afterwards.

### Channels

attest is installed from one of two channels:

| Channel | attest | Runs in CI |
|---|---|---|
| `CHANNEL=released` (default) | The published packages pinned in `py/uv.lock` and `ts/package.json` | On the latest `verified-<version>` tag |
| `CHANNEL=edge` | attest `main`, built from source | On every push and pull request |

Run the edge channel locally from an attest checkout:

```bash
make edge-artifacts ATTEST_SRC=../attest
make setup CHANNEL=edge && make check CHANNEL=edge
```

### Pointing the agent at a real model

The agents read `MODEL_BASE_URL`, `MODEL_NAME` and `MODEL_API_KEY` from the environment, and any exported value overrides `stack.mk`. Any OpenAI-compatible chat-completions endpoint works. The repository never does this: CI and every `make` target use the scripted server, and a real model will not follow the incident script.

## Act 1: the incident

[Issue #2](https://github.com/attest-framework/refund-desk/issues/2) reports INC-1042 (synthetic): the payments API timed out after committing a refund, the agent called `issue_refund` again without an idempotency key, and the customer was refunded twice.

`make incident` replays it with the `inc-1042` fault script. The first refund commits and its response is held past the agent's 1.2 s timeout, so the agent retries and the ledger shows two refunds for O-1042:

```text
Payments ledger after the py agent (synthetic)
  refund   order      amount  idempotency key  committed_at
  R-0001   O-1042     $84.00  -                2026-11-02T07:09:46.362Z
  R-0002   O-1042     $84.00  -                2026-11-02T07:09:47.568Z
  O-1042: 2 refunds, $168.00 total (order amount $84.00)
```

`make check` still passes in both languages. Each test asserts only the reply: it contains `refund of $84.00`, does not mention `$168.00`, and the judge agrees it confirms the refund. The reply is exactly what the customer was told, "Your refund of $84.00 has been processed.", so every assertion holds. None of them looks at what the agent did: how many times it called `issue_refund`, with which arguments, or what the ledger holds afterwards. The double refund happens in the tool calls and the payments ledger, and the tests never look there.

The traces in `incidents/INC-1042/` record those tool calls. Later acts use them to turn the incident into a failing test, fix the agent and block the regression.

| Act | What it shows |
|---|---|
| 1 | The incident happens; output-only tests stay green |
| 2 | A behavior contract over the frozen trace detects the double refund |
| 3 | Captured fixture: the real agent replays with zero model calls and the simulated world shows two refunds |
| 4 | The fix merges with zero live model calls; a regression pull request is blocked with an annotation |
| 5 | A coding agent drafts the contract; mutation testing scores it |
| 6 | Identical verdicts in TypeScript; a viewer artifact on the regression pull request |

## Trace doctor

`make doctor` runs `attest trace check` on both committed INC-1042 traces. It exits non-zero when a trace has structural errors (orphan or unpaired spans, reported by span id) and prints what evidence the trace lacks:

```text
trace check incidents/INC-1042/trace.py.otlp.json
trace 29478f3e0a07ff5725faf3112a8e3663: 10 spans, attest trace schema v2
steps: 5 llm_call, 4 tool_call; 1 turn, 0 handoffs, 1 retry
structure: OK
coverage: missing evidence
  cost     5 of 5 llm_call spans lack gen_ai.usage.cost
  content  5 of 5 llm_call spans lack gen_ai.input.messages / gen_ai.output.messages
```

The retry is the second `issue_refund` call, made after the first one timed out at 1.2 s: the double refund. The traces record no cost and no message content, so an assertion over either, such as `cost_under(0.05)`, reports not evaluated (`missing_evidence`) instead of passing. The TypeScript trace reports the same counts.

`trace check` ships in attest 1.0.0-rc.2, so `make doctor` runs on the edge channel (`make doctor CHANNEL=edge`, and in the edge CI job). On `CHANNEL=released` it stops with `make doctor needs attest >= 1.0.0-rc.2` until a release with the command is verified.

## License

[Apache-2.0](LICENSE)
