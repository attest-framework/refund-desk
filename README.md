# Refund Desk

> **Synthetic.** Everything in this repository is invented to demonstrate [attest](https://github.com/attest-framework/attest): the company, the customers, the orders, the payments and the incidents. No real customer or payment data is used, and no paid model API is called.

Refund Desk is a small customer-support agent, written in Python and TypeScript, that looks up orders, issues refunds and notifies customers. It runs against a scripted OpenAI-compatible model server and a payments API that is an [attest world](https://github.com/attest-framework/attest/blob/main/docs/guides/world-fixtures.md), so every run is free and reproducible.

## Role of this repository

| Repo | Role | Tracks |
|---|---|---|
| [`attest-examples`](https://github.com/attest-framework/attest-examples) | One small, copyable example per feature or framework | Latest published release |
| `refund-desk` (this repo) | One end-to-end story: incident → reproduction → fix → blocked regression | attest 1.1.0-rc.2 (released channel) and attest `main` (edge channel) |

Start with `attest-examples` to copy a working setup for your framework. Read this repository to follow one incident from the first report to a merge gate that blocks its regression.

## From incident to regression test

One incident, followed from the first report to a merge gate that blocks its regression. Requires [uv](https://docs.astral.sh/uv/), Node.js 22+ and [pnpm](https://pnpm.io/). No API key and no model call. The network is used by the package installs of `make setup` and, on a fresh `HOME`, by the one-time download of `attest-engine` from GitHub Releases on the released channel.

```bash
make setup walkthrough
```

`make walkthrough` runs every act below in order on the released attest (`CHANNEL=released`, the default; `make walkthrough CHANNEL=edge` runs attest from source, see [Channels](#channels)), checks the outcome each act promises and prints one line per act. A wrong outcome prints the act, the expected and the actual result and exits 1; every command's log is kept in `reports/walkthrough/`. It takes about two minutes. The unfixed agent comes from a temporary copy of this tree with [`regression/revert-inc-1042-fix.patch`](regression/revert-inc-1042-fix.patch) applied (the change of the regression pull requests [#12](https://github.com/attest-framework/refund-desk/pull/12) and [#22](https://github.com/attest-framework/refund-desk/pull/22)) and with the fixtures recorded before the fix restored from [`regression/pre-fix-fixtures/`](regression/pre-fix-fixtures/), so the working tree is never modified.

```text
walkthrough on the released channel (logs in reports/walkthrough/)
Act 1: output-only tests pass; both incident traces show 2 refunds ✓
Act 2: trace check passes; the contract reports issue_refund called 2× ✓
Act 3a: capture verifies INC-1042: byte-identical, 0 planted secrets, tests pass ✓
Act 3b: strict replay reproduces INC-1042: 'effect violated: 2 refunds for O-1042', 0 misses, 0 live calls ✓
Act 4a: the fix passes: 0 failed, 0 live model calls · $0.00 ✓
Act 4b: the regression is blocked: tests/refund-desk.test.ts:88 'effect violated: 2 refunds for O-1042 (expected 1)', policy exit 1 ✓
Act 5a: mutation score 0.00 → 0.34: the Act 1 tests block, the contracts pass ✓
Act 5b: the MCP-drafted contract test passes ✓
Act 6: viewer page written: 10 tests, 0 failed, 10 traces ✓
Act 7: outage warns: not evaluated: provider_unavailable, policy exit 2 ✓
walkthrough: every act ended as expected
```


| Act | What it shows |
|---|---|
| 1 | The incident happens; output-only tests stay green |
| 2 | A behavior contract over the frozen trace detects the double refund |
| 3a | `attest capture` turns the incident run into a verified fixture with the secrets removed |
| 3b | Replay: the real agent code runs against the recorded incident with zero model calls, and the double refund reproduces as a failing effect contract (the walkthrough shows it against the fixtures recorded before the fix) |
| 4 | The fix (idempotency key plus a status check) merges with zero live model calls; a regression pull request is blocked with an annotation |
| 5 | A coding agent drafts the contract; mutation testing scores it |
| 6 | Identical verdicts in TypeScript; a viewer artifact on the regression pull request |
| 7 | The judge provider is unreachable; the run reports not evaluated (`provider_unavailable`) and the policy warns instead of blocking |

### Act 1: the incident

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

### Act 2: a behavior contract catches the double refund

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

`make check` runs them after the agent tests. The payments API is an attest world, so `make check` runs on attest 1.1.0-rc.2 and on attest `main`. The Act 5 step (`check-mutate`) uses `attest mutate`, and the `outage` act closes the run.

### Act 3a: capture

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

`make capture` removes the existing fixture and captures again with `--world world/payments-inc-1042.world.yaml` (`attest capture --refresh` refuses a fixture that has a world section). `OPENAI_BASE_URL` in the capture's environment is the scripted model server, so the proxy forwards to it; the agent gets the proxy's URL instead. Each agent builds its client from `OPENAI_BASE_URL` and `OPENAI_API_KEY`, and exports its spans over OTLP/HTTP to `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` when capture sets it, next to the OTLP/JSON file. The fixtures land in `py/tests/attest/fixtures/inc-1042.attest.json` and `ts/tests/attest/fixtures/inc-1042.attest.json`; capture drafts `py/tests/attest/test_inc_1042.py` and `ts/tests/attest/inc-1042.test.ts` next to them. Those two files are committed contract tests: `inspect()` runs the drafted contracts over the fixture's trace and the test asserts each status, all `pass` on the fixed agent's capture. `make check` runs them outside the policy report. The double refund itself is held by the frozen traces in `incidents/INC-1042/`; the contract that catches it is in the reproduction tests (Act 2).

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
"verification": { "expect_fail": false, "expected_failures": [], "verified": true },
"exchanges": [{
  "api": "chat_completions", "path": "/chat/completions", "provider": "openai",
  "request": { "messages": [ ..., { "content": "Hi, {{email_1}}: O-1042 came damaged. Refund.", "role": "user" } ] },
  "key": { "model": "refund-desk-scripted", "prompt_hash": "sha256:1bf2c172…", "tool_schema_hash": "sha256:85273f44…" }
}],
"world": { "definition_sha256": "a5cd72eb…", "faults_fired": [{ "fault": "timeout_after_commit", "id": "inc-1042", "request": 1, ... }], "state": { "refunds": [{ "refund_id": "R-0001", "order_id": "O-1042", ... }], ... } }
```

The email is `{{email_1}}` in every place it appears. The key is nowhere in the fixture: request headers, which carry it, are never recorded, and any other place it reached would be `[redacted]`. `make capture-check` holds that to account:

| Check | Expected |
|---|---|
| re-capture both languages into a temporary directory and `cmp` with the committed fixtures | byte-identical |
| `attest capture --check-redaction` on each committed fixture | `clean`, with the planted key in the environment |
| `grep` each fixture for the planted key and the email | 0 hits |
| `attest trace check` on each fixture | exit 0 |

The fixture is the input of Act 3b. It holds the four model exchanges of the fixed agent's run with their request keys (the incident capture from the agent as it shipped had five), so replay can answer the agent's real code from the recording with zero model calls, and the `world` section holds the payments world's final state (one refund) and the fault that fired. It is evidence only: replay and the tests start a fresh world from `world/`. A fixture that came from `--from <otlp>` has the trace but no exchanges and cannot replay.

`make capture` and `make capture-check` run on attest 1.1.0-rc.2 and on attest `main`.

### Act 3b: replay

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

The fixtures on `main` are the fixed agent's recording, so replay passes there. The first capture, from the agent as it shipped, was committed with `--expect-fail`: five exchanges, `"expect_fail": true` and a world with two refunds for O-1042. [`regression/pre-fix-fixtures/`](regression/pre-fix-fixtures/) keeps those two fixtures. `make walkthrough` reverts the fix in a temporary copy of this tree, restores them there and requires strict replay to fail in both languages with `effect violated: 2 refunds for O-1042`, 0 replay misses and 0 live model calls: the incident replays from its recording.

#### A changed prompt is a replay miss

A request matches a recording when its model, parameters, prompt and tool schemas are equal. Change any of them and strict replay fails the test instead of guessing. `make replay-miss` appends one sentence to `agent-spec/system-prompt.txt`, runs both replay tests and requires each to fail with the message below, then restores the prompt. CI runs it on the edge job.

```text
replay miss: system prompt changed (hash e1b7b67→5305126); re-record with `attest capture --refresh inc-1042`
```

The hashes are the first seven characters of a hash of the old and new system prompt, so the log shows that it changed without showing the text. After an intended change, `make capture CHANNEL=edge` re-records both fixtures.

### Act 4: the fix merges, the regression is blocked

[Issue #2](https://github.com/attest-framework/refund-desk/issues/2) is closed by [#11](https://github.com/attest-framework/refund-desk/pull/11) (merged): the agents send an idempotency key and check the refund status after a timeout, the live effect tests lose their expected-failure markers and the fixtures are re-recorded. Its pr-annotate [summary](https://github.com/attest-framework/refund-desk/pull/11#issuecomment-6608157351) reads `10 passed · 0 failed · 0 not evaluated` and `8 replayed · 0 live model calls · $0.00`, with the policy at `pass (exit 0)`. The model-call line under it counts the live suites' calls to the scripted server, not a provider.

The same change reverted is the regression pull request [#12](https://github.com/attest-framework/refund-desk/pull/12) (closed unmerged, as planned). Its [summary](https://github.com/attest-framework/refund-desk/pull/12#issuecomment-6609149501) lists `effect violated: 2 refunds for O-1042 (expected 1)` with file and line (`py/tests/test_refund_desk.py:77`, `ts/tests/refund-desk.test.ts:69`), two replay misses and `Policy: fail (exit 1)`; the failures also show as annotations in the checks list. [#22](https://github.com/attest-framework/refund-desk/pull/22) repeats the regression to show the failure viewer (Act 6).

`make walkthrough` reproduces both outcomes locally: the fixed tree passes `make check-py check-ts replay-tests` and `attest report summary` over the four reports reads `0 live model calls · $0.00`; the copy with the fix reverted fails the live effect tests with the message above, and `attest policy evaluate --policy attest.policy.yaml` exits 1 for both languages.


#### The fix

Both agents (`Tools.issue_refund` in `py/src/refund_desk/agent.py`, `issueRefund` in `ts/src/agent.ts`) now send an `Idempotency-Key` header, the first 16 hex digits of `sha256("<order_id>:<amount_cents>")`, so a repeat of the same refund is answered with the first one. When the request times out they also read `GET /refunds?order_id=<id>` and, if the payments API committed a refund for that amount, return it as committed instead of reporting `payments_timeout`; the model then never retries. With no committed refund the agent still returns the timeout error.

A live test per language runs the real agent against the scripted model server under the INC-1042 fault and asserts the effect contract (`test_inc_1042_effect_contract_leaves_one_refund`, and its TypeScript twin in `ts/tests/refund-desk.test.ts`). Reverting the agent turns that test red with the message above. Replay reaches the same verdict from the fixture, but a change to the agent's tool results changes its model requests, so the fixtures are re-recorded with `make capture`.

Reproduction tests (Act 2) and the replay tests answer different questions. The reproduction tests read frozen traces and stay green for good: they prove the contract catches the bug. The replay tests run the current agent: they are green because the agent is fixed, and fail if it regresses.

### Act 5: test the tests

A suite that stays green when the agent's behavior breaks protects nothing. `attest mutate` measures that on the captured INC-1042 fixture: it makes behavior mutants of the run (a tool call dropped, duplicated or reordered, an argument perturbed, a tool error injected, a world record altered, the output truncated; this fixture's captured reply is empty, so it yields the first six and no `truncate_output` mutant), runs the suite's contracts against each at no model cost, and reports the share it killed. Only behavior is mutated, never source code. See `attest guide mutation` for the operators and the report.

```bash
make mutate CHANNEL=edge
```

The target records the contracts twice with `ATTEST_CONTRACTS_DIR`, under `reports/mutate/` only (no existing suite's report changes), and mutates each language's fixture against each recording:

- `contracts-act1`: the three Act 1 output-only tests per language (the reply text), the tests that stayed green through INC-1042;
- `contracts-all`: every contract suite: those three, the Act 4 effect test, the Act 2 reproduction tests, the Act 3a captured-fixture tests and the Act 3b strict-replay tests.

Both fixtures hold the same run, so the numbers match per language:

| | Act 1 tests | all contracts |
|---|---|---|
| mutation score | 0.00 | 0.34 |
| killed / survived | 0 / 29 | 10 / 19 |
| `duplicate_tool_call` | 0 / 3 | 3 / 0 |
| `drop_tool_call` | 0 / 3 | 3 / 0 |
| `reorder_tool_calls` | 0 / 2 | 2 / 0 |
| `alter_world_effect` | 0 / 12 | 2 / 10 |
| `perturb_argument` | 0 / 6 | 0 / 6 |
| `inject_tool_error` | 0 / 3 | 0 / 3 |

The mutant `duplicate issue_refund (order_id=O-1042)` is INC-1042 replayed on the fixed run: the agent refunds the order twice. It survives the Act 1 tests, whose reply is the same whether the customer was refunded once or twice, and the contracts kill it (`tool_cardinality`, Act 2). `scripts/mutation_report.py` asserts both outcomes for each language and exits 1 otherwise.

The Act 1 score is 0 because none of its checks can fail on this fixture: the captured trace's output is `{"message": ""}`, so the `output_contains` checks do not apply, the `output_not_contains` checks hold on an empty reply for every mutant, and the judge checks are skipped (not deterministic).

`mutation.policy.yaml` gates on the score (`min_mutation_score` 0.2, severity `block`). `make mutate` asserts that `attest policy evaluate --policy mutation.policy.yaml --mutation <report>` exits 1 for the Act 1 tests and 0 for all contracts. The 19 survivors are the gap Act 5 leaves visible: `attest mutate` prints a contract that would kill each one that the operator table can express. `make check` runs `make mutate` as `check-mutate`.

#### Coding agents draft the contracts

Two transcripts in [`docs/agent-transcripts/`](docs/agent-transcripts/) show a coding agent writing an INC-1042 contract with no help beyond attest:

- [With the attest skill](docs/agent-transcripts/2026-11-04-attest-skill-duplicate-refund-contract.md): a fresh Claude Code session with only `attest init --skills` installed, in a copy of this repo without its contracts, is asked to "add a contract that prevents duplicate refunds" and writes a passing replay test.
- [With the attest MCP server](docs/agent-transcripts/2026-11-04-attest-mcp-inc-1042-contract.md): a fresh session with only the MCP server drafts the contract with `draft_contract` and checks it with `run_contract`. It passes on the fixed agent's fixture, and its trace check fails on the frozen incident trace. The session then adds it to `py/tests/attest/test_inc_1042.py` (`test_inc_1042_double_refund_contract_holds_on_fixed_agent`).

`attest init --mcp` wrote [`.mcp.json`](.mcp.json) (Claude Code), [`.cursor/mcp.json`](.cursor/mcp.json) and [`.codex/config.toml`](.codex/config.toml). They start `attest mcp` from `PATH`, so run your client with `py/.venv/bin` on `PATH` (for example after `source py/.venv/bin/activate`). The released channel (attest 1.1.0-rc.2) has `attest mcp`. See `attest guide mcp`.

### Act 6: TypeScript parity

The TypeScript suite runs the same contracts, fixture and world as the Python one. `make check-parity` proves the verdicts match instead of trusting that the two test files drifted together: it runs every py and ts suite (the default tests, the captured-fixture tests, the reproduction tests and the strict-replay tests) with `ATTEST_CONTRACTS_DIR` set, so the engine records each spec it evaluates. A recorded spec joins to its report-v2 row by `assertion_id`, and the script compares, per `(type, spec)` and language, the sorted `(explanation, status)` pairs of that spec's evaluations. One spec runs against both incident traces and the corrected one; the engine's explanation, written from the evaluated input, keeps the verdicts of different inputs apart. The spec is canonical JSON: keys sorted, an effect spec's world snapshot removed (it differs per run), and null-valued keys dropped (the Python SDK writes an unset judge `model` as `null`, the TypeScript SDK omits it).

```text
verdict parity: 16 specs, 16 identical, 0 different, 0 allowlisted
```

The check fails on a spec whose status differs between the languages and on a spec only one language evaluates. `parity-allowlist.json` lists the exceptions (`{type, spec_contains | test_id, reason}`; a match on an evaluation in either language exempts that whole `(type, spec)` in both languages); it is empty. An entry that matches nothing also fails. `make check-parity-selftest` proves the check bites: it feeds the script small recording and report pairs with a differing status, a verdict that flips on one of two inputs of a spec, a one-language spec, a recording with no report row, a report row with no recording and a stale allowlist entry, and requires each to fail (and a differing world snapshot or a null-valued key to pass). The recording runs write their reports under `reports/parity/` only, so the policy runs above are unchanged.

`ts/tests/attest/inc-1042.test.ts` gained the double-refund contract that `py/tests/attest/test_inc_1042.py` already had (`tool_cardinality` per order plus the `world(FIXTURE.world)` effects). The SDK-side parity matrix (the TypeScript counterpart of every Python API) is in attest: `attest guide parity`, `docs/guides/parity.md`.

#### The failure viewer

`attest view` (on the released channel, attest 1.1.0-rc.2) turns the suite reports into one self-contained HTML page: the test list, the trace tree with the failing span highlighted, expected against actual, replay or live provenance, cost, a baseline diff and (when given) the surviving mutants. It needs no server and loads nothing from outside the file. See `attest guide viewer`.

`make check` runs the report-writing suites with `ATTEST_REPORT_TRACES=1` (the data here is synthetic, so embedding traces is safe) and runs `make view` before the final outage act; `make view` writes `reports/attest-report.html` from the four reports (`attest-report.{py,ts}.json` and `attest-report.replay.{py,ts}.json`). The page is written even when a suite failed.

- **From a pull request:** open the `edge` job of the PR's workflow run and download the `attest-report-html` artifact (it is a zip holding `attest-report.html`); open the file in a browser. On a pull request the job first downloads the `attest-reports` artifact of the latest successful run on `main` and passes it as the baseline, so the page carries a baseline-versus-head section: pass rate, cost, latency and every test whose tool sequence changed. A repository without a successful `main` run yet renders the page without a baseline and says so.
- **Locally:** `make view CHANNEL=edge` opens the page after a `make check`; `NO_OPEN=1` only writes it; `BASELINE_DIR=<dir>` compares against the four reports of an earlier run kept in that directory. `make check` deletes the previous reports first; `make replay-miss` rewrites the two replay reports with its deliberate miss, so run `make check` again before `make view`.

The Act 4 effect test is the one that records the agent's own OpenTelemetry spans (`chat <model>`, `execute_tool <name>`) into its attest trace and adds `tool_cardinality("issue_refund", per="order_id", at_most=1)` to its effect checks; the three Act 1 tests stay output-only. On the fixed agent the contract passes. With the INC-1042 fix reverted (the regression pull request, as in [#12](https://github.com/attest-framework/refund-desk/pull/12)) the contract hard-fails and the viewer outlines the second `issue_refund` span (`steps[N]` in the failing row's trace node) as the failing span, next to the baseline diff (`+issue_refund`).

### Act 7: the judge provider is down

The agent and attest's layer-6 judge both talk to the scripted model server, and `attest.policy.yaml` sets `not_evaluated: block`: the scripted judge always answers, so an assertion that was not evaluated is a defect here. A real provider can be down, and then the verdict must be "not evaluated", not a pass and not a failure of the agent.

```bash
make outage
```

`make outage` keeps the agent on its scripted server and points `ATTEST_JUDGE_BASE_URL` at a loopback port nothing listens on, with an empty judge cache. It runs the two suites that use the judge (`passes_judge` in `py/tests/test_refund_desk.py` and `ts/tests/refund-desk.test.ts`: the refund replies) without strict mode, and requires, per language:

- every layer-6 row is `not_evaluated` with reason `provider_unavailable`, and no row is a hard failure;
- `attest policy evaluate --policy outage.policy.yaml` exits 2: [`outage.policy.yaml`](outage.policy.yaml) is `attest.policy.yaml` with `not_evaluated: warn`;
- the same report under `attest.policy.yaml` exits 1, which is why the two policies differ.

Reports are written to `reports/outage/`. It runs on both channels and is the last step of `make check`. The plan's story places the outage after the regression; the demo numbers it last (Act 7) so the existing Act 5 and Act 6 names stay.


## Run it

Requires [uv](https://docs.astral.sh/uv/), Node.js 22+ and [pnpm](https://pnpm.io/). No API key.

```bash
make edge-artifacts ATTEST_SRC=<attest checkout>   # build attest from source (edge builds attest from a checkout)
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
| `mutation.policy.yaml`, `scripts/mutation_report.py` | The Act 5 mutation-score gate and the before/after report that `make mutate` prints (Act 5) |
| `scripts/verdict_parity.py`, `parity-allowlist.json` | The Act 6 check that the py and ts suites return the same verdict for every contract (`make check-parity`) |
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

`trace check` ships in attest 1.1.0-rc.2, so `make doctor` runs on both channels.

## Flaky model: statistical verdicts and a judge budget

One run of a non-deterministic agent cannot show that a change made it worse. `make flaky` starts the scripted model server with `--flaky P --seed 42`, which fails a seeded fraction P of chat requests with HTTP 500, and runs `test_refund_reply_confirms_amount` as 20 fixed trials (`pytest --attest-trials=20`). The agent's OpenAI client retries a failed request twice, so a trial fails when one model call fails three times in a row. [`flaky.policy.yaml`](flaky.policy.yaml) compares each assertion's pass rate with a pinned baseline (two-sided 95% Wilson interval, tolerance 0.05):

| Run | Trials passed | 95% Wilson interval | Verdict | Policy exit |
|---|---|---|---|---|
| `--flaky 0.1`, pinned as baseline `flaky-0.1` | 20/20 | | | |
| `--flaky 0.2` | 19/20 | [0.764, 0.991] | `inconclusive`: straddles the line at 0.95 | 2 |
| `--flaky 0.6` | 7/20 | [0.181, 0.567] | `regressed`: below the line | 1 |

`inconclusive` means 20 trials cannot separate 0.2 from 0.1 at this confidence; the answer is more trials, not a rerun until the verdict changes. The seed fixes which requests fail, so every rerun prints the same counts.

The last case shows the judge budget. It runs the test file once with `ATTEST_MAX_JUDGE_CALLS=1` and an empty judge cache. Two tests ask the scripted judge different questions: the first reserves the one call and is served, the second cannot reserve, is never sent, and is `not_evaluated: budget_exhausted`. The model server counts one judge request, the run summary reports `1 calls refused by budget`, and the policy warns (exit 2). Repeated identical questions are answered from the judge cache, so the 20-trial runs above reach the judge at most once.

`make flaky` exits 0 only when the trial counts, verdicts, policy exit codes, judge request counts and `not_evaluated` reasons above match; reports and model server counters are written to `reports/flaky/`. Trials, the regression rule and judge budgets ship in attest 1.1.0-rc.2, so it runs on both channels. See attest's [statistical verdicts guide](https://github.com/attest-framework/attest/blob/main/docs/guides/statistical-verdicts.md).

## License

[Apache-2.0](LICENSE)
