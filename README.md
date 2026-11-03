# Refund Desk

> **Synthetic.** Everything in this repository is invented to demonstrate [attest](https://github.com/attest-framework/attest): the company, the customers, the orders, the payments and the incidents. No real customer or payment data is used, and no paid model API is called.

Refund Desk is a small customer-support agent, written in Python and TypeScript, that looks up orders, issues refunds and notifies customers. It runs against a scripted OpenAI-compatible model server and a payments API that is an [attest world](https://github.com/attest-framework/attest/blob/main/docs/guides/world-fixtures.md), so every run is free and reproducible.

## Role of this repository

| Repo | Role | Tracks |
|---|---|---|
| [`attest-examples`](https://github.com/attest-framework/attest-examples) | One small, copyable example per feature or framework | Latest published release |
| `refund-desk` (this repo) | One end-to-end story: incident → reproduction → fix → blocked regression | attest `main` until 1.0.0, then 1.0.x |

Start with `attest-examples` to copy a working setup for your framework. Read this repository to follow one incident from the first report to a merge gate that blocks its regression.

## Run it

Requires [uv](https://docs.astral.sh/uv/), Node.js 22+ and [pnpm](https://pnpm.io/). No API key.

```bash
make edge-artifacts ATTEST_SRC=<attest checkout>   # build attest from source (the payments world needs attest >= 1.0.0-rc.3)
make setup CHANNEL=edge      # uv sync (py/) and pnpm install (ts/), with attest from source
make incident CHANNEL=edge   # run the incident request in Python and TypeScript, print the payments ledger, require one refund
make check CHANNEL=edge      # lint, type-check and run the attest tests in both languages
```

| Path | What it is |
|---|---|
| `py/`, `ts/` | The Refund Desk agent: an OpenAI chat-completions tool loop with `lookup_order`, `issue_refund` and `notify_customer`, plus its pytest / Vitest attest tests |
| `agent-spec/` | System prompt and tool schemas shared by both agents |
| `model-server/` | Scripted OpenAI-compatible server: replies per scenario, a seeded `--flaky P` fault, scripted judge replies for attest's layer 6, and a request counter at `/_admin/stats` |
| `world/` | The payments API as attest worlds (`world.yaml`): `payments.world.yaml` is healthy, `payments-inc-1042.world.yaml` adds the INC-1042 fault. Every run, test and capture hosts a fresh one. A world does not validate refunds: any order id and amount commit, so the agents' 404/422 branches in `issue_refund` are no longer reached |
| `py/reproduction/`, `ts/reproduction/` | The INC-1042 reproduction tests: a behavior contract over the frozen traces (Act 2) |
| `incidents/INC-1042/` | The incident as it shipped, frozen: the request, both OTLP/JSON traces of the double-refund agent, their span structure and a corrected trace with one refund |
| `py/tests/attest/`, `ts/tests/attest/` | The captured INC-1042 fixture and its drafted reproduction test per language (Act 3a) |
| `py/tests/replay/`, `ts/tests/replay/` | The INC-1042 replay tests: today's agent against the captured fixture (Act 3b) |
| `scripts/span-structure.txt` | The span structure of the current agent's incident run, which `make incident` compares against |
| `stack.mk` | Ports, URLs and the planted fake `OPENAI_API_KEY` the scripted server ignores |

`make incident` and `make check` start the scripted model server through `scripts/stack.py` and stop it afterwards; each test, capture or incident run hosts its own payments world.

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

The agents read `OPENAI_BASE_URL`, `MODEL_NAME` and `OPENAI_API_KEY` from the environment, and any exported value overrides `stack.mk`. Any OpenAI-compatible chat-completions endpoint works. The repository never does this: CI and every `make` target use the scripted server, and a real model will not follow the incident script.

## Act 1: the incident

[Issue #2](https://github.com/attest-framework/refund-desk/issues/2) reports INC-1042 (synthetic): the payments API timed out after committing a refund, the agent called `issue_refund` again without an idempotency key, and the customer was refunded twice.

The agent as it shipped, replayed in a fresh `world/payments-inc-1042.world.yaml` world, reproduces it. The world's `timeout_after_commit` fault fires on the first refund request: the refund commits and its response is held until the agent's 1.2 s timeout, so the agent retried and the world's state showed two refunds for O-1042:

```text
Payments ledger after the py agent (synthetic)
  refund   order      amount  idempotency key
  R-0001   O-1042     $84.00  -
  R-0002   O-1042     $84.00  -
  O-1042: 2 refunds, $168.00 total (order amount $84.00)
```

`make check` passed in both languages. Each test asserts only the reply: it contains `refund of $84.00`, does not mention `$168.00`, and the judge agrees it confirms the refund. The reply is exactly what the customer was told, "Your refund of $84.00 has been processed.", so every assertion holds. None of them looks at what the agent did: how many times it called `issue_refund`, with which arguments, or what the ledger holds afterwards. The double refund happens in the tool calls and the payments ledger, and the tests never look there.

The traces in `incidents/INC-1042/` record those tool calls. They are frozen: the fix in Act 4 does not touch them, and `make incident` writes its own traces to `.stack/incident-traces/`. Later acts turn the incident into a failing test, fix the agent and block the regression.

| Act | What it shows |
|---|---|
| 1 | The incident happens; output-only tests stay green |
| 2 | A behavior contract over the frozen trace detects the double refund |
| 3a | `attest capture` turns the incident run into a verified fixture with the secrets removed |
| 3b | Replay: the real agent code runs against the fixture with zero model calls, and the double refund reproduces as a failing effect contract |
| 4 | The fix (idempotency key plus a status check) merges with zero live model calls; a regression pull request is blocked with an annotation |
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

These tests stay green permanently, including after the fix: they prove the contract catches this bug in the frozen traces, not that today's agent is correct. Contracts run in the engine with no model calls, so they cost nothing and give the same verdict on every run. See attest's [behavior contracts guide](https://github.com/attest-framework/attest/blob/main/docs/guides/behavior-contracts.md) for the other contracts: forbidden tools, trajectories, ordering, cycles, failure streaks and argument predicates.

`make check` runs them after the agent tests. Behavior contracts ship in attest 1.0.0-rc.2, so they run on the edge channel (`make check CHANNEL=edge`, and in the edge CI job). The payments API is an attest world, so `make check` needs attest >= 1.0.0-rc.3 on every channel: on `CHANNEL=released` it stops with that message until a release with `world` is verified.

## Act 3a: capture

Act 2 read a frozen trace. `attest capture` makes the run itself the input: it runs the incident, records the trace and every model call, removes secrets, templates volatile values, drafts contracts and checks them against the run.

```bash
make setup CHANNEL=edge
make capture CHANNEL=edge          # one capture per language, with the stack up
make capture-check CHANNEL=edge    # re-capture, compare bytes, check redaction and the trace
```

`make capture` runs, in `py/` and in `ts/`, where the fixture does not exist yet:

```bash
attest capture --name inc-1042 -- <the incident command for that language>
```

`make capture` removes the existing fixture and captures again with `--world world/payments-inc-1042.world.yaml` (`attest capture --refresh` refuses a fixture that has a world section). `OPENAI_BASE_URL` in the capture's environment is the scripted model server, so the proxy forwards to it; the agent gets the proxy's URL instead. Each agent builds its client from `OPENAI_BASE_URL` and `OPENAI_API_KEY`, and exports its spans over OTLP/HTTP to `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` when capture sets it, next to the OTLP/JSON file. The fixtures land in `py/tests/attest/fixtures/inc-1042.attest.json` and `ts/tests/attest/fixtures/inc-1042.attest.json`; capture drafts `py/tests/attest/test_inc_1042.py` and `ts/tests/attest/inc-1042.test.ts` next to them. Those two files are committed reproduction tests: `inspect()` runs the drafted contracts over the fixture's trace, and the test passes because `cardinality-issue_refund-per-order_id` reports the double refund. `make check` runs them outside the policy report, since a reproduction's hard failure is expected.

```text
capture inc-1042: tests/attest/fixtures/inc-1042.attest.json
  trace: 4 llm_call, 3 tool_call; trace check OK
  exchanges: 4 recorded (openai chat_completions ×4)
  contracts:
    pass  tools-called                               trajectory (superset) matches [lookup_order issue_refund notify_customer]
    pass  cardinality-lookup_order-per-order_id      lookup_order within max 1 for each of 1 order_id value(s)
    pass  cardinality-issue_refund-per-order_id      issue_refund within max 1 for each of 1 order_id value(s)
    ...
  verified: every drafted contract passes
```

The fixture was first captured from the agent as it shipped, where the same capture needed `--expect-fail`: `issue_refund` ran twice for O-1042 and `cardinality-issue_refund-per-order_id` was the recorded expected failure. The fix re-recorded both fixtures from the fixed agent, so the flag is gone; the double-refund trace lives on in `incidents/INC-1042/`.

The demo plants two secrets so the redaction has something to catch: a fake key in `OPENAI_API_KEY` (`stack.mk`, shaped like a real `sk-` key) and a customer email in `incidents/INC-1042/request.json`. Excerpt of the fixture:

```json
"verification": { "expect_fail": true, "expected_failures": ["cardinality-issue_refund-per-order_id"], "verified": true },
"exchanges": [{
  "api": "chat_completions", "path": "/chat/completions", "provider": "openai",
  "request": { "messages": [ ..., { "content": "Hi, {{email_1}}: O-1042 came damaged. Refund.", "role": "user" } ] },
  "key": { "model": "refund-desk-scripted", "prompt_hash": "sha256:1bf2c172…", "tool_schema_hash": "sha256:85273f44…" }
}],
"world": null
```

The email is `{{email_1}}` in every place it appears. The key is nowhere in the fixture: request headers, which carry it, are never recorded, and any other place it reached would be `[redacted]`. `make capture-check` holds that to account:

| Check | Expected |
|---|---|
| re-capture both languages into a temporary directory and `cmp` with the committed fixtures | byte-identical |
| `attest capture --check-redaction` on each committed fixture | `clean`, with the planted key in the environment |
| `grep` each fixture for the planted key and the email | 0 hits |
| `attest trace check` on each fixture | exit 0 |

The fixture is the input of Act 3b. It holds the five model exchanges with their request keys, so replay can answer the agent's real code from the recording with zero model calls, and the `world` section holds the payments world's final state (the two refunds) and the fault that fired. It is evidence only: replay and the tests start a fresh world from `world/`. A fixture that came from `--from <otlp>` has the trace but no exchanges and cannot replay.

Capture ships after attest 1.0.0-rc.2, so `make capture` and `make capture-check` run on the edge channel. On `CHANNEL=released` they stop with `needs attest >= 1.0.0-rc.3` until a release with the command is verified.

## Act 3b: replay

Capture recorded the model's side of the incident. Replay serves it back: the tests run the current agent code (`refund_desk.agent.run`, `ts/src/agent.ts` `run`) on the INC-1042 request against a fresh payments world with the `inc-1042` fault, exactly as `make incident` does, while a local proxy answers every model request from `tests/attest/fixtures/inc-1042.attest.json`. No model is called and no key is needed.

```bash
make setup CHANNEL=edge
make check CHANNEL=edge            # runs the replay tests last, in both languages
make replay-miss CHANNEL=edge      # the miss message, below
```

`make check` runs both replay tests with strict replay and the egress guard on, with no provider key in the environment (the agent's settings need a non-empty `OPENAI_API_KEY`, so the run sets the placeholder `replay-needs-no-key`):

```bash
pytest tests/replay --attest-replay=strict --attest-egress=block
ATTEST_REPLAY=strict ATTEST_EGRESS=block vitest run --config tests/replay/vitest.config.ts
```

```text
tests/replay/test_inc_1042_replay.py .
attest replay: 4 replayed · 0 live model calls · $0.00
```

Each test asserts the effect contract `count("refunds", equals=1, order_id="O-1042")` with `evaluate()` against the world's final state, and it passes: the fixed agent leaves one refund. Before the fix the same tests failed with `effect violated: 2 refunds for O-1042 (expected 1)` and sat under strict expected-failure markers (`pytest.mark.xfail(strict=True)`, Vitest `it.fails`) that the fix removed. The trace contract on the incident stays in the reproduction tests, which read the frozen traces and stay green for good.

### The fix

Both agents (`Tools.issue_refund` in `py/src/refund_desk/agent.py`, `issueRefund` in `ts/src/agent.ts`) now send an `Idempotency-Key` header, the first 16 hex digits of `sha256("<order_id>:<amount_cents>")`, so a repeat of the same refund is answered with the first one. When the request times out they also read `GET /refunds?order_id=<id>` and, if the payments API committed a refund for that amount, return it as committed instead of reporting `payments_timeout`; the model then never retries. With no committed refund the agent still returns the timeout error.

A live test per language runs the real agent against the scripted model server under the INC-1042 fault and asserts the effect contract (`test_inc_1042_effect_contract_leaves_one_refund`, and its TypeScript twin in `ts/tests/refund-desk.test.ts`). Reverting the agent turns that test red with the message above. Replay reaches the same verdict from the fixture, but a change to the agent's tool results changes its model requests, so the fixtures are re-recorded with `make capture`.

Reproduction tests (Act 2) and the replay tests answer different questions. The reproduction tests read frozen traces and stay green for good: they prove the contract catches the bug. The replay tests run the current agent: they are green because the agent is fixed, and fail if it regresses.

### A changed prompt is a replay miss

A request matches a recording when its model, parameters, prompt and tool schemas are equal. Change any of them and strict replay fails the test instead of guessing. `make replay-miss` appends one sentence to `agent-spec/system-prompt.txt`, runs both replay tests and requires each to fail with the message below, then restores the prompt. CI runs it on the edge job.

```text
replay miss: system prompt changed (hash e1b7b67→5305126); re-record with `attest capture --refresh inc-1042`
```

The hashes are the first seven characters of a hash of the old and new system prompt, so the log shows that it changed without showing the text. After an intended change, `make capture CHANNEL=edge` re-records both fixtures. Replay and worlds ship after attest 1.0.0-rc.2: on `CHANNEL=released`, `make check` stops with `needs attest >= 1.0.0-rc.3`.

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
