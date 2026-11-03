# Agent transcript: a duplicate-refund contract from the attest skill

A fresh Claude Code session had only `attest init --skills` installed. It was asked to "add a contract that prevents duplicate refunds" and wrote a passing attest test. It called no live model.

## Setup

| | |
|---|---|
| Date | 2026-11-04 |
| attest | `main` at 8c84341, built for the edge channel (`make edge-artifacts ATTEST_SRC=<attest checkout> && make setup CHANNEL=edge`) |
| Agent | Claude Code 2.1.317, model `claude-sonnet-5-5`: `claude -p "add a contract that prevents duplicate refunds" --output-format stream-json --verbose --strict-mcp-config --setting-sources project --permission-mode bypassPermissions` |
| Environment | `env -i` with `PATH`, `HOME`, `USER`, `LOGNAME`, `TMPDIR`, `LANG`, `TERM=dumb`, non-interactive git settings, and `ATTEST_ENGINE_PATH` set to the edge engine. No provider keys. `--setting-sources project` loads no user settings, user skills or `CLAUDE.md`. |
| Skills loaded | `attest, attest-verify-generator` (from `attest init --skills`), plus Claude Code's built-in skills |
| Result | 10 turns, 30 s |

### The scratch copy

The scratch copy is `git archive` of refund-desk `main` (0875bad) in a new git repository with one commit. Every existing duplicate-refund contract was removed from it, so the session had to write one:

- the reproduction tests: `py/reproduction/test_inc_1042.py` and `ts/reproduction/inc-1042.test.ts`;
- the captured tests: `py/tests/attest/test_inc_1042.py` and `ts/tests/attest/inc-1042.test.ts`;
- the replay tests: `py/tests/replay/test_inc_1042_replay.py` and `ts/tests/replay/inc-1042.test.ts`;
- the effect-contract test case at the end of `py/tests/test_refund_desk.py` and `ts/tests/refund-desk.test.ts`;
- the README from Act 2 on;
- the reproduction, capture and replay suites in `make check`.

The fixed agent, the INC-1042 fixtures (including their drafted contracts), the worlds, the incident README and the Makefile's replay targets stayed. Then:

```bash
ATTEST_ENGINE_PATH=<scratch>/.attest-edge/attest-engine uv run --project py --no-sync attest init --skills --json
```

That wrote `.agents/skills/{attest,attest-verify-generator}/` and `.claude/skills/{attest,attest-verify-generator}/`, plus the scaffold `tests/test_my_agent.py`, and skipped `attest.policy.yaml`. Before the session, `make check CHANNEL=edge` passed: 3 Python and 3 TypeScript output-only tests.

The skills' worked examples use a fictional checkout assistant. They contain none of refund-desk's names: no refund, payments, INC-1042, O-1042 or `issue_refund`. A first run used an earlier draft of the skills whose examples were copied from refund-desk. That run was discarded, the examples were replaced in attest#162, and the session was run again from a clean scratch copy.

## Prompt

```text
add a contract that prevents duplicate refunds
```

## Session

**Tool 1: Skill** `attest`

<details><summary>Output</summary>

````text
Launching skill: attest
````

</details>

**Tool 2: Read** `<scratch>/.claude/skills/attest/references/write-contracts.md`

<details><summary>Output</summary>

````text
1	# Write a contract for an agent behavior
2	
3	Goal: a test that encodes a rule such as "never charge a card twice", runs the agent's real code with zero model calls, and passes on the current agent. Background: `attest guide behavior-contracts`, `attest guide world-fixtures`, `attest guide replay`.
4	
5	## 1. Find the agent, its tools and its evidence
6	
7	```bash
8	git ls-files '*.attest.json' '*world.yaml' '*.otlp.json' 'incidents/*'
9	git grep -n -E 'def (run|handle|invoke)\b|export (async )?function (run|handle|invoke)\b|tools\.json|"type": "function"|execute_tool|tool_call'
10	git grep -l -E 'attest_replay|useReplay|attest_world|useWorld|attest\.evaluate|evaluate\('
11	```
12	
13	Write down the repo's own facts, before any code. The final column is one fictional checkout assistant example, not names or paths to assume in the target repo:
14	
15	| Item | Where to look | Checkout assistant example |
16	| --- | --- | --- |
17	| Entry point the tests can call | agent modules, CLI modules, existing tests | `shop_assistant.agent.handle(config, message, tracer)`; TS `handle(loadConfig(), message, tracer)` |
18	| How it builds its model client | configuration loaders and client constructors | reads `OPENAI_BASE_URL` / `OPENAI_API_KEY` when `load_config()` (TS `loadConfig()`) runs |
19	| Tool names and the business key in their arguments | tool schemas (`tools.json`, function definitions) | `charge_card(order_id, amount_cents)`; key `order_id` |
20	| Where side effects go | HTTP clients and their base URL variables | billing API at `BILLING_BASE_URL` |
21	| Fixture with recorded model calls | `tests/attest/fixtures/<name>.attest.json` | `checkout-timeout` |
22	| World for the external system | `*.world.yaml` (`base_url_env`, `faults`) | `world/billing-timeout.world.yaml` with `timeout_after_commit`, collection `charges` |
23	| Incident input and frozen trace | `incidents/<ID>/` | `incidents/INC-7/request.json`, `incidents/INC-7/trace.otlp.json` |
24	| How tests already run, with which env | `Makefile`, `package.json` scripts, CI workflow | `make test` |
25	
26	No fixture yet: follow `capture-incident.md` first, then return here. No trace at all (the agent emits no OpenTelemetry spans and uses no adapter): read `attest guide framework-adapters`.
27	
28	## 2. Choose the contract
29	
30	| The rule is about | Use | Needs |
31	| --- | --- | --- |
32	| which tools the agent calls, how often per key, in what order, with which arguments | trace contract: `tool_cardinality`, `forbidden_tools`, `tool_called_before`, `trajectory`, `tool_arg_satisfies`, `no_tool_cycles`, `max_tool_failure_streak` | a trace (replayed run, fixture trace or OTLP export) |
33	| what ended up in the external system (records created, duplicates, idempotency keys) | world-effect contract: `world(state).count`, `.unique`, `.idempotent` | a `world.yaml` for the system, and the agent reading its base URL from the world's `base_url_env` variable |
34	
35	Decision rule: a duplicate the model causes (it calls the tool twice) shows in the trace. A duplicate below the tool (an HTTP retry after a timeout that already committed) leaves one tool call and two records: only the effect contract catches it. For "prevent duplicate X", write both when a world exists; write the trace contract alone when none exists, and tell the user the effect is unchecked.
36	
37	Do not write a world from scratch unless the user asks; a world covers HTTP/JSON create/list/get only (`attest guide world-fixtures`).
38	
39	## 3. Write the test
40	
41	Put it next to the repo's existing replay tests (same directory, same naming). Construct model and HTTP clients after `attest_replay` / `useReplay` and `attest_world` / `useWorld` have set the environment.
42	
43	Example: the fictional checkout assistant discovered above. Python (pytest; the `attest`, `attest_replay` and `attest_world` fixtures come from the installed plugin):
44	
45	```python
46	import json
47	from pathlib import Path
48	
49	from attest import OTelAdapter, expect
50	from opentelemetry.sdk.trace import TracerProvider
51	from opentelemetry.sdk.trace.export import SimpleSpanProcessor
52	from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
53	
54	from shop_assistant.agent import handle, load_config
55	
56	ROOT = Path(__file__).resolve().parents[3]
57	MESSAGE = json.loads((ROOT / "incidents/INC-7/request.json").read_text())["customer_message"]
58	
59	
60	def test_checkout_charges_order_once(attest, attest_replay, attest_world):
… (103 more lines)
````

</details>

**Tool 3: Bash**

````bash
git ls-files | head -80 && git grep -n -i refund -- '*.py' | head -40
````

<details><summary>Output</summary>

````text
.agents/skills/attest-verify-generator/SKILL.md
.agents/skills/attest-verify-generator/references/template.md
.agents/skills/attest/SKILL.md
.agents/skills/attest/references/capture-incident.md
.agents/skills/attest/references/ci-setup.md
.agents/skills/attest/references/debug-failure.md
.agents/skills/attest/references/migrate.md
.agents/skills/attest/references/write-contracts.md
.github/workflows/ci.yml
.gitignore
LICENSE
Makefile
README.md
agent-spec/system-prompt.txt
agent-spec/tools.json
attest.policy.yaml
flaky.policy.yaml
incidents/INC-1042/README.md
incidents/INC-1042/corrected.otlp.json
incidents/INC-1042/request.json
incidents/INC-1042/span-structure.txt
incidents/INC-1042/trace.py.otlp.json
incidents/INC-1042/trace.ts.otlp.json
model-server/server.py
py/.python-version
py/pyproject.toml
py/src/refund_desk/__init__.py
py/src/refund_desk/agent.py
py/src/refund_desk/cli.py
py/src/refund_desk/otlp_json.py
py/tests/attest/fixtures/inc-1042.attest.json
py/tests/conftest.py
py/tests/test_refund_desk.py
py/uv.lock
ruff.toml
scripts/flaky.py
scripts/incident.py
scripts/replay-miss.sh
scripts/span-structure.txt
scripts/stack.py
stack.mk
tests/test_my_agent.py
ts/package.json
ts/pnpm-lock.yaml
ts/pnpm-workspace.yaml
ts/reproduction/tsconfig.json
ts/reproduction/vitest.config.ts
ts/src/agent.ts
ts/src/cli.ts
ts/src/otlp-json.ts
ts/tests/attest/fixtures/inc-1042.attest.json
ts/tests/attest/tsconfig.json
ts/tests/attest/vitest.config.ts
ts/tests/refund-desk.test.ts
ts/tests/replay/tsconfig.json
ts/tests/replay/vitest.config.ts
ts/tsconfig.json
ts/vitest.config.ts
world/payments-inc-1042.world.yaml
world/payments.world.yaml
… (40 more lines)
````

</details>

**Tool 4: Bash**

````bash
cat py/tests/test_refund_desk.py py/tests/conftest.py tests/test_my_agent.py world/payments-inc-1042.world.yaml; cat incidents/INC-1042/README.md Makefile; sed -n 50,140p py/src/refund_desk/agent.py
````

<details><summary>Output</summary>

````text
"""Output-only attest tests for Refund Desk.

Most of these tests check only the reply text, so they stayed green under the INC-1042
fault while the customer was refunded twice.
"""

from __future__ import annotations

from collections.abc import Callable

from attest import Agent, AgentResult, TraceBuilder, expect
from attest.plugin import AttestEngineFixture
from attest.world import WorldSession
from opentelemetry import trace

from refund_desk.agent import Settings, run

CONFIRMS_REFUND = "The reply confirms that the refund was processed and states its amount."


def refund_desk(settings: Settings, customer_message: str) -> AgentResult:
    """Run the real agent and record its input and reply as an attest trace."""

    def call(builder: TraceBuilder, customer_message: str) -> dict[str, str]:
        return {"message": run(settings, customer_message, trace.get_tracer("refund-desk"))}

    return Agent("refund-desk", fn=call).run(customer_message=customer_message)


def test_refund_reply_confirms_amount(
    attest: AttestEngineFixture, payments_world: Callable[[str], WorldSession]
) -> None:
    payments_world("payments")

    result = refund_desk(Settings.from_env(), "Order O-2001 arrived torn. Please refund it.")

    attest.evaluate(
        expect(result)
        .output_contains("refund of $26.50")
        .output_not_contains("could not")
        .passes_judge(CONFIRMS_REFUND)
    )


def test_inc_1042_reply_confirms_single_refund_amount(
    attest: AttestEngineFixture,
    payments_world: Callable[[str], WorldSession],
    incident_request: dict[str, str],
) -> None:
    # Same fault as INC-1042: the payments API times out after committing.
    payments_world("payments-inc-1042")

    result = refund_desk(Settings.from_env(), incident_request["customer_message"])

    attest.evaluate(
        expect(result)
        .output_contains("refund of $84.00")
        .output_not_contains("$168.00")
        .passes_judge(CONFIRMS_REFUND)
    )
… (531 more lines)
````

</details>

**Tool 5: Bash**

````bash
cd <scratch>/py && cat pyproject.toml | sed -n 1,60p; head -c 1500 tests/attest/fixtures/inc-1042.attest.json; cat ../incidents/INC-1042/request.json; ls .venv 2>&1 | head -3; uv run --no-sync attest doctor --json 2>&1 | head -30; sed -n 1,50p src/refund_desk/agent.py
````

<details><summary>Output</summary>

````text
[project]
name = "refund-desk"
version = "0.0.0"
description = "Refund Desk agent (synthetic) for the attest incident demo"
license = "Apache-2.0"
requires-python = ">=3.12"
dependencies = [
    "httpx>=0.28",
    "openai>=1.109",
    "opentelemetry-api>=1.38",
    "opentelemetry-exporter-otlp-proto-http>=1.38",
    "opentelemetry-sdk>=1.38",
]

[project.scripts]
refund-desk = "refund_desk.cli:main"

[dependency-groups]
dev = [
    "attest-ai==1.0.0rc3",
    "mypy>=1.18",
    "pytest>=8.4",
    "ruff>=0.14",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/refund_desk"]

[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B"]

[tool.mypy]
strict = true
files = ["src", "tests"]
# Type-checked by `make check-capture` and `make check-replay`: they need an attest with capture and replay.
exclude = ["tests/attest/", "tests/replay/"]

[tool.pytest.ini_options]
testpaths = ["tests"]
{
  "contracts": [
    {
      "description": "calls lookup_order, issue_refund, notify_customer",
      "id": "tools-called",
      "kind": "tools",
      "spec": {
        "check": "trajectory",
        "mode": "superset",
        "soft": false,
        "tools": [
          "lookup_order",
          "issue_refund",
… (127 more lines)
````

</details>

**Tool 6: Bash**

````bash
mkdir -p tests/replay && cat > tests/replay/test_inc_1042_replay.py <<'EOF'
"""INC-1042 duplicate-refund contract, checked on today's agent under strict replay.

The agent runs for real against a fresh payments world with the INC-1042 fault armed
(the first refund commits, then times out). The model's replies come from the captured
fixture, so the test makes no model calls.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from attest import OTelAdapter, expect
from attest.plugin import AttestEngineFixture
from attest.world import WorldSession
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from refund_desk.agent import Settings, run


def test_inc_1042_refunds_order_once(
    attest: AttestEngineFixture,
    attest_replay: Callable[..., AbstractContextManager[Any]],
    payments_world: Callable[[str], WorldSession],
    incident_request: dict[str, str],
) -> None:
    world = payments_world("payments-inc-1042")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    with attest_replay("inc-1042"):
        run(Settings.from_env(), incident_request["customer_message"], provider.get_tracer("verify"))

    trace = OTelAdapter.from_spans(exporter.get_finished_spans())
    state = world.state()

    attest.evaluate(
        expect(trace)
        # Trace: the model never asks for the same order to be refunded twice.
        .tool_cardinality("issue_refund", per="order_id", at_most=1)
        # Effect: the payments API holds exactly one refund for the order, and no
        # idempotency key produced two records.
        .world(state)
        .count("refunds", equals=1, order_id="O-1042")
        .world(state)
        .idempotent("refunds", order_id="O-1042")
    )
EOF
OPENAI_API_KEY=replay-needs-no-key ATTEST_REPLAY=strict ATTEST_EGRESS=block OPENAI_BASE_URL=http://127.0.0.1:1/v1 MODEL_NAME=refund-desk-scripted PAYMENTS_TIMEOUT_MS=1000 PAYMENTS_BASE_URL=http://x uv run --no-sync pytest tests/replay --attest-replay=strict --attest-egress=block --attest-strict 2>&1 | tail -30
````

<details><summary>Output</summary>

````text
============================= test session starts ==============================
platform darwin -- Python 3.12.15, pytest-9.2.0, pluggy-1.7.0
rootdir: <scratch>/py
configfile: pyproject.toml
plugins: attest-ai-1.0.0-rc.3, anyio-4.16.0
collected 1 item

tests/replay/test_inc_1042_replay.py .                                   [100%]

attest replay: 4 replayed · 0 live model calls · $0.00
============================== 1 passed in 1.59s ===============================
````

</details>

**Assistant:**

Test passes under replay. I'm running a lint check, then I'll report.

**Tool 7: Bash**

````bash
uv run --no-sync ruff check tests/replay && uv run --no-sync ruff format --check tests/replay; uv run --no-sync mypy tests/replay/test_inc_1042_replay.py 2>&1 | tail -5
````

<details><summary>Output</summary>

````text
E501 Line too long (101 > 100)
  --> tests/replay/test_inc_1042_replay.py:36:101
   |
35 |     with attest_replay("inc-1042"):
36 |         run(Settings.from_env(), incident_request["customer_message"], provider.get_tracer("verify"))
   |                                                                                                     ^
37 |
38 |     trace = OTelAdapter.from_spans(exporter.get_finished_spans())
   |

Found 1 error.
tests/replay/test_inc_1042_replay.py:21: error: Skipping analyzing "refund_desk.agent": module is installed, but missing library stubs or py.typed marker  [import-untyped]
tests/replay/test_inc_1042_replay.py:21: note: See https://mypy.readthedocs.io/en/stable/running_mypy.html#missing-imports
Found 1 error in 1 file (checked 1 source file)
````

</details>

**Tool 8: Bash**

````bash
uv run --no-sync ruff format tests/replay && uv run --no-sync ruff check tests/replay && uv run --no-sync mypy src tests/replay/test_inc_1042_replay.py 2>&1 | tail -3
OPENAI_API_KEY=replay-needs-no-key OPENAI_BASE_URL=http://127.0.0.1:1/v1 MODEL_NAME=refund-desk-scripted PAYMENTS_TIMEOUT_MS=1000 PAYMENTS_BASE_URL=http://x uv run --no-sync pytest tests/replay --attest-replay=strict --attest-egress=block --attest-strict 2>&1 | tail -3
````

<details><summary>Output</summary>

````text
1 file reformatted
All checks passed!
Success: no issues found in 5 source files

attest replay: 4 replayed · 0 live model calls · $0.00
============================== 1 passed in 1.55s ===============================
````

</details>

**Assistant:**

I added a duplicate-refund contract in `py/tests/replay/test_inc_1042_replay.py`. It passes on the current agent with no model calls.

It runs the real agent against the payments world with the INC-1042 fault armed, where the first refund commits and then times out. The model replies come from the captured `inc-1042` fixture. The contract has three checks:
- **Trace:** `issue_refund` is called at most once per `order_id`, which catches the model asking for the same refund twice.
- **Effect:** the `refunds` collection holds exactly one record for `O-1042`, which catches a duplicate created below the tool, such as an HTTP retry after the timeout.
- **Idempotency:** no idempotency key produced two refund records.

I did not check that the contract fails when the bug is present. I didn't break the agent's idempotency or its refund-lookup after a timeout to see the test go red, so a passing run only shows the current agent is clean.

I only ran the new test, not `make check` or the full suite.

```
cd py && OPENAI_API_KEY=replay-needs-no-key OPENAI_BASE_URL=http://127.0.0.1:1/v1 MODEL_NAME=refund-desk-scripted \
  PAYMENTS_TIMEOUT_MS=1000 PAYMENTS_BASE_URL=http://x \
  uv run --no-sync pytest tests/replay --attest-replay=strict --attest-egress=block --attest-strict
→ attest replay: 4 replayed · 0 live model calls · $0.00
→ 1 passed
```

`ruff` and `mypy` are clean. No `not_evaluated` results. The `make replay-tests` target also runs the TypeScript side, and I haven't added a matching TS test.

I haven't committed anything.


## Result

The session added one test file and committed nothing.

```diff
diff --git a/py/tests/replay/test_inc_1042_replay.py b/py/tests/replay/test_inc_1042_replay.py
new file mode 100644
index 0000000..7d7ff80
--- /dev/null
+++ b/py/tests/replay/test_inc_1042_replay.py
@@ -0,0 +1,53 @@
+"""INC-1042 duplicate-refund contract, checked on today's agent under strict replay.
+
+The agent runs for real against a fresh payments world with the INC-1042 fault armed
+(the first refund commits, then times out). The model's replies come from the captured
+fixture, so the test makes no model calls.
+"""
+
+from __future__ import annotations
+
+from collections.abc import Callable
+from contextlib import AbstractContextManager
+from typing import Any
+
+from attest import OTelAdapter, expect
+from attest.plugin import AttestEngineFixture
+from attest.world import WorldSession
+from opentelemetry.sdk.trace import TracerProvider
+from opentelemetry.sdk.trace.export import SimpleSpanProcessor
+from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
+
+from refund_desk.agent import Settings, run
+
+
+def test_inc_1042_refunds_order_once(
+    attest: AttestEngineFixture,
+    attest_replay: Callable[..., AbstractContextManager[Any]],
+    payments_world: Callable[[str], WorldSession],
+    incident_request: dict[str, str],
+) -> None:
+    world = payments_world("payments-inc-1042")
+    exporter = InMemorySpanExporter()
+    provider = TracerProvider()
+    provider.add_span_processor(SimpleSpanProcessor(exporter))
+
+    with attest_replay("inc-1042"):
+        run(
+            Settings.from_env(), incident_request["customer_message"], provider.get_tracer("verify")
+        )
+
+    trace = OTelAdapter.from_spans(exporter.get_finished_spans())
+    state = world.state()
+
+    attest.evaluate(
+        expect(trace)
+        # Trace: the model never asks for the same order to be refunded twice.
+        .tool_cardinality("issue_refund", per="order_id", at_most=1)
+        # Effect: the payments API holds exactly one refund for the order, and no
+        # idempotency key produced two records.
+        .world(state)
+        .count("refunds", equals=1, order_id="O-1042")
+        .world(state)
+        .idempotent("refunds", order_id="O-1042")
+    )
```

## Verification by the runner

These checks were run in the scratch copy after the session ended.

| Check | Result |
|---|---|
| `make check-replay CHANNEL=edge` | Python: mypy `Success: no issues found in 5 source files`, then `1 passed` with `attest replay: 4 replayed · 0 live model calls · $0.00`. The TypeScript replay step has no test file, because the session wrote a Python test only, so the target exits non-zero. |
| `make check CHANNEL=edge` | exit 0 |
| The INC-1042 fix from #11 reverted in `py/src`, then `make check-replay CHANNEL=edge` | `FAILED tests/replay/test_inc_1042_replay.py::test_inc_1042_refunds_order_once`: `replay miss: messages changed (hash 25da4a0→267d256)`, with `2 replayed · 0 live model calls · $0.00 · 1 missed` |

Strict replay stops the reverted agent at its first changed model request, so the run fails before the trace and world assertions are evaluated.
