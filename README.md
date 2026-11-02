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
| `py/reproduction/`, `ts/reproduction/` | The INC-1042 reproduction tests: a behavior contract over the frozen traces (Act 2) |
| `incidents/INC-1042/` | The incident request, both OTLP/JSON traces, their expected span structure and a corrected trace with one refund |
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

## Act 2: a behavior contract catches the double refund

The Act 1 tests check what the agent said. A behavior contract checks what it did. The rule INC-1042 broke is "refund each order at most once", which attest states over the trace's tool calls:

```python
expect(trace).tool_cardinality("issue_refund", per="order_id", at_most=1)
```

```typescript
attestExpect(trace).toolCardinality("issue_refund", { per: "order_id", atMost: 1 });
```

The contract counts `issue_refund` calls per `order_id` argument. A retried call counts again, so the incident traces report:

```text
hard_fail  issue_refund called 2× for order_id=O-1042 (max 1)
```

The output-only tests missed this because the reply never changed: both refunds went through, and the agent told the customer about one of them. The violation is in the tool calls, which only the trace records.

[`py/reproduction/`](py/reproduction/test_inc_1042.py) and [`ts/reproduction/`](ts/reproduction/inc-1042.test.ts) hold the reproduction tests for [issue #2](https://github.com/attest-framework/refund-desk/issues/2). They never run the agent. Each one loads the frozen traces in `incidents/INC-1042/`, converts them through attest's OTel adapter (the engine's `trace convert`) and runs the contract with `inspect()`, which returns the verdict without failing the test. The tests assert that:

- the contract reports exactly `issue_refund called 2× for order_id=O-1042 (max 1)` on `trace.py.otlp.json` and `trace.ts.otlp.json`;
- the same contract passes on `corrected.otlp.json`, a trace of the same request with one refund.

These tests stay green permanently, including after the fix: they prove the contract catches this bug, not that today's agent is correct. Contracts run in the engine with no model calls, so they cost nothing and give the same verdict on every run. See attest's [behavior contracts guide](https://github.com/attest-framework/attest/blob/main/docs/guides/behavior-contracts.md) for the other contracts: forbidden tools, trajectories, ordering, cycles, failure streaks and argument predicates.

`make check` runs them after the agent tests. Behavior contracts ship in attest 1.0.0-rc.2, so they run on the edge channel (`make check CHANNEL=edge`, and in the edge CI job). On `CHANNEL=released`, `make check` prints `skipping the INC-1042 reproduction tests` until a release with contracts is verified; on `CHANNEL=edge`, an attest without them fails `make check`.

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

## Flaky model: statistical verdicts and a judge budget

One run of a non-deterministic agent cannot show that a change made it worse. `make flaky` starts the scripted model server with `--flaky P --seed 42`, which fails a seeded fraction P of chat requests with HTTP 500, and runs `test_refund_reply_confirms_amount` as 20 fixed trials (`pytest --attest-trials=20`). The agent's OpenAI client retries a failed request twice, so a trial fails when one model call fails three times in a row. [`flaky.policy.yaml`](flaky.policy.yaml) compares each assertion's pass rate with a pinned baseline (two-sided 95% Wilson interval, tolerance 0.05):

| Run | Trials passed | 95% Wilson interval | Verdict | Policy exit |
|---|---|---|---|---|
| `--flaky 0.1`, pinned as baseline `flaky-0.1` | 20/20 | | | |
| `--flaky 0.2` | 19/20 | [0.764, 0.991] | `inconclusive`: straddles the line at 0.95 | 2 |
| `--flaky 0.6` | 7/20 | [0.181, 0.567] | `regressed`: below the line | 1 |

`inconclusive` means 20 trials cannot separate 0.2 from 0.1 at this confidence; the answer is more trials, not a rerun until the verdict changes. The seed fixes which requests fail, so every rerun prints the same counts.

The last case shows the judge budget. It runs the test file once with `ATTEST_MAX_JUDGE_CALLS=1` and an empty judge cache. Two tests ask the scripted judge different questions: the first reserves the one call and is served, the second cannot reserve, is never sent, and is `not_evaluated: budget_exhausted`. The model server counts one judge request, the run summary reports `1 calls refused by budget`, and the policy warns (exit 2). Repeated identical questions are answered from the judge cache, so the 20-trial runs above reach the judge at most once.

`make flaky` exits 0 only when the trial counts, verdicts, policy exit codes, judge request counts and `not_evaluated` reasons above match; reports and model server counters are written to `reports/flaky/`. Trials, the regression rule and judge budgets ship in attest 1.0.0-rc.2, so it runs on the edge channel (`make flaky CHANNEL=edge`, and in the edge CI job). On `CHANNEL=released` it stops with `make flaky needs attest >= 1.0.0-rc.2`. See attest's [statistical verdicts guide](https://github.com/attest-framework/attest/blob/main/docs/guides/statistical-verdicts.md).

## License

[Apache-2.0](LICENSE)
