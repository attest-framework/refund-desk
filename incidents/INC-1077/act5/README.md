# Act 5: a coding agent drafts the relational contract

The committed [stream-json transcript](transcript.stream.jsonl) records the coding agent reading synthetic [issue #34](https://github.com/attest-framework/refund-desk/issues/34), using only the attest MCP server, and writing [inc_1077_contract.py](inc_1077_contract.py). The Python contract is the agent's output, unedited. The walkthrough does not invoke a coding agent: it verifies this recorded outcome offline against the frozen incident and the fixed capture.

## Reproduce the recorded session

Use a scratch copy of Refund Desk, not your normal checkout. Remove its project settings and copy only attest's `attest` and `attest-verify-generator` skills from the attest checkout into the scratch `.claude/skills/`. No extra project instructions or project MCP servers belong in that scratch tree. Install the edge SDK and point `ATTEST_ENGINE_PATH` at the edge engine. Write an MCP config containing only:

```json
{"mcpServers":{"attest":{"command":"attest","args":["mcp"]}}}
```

Run a prompt containing the complete synthetic issue text from issue #34 and the instruction below to write and execute the two-fixture contract test. The stream recording does not include the CLI's initial `-p` argument; this is the reproducible task, not a claim of a byte-identical recovered prompt.

```bash
env -i HOME="$HOME" USER="$USER" LOGNAME="$LOGNAME" \
  PATH="$PWD/py/.venv/bin:$PATH" ATTEST_ENGINE_PATH="$ATTEST_ENGINE_PATH" \
  claude -p --setting-sources project --strict-mcp-config \
  --mcp-config /path/to/attest-only.json --output-format stream-json --verbose \
  '<the task below plus the full synthetic issue #34 text>'
```

This is a record of a subscription-backed session, not a command the walkthrough runs. On macOS `HOME` and `PATH` alone under `env -i` returned `Not logged in`; `USER` and `LOGNAME` were also needed for keychain login. The successful recording reports Claude Code 2.1.319 and model `claude-opus-5-5`. Claude Code's bundled skills also appear in its init event; only the two attest skills were installed as project skills. Home paths are redacted to `~`, the temporary checkout to `<scratch>`, and credential-expiry metadata is removed.


Use this task and the complete issue text from [issue #34](https://github.com/attest-framework/refund-desk/issues/34):

> Use the attest skills and attest MCP server to draft relational contracts for INC-1077 from the synthetic issue. Write `drafted/inc_1077_contract.py` and a pytest test. Verify the contract with MCP against `incidents/INC-1077/fixture.py.attest.json` (must fail the two issue expectations) and `py/tests/attest/fixtures/inc-1077.attest.json` (must pass). Run the pytest test with `uv run --project py --no-sync pytest drafted/test_inc_1077_contract.py --attest-strict` and report its actual outcome. Do not call a model provider, change the agents, or change the frozen fixtures.

The issue describes two refunds ($12.00 then $126.00, $138.00 total) against O-2077 ($126.00, C-0744), followed by a confirmation sent to C-0311, whose order was looked up earlier. Its expectations are: refunded total per order never exceeds the order amount, and a notification about an order goes to that order's customer. The per-order refund cardinality of two misses both defects.

## Verify the artifact without a coding agent

After `make edge-artifacts ATTEST_SRC=<attest checkout>` and `make setup CHANNEL=edge`:

```bash
export ATTEST_ENGINE_PATH="$PWD/.attest-edge/attest-engine"
(cd py && ATTEST_CONTRACTS_DIR="$PWD/../reports/act5-contracts" \
  uv run --no-sync pytest ../incidents/INC-1077/act5/test_drafted_contract.py --attest-strict)
uv run --project py --no-sync attest mutate \
  py/tests/attest/fixtures/inc-1077.attest.json \
  --contracts reports/act5-contracts --json
```

Both tests pass: one requires the drafted `sum` and `matches` assertions to **fail** the frozen incident with $138.00 refunded against $126.00 and C-0311 notified instead of C-0744; the other requires both assertions to **pass** the fixed capture. The fixed capture now carries synthetic contact emails for Act 3; the incident recording stays frozen.

## Per-operator mutation report

[mutation-report.json](mutation-report.json) is the full deterministic `attest mutate --json` result using those two recorded relational assertions, not the entire test suite. Overall: **11 / 49 killed (22.45%)**. The walkthrough regenerates and compares it with the committed report.

| Operator | Generated | Killed | Survived | What the survivors mean |
|---|---:|---:|---:|---|
| `drop_tool_call` | 5 | 0 | 5 | These contracts constrain ledger effects, not whether every tool was called. Add trajectory/cardinality contracts when a required call matters. |
| `duplicate_tool_call` | 5 | 0 | 5 | Duplicating a recorded tool step does not change its recorded world; a trace cardinality contract is needed. |
| `reorder_tool_calls` | 2 | 0 | 2 | The world invariants do not prescribe call order; use an ordering contract. |
| `perturb_argument` | 11 | 0 | 11 | A changed argument is not a recomputed ledger. Argument contracts are separate from these effect assertions. |
| `inject_tool_error` | 5 | 0 | 5 | The relational invariants do not assert tool success. Add a no-tool-error/status contract if required. |
| `alter_world_effect` | 21 | 11 | 10 | Over-refunds and recipient mismatches are killed. Deletions and unrelated/under-refund changes can still satisfy upper-bound and relational-match invariants. Add existence/count or exact-amount contracts only if those are intended requirements. |

Every surviving mutant has a suggested contract in `survivors_suggestions`. A survivor is a documented limit of this two-invariant contract, not proof that a mutation happened safely and not a reason to invent a broader business requirement.
