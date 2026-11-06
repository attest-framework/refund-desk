# Refund Desk (synthetic). `make help` lists the targets.
#
# CHANNEL selects which attest the tests run on (contract C6):
#   released  the published packages pinned in py/uv.lock and ts/pnpm-lock.yaml (default)
#   edge      attest built from source; needs ATTEST_SRC, ATTEST_ENGINE_PATH,
#             ATTEST_CORE_TGZ and ATTEST_VITEST_TGZ (CI sets them from setup-attest;
#             locally run `make edge-artifacts ATTEST_SRC=<attest checkout>` first)

include stack.mk
-include .attest-edge/edge.mk
export

CHANNEL ?= released
INCIDENT ?= 1042
REPORTS := $(CURDIR)/reports
PYTHON := uv run --no-project --python 3.12 python
STACK := $(PYTHON) scripts/stack.py --
TOOLS := ../scripts ../model-server
EDGE_VARS := ATTEST_SRC ATTEST_ENGINE_PATH ATTEST_CORE_TGZ ATTEST_VITEST_TGZ
# The report-writing suite runs embed their traces in the reports so the failure viewer can draw
# them. Traces hold prompts, replies and tool arguments: safe here because every value is
# synthetic (scripted model server, fake payments, the invented customer of INC-1042).
REPORT_TRACES := ATTEST_REPORT_TRACES=1
REQUIRE_CHANNEL = @test "$$(cat .channel 2>/dev/null)" = "$(CHANNEL)" || \
	  { echo "installed channel is '$$(cat .channel 2>/dev/null)', not $(CHANNEL); run make setup CHANNEL=$(CHANNEL)"; exit 1; }
TRACES := incidents/INC-1042/trace.py.otlp.json incidents/INC-1042/trace.ts.otlp.json
# The failure viewer reads the four reports `make check` writes. BASELINE_DIR holds the same file
# names from an earlier run (CI downloads the latest green main run into it); without one the
# page says there is no baseline.
VIEW_REPORT_NAMES := attest-report.py.json attest-report.ts.json attest-report.replay.py.json attest-report.replay.ts.json
VIEW_OUT := $(REPORTS)/attest-report.html
# The replay run: no provider key besides a placeholder the agent's settings need (the scripted
# judge key from stack.mk stays: the engine needs one with ATTEST_JUDGE_BASE_URL), strict
# replay and the egress guard on. A miss fails the test and nothing is sent to a provider.
REPLAY_ENV := env -u ANTHROPIC_API_KEY -u GOOGLE_API_KEY -u GEMINI_API_KEY \
  OPENAI_API_KEY=replay-needs-no-key ATTEST_REPLAY=strict ATTEST_EGRESS=block
# Payments is an attest world, hosted per run (capture, replay tests, incident). It needs an
# attest with world support (edge).
WORLD := world/payments-inc-1042.world.yaml
CAPTURE_NAME := inc-1042
CAPTURE_DIR := $(CURDIR)/.stack/capture-check
FIXTURE := tests/attest/fixtures/$(CAPTURE_NAME).attest.json
# Planted by the demo: the fake key in stack.mk and the customer email in request.json.
PLANTED_EMAIL := jane.doe@example.com
# The traces under capture go to .stack/; the incident traces in incidents/ stay frozen.
# Relative path: the capture records its command line, and the fixture must not hold
# the checkout's location.
CAPTURE_TRACES := ../.stack/capture-traces
# One language's incident under `attest capture`. The capture's own environment points the
# proxy upstream at the scripted model server; the child gets the proxy URL instead.
# Arguments: 1 output directory, 2 fixture name, 3 world file, 4 incident arguments, 5 capture flags.
CAPTURE_PY = cd py && OPENAI_BASE_URL=http://127.0.0.1:$(MODEL_PORT)/v1 \
  uv run --no-sync attest capture --name $(2) --world ../$(3) $(5) --out-dir $(1) -- \
  $(PYTHON) ../scripts/incident.py $(4) --lang py --in-world --trace-dir $(CAPTURE_TRACES)
CAPTURE_TS = cd ts && OPENAI_BASE_URL=http://127.0.0.1:$(MODEL_PORT)/v1 \
  pnpm exec attest capture --name $(2) --world ../$(3) $(5) --out-dir $(1) -- \
  $(PYTHON) ../scripts/incident.py $(4) --lang ts --in-world --trace-dir $(CAPTURE_TRACES)
# INC-1077 is captured as an incident reproduction: the agent over-refunds and notifies the wrong
# customer, so the drafted relational contracts fail and are recorded as expected failures.
CAPTURE_NAME_1077 := inc-1077
WORLD_1077 := world/payments-inc-1077.world.yaml
FIXTURE_1077 := tests/attest/fixtures/$(CAPTURE_NAME_1077).attest.json
CAPTURE_ARGS_1077 := --incident 1077
CAPTURE_FLAGS_1077 := --expect-fail

ifeq ($(filter $(CHANNEL),released edge),)
$(error CHANNEL must be released or edge, got "$(CHANNEL)")
endif
# INC-1077's tests use relational contracts (`related`, `sum`, `matches`), which only attest with
# attest#242 has; the released channel (rc.3) skips them.
ifeq ($(CHANNEL),edge)
INC1077_MYPY := tests/attest/test_inc_1077.py
INC1077_REPLAY_MYPY := tests/replay/test_inc_1077_replay.py
INC1077_PYTEST_IGNORE :=
INC1077_VITEST_EXCLUDE :=
TSC_ATTEST := tsconfig.json
TSC_REPLAY := tsconfig.json
else
INC1077_MYPY :=
INC1077_REPLAY_MYPY :=
INC1077_PYTEST_IGNORE := --ignore=tests/attest/test_inc_1077.py --ignore=tests/replay/test_inc_1077_replay.py
INC1077_VITEST_EXCLUDE := --exclude '**/inc-1077.test.ts'
TSC_ATTEST := tsconfig.released.json
TSC_REPLAY := tsconfig.released.json
endif

ifeq ($(CHANNEL),released)
# The released channel finds the engine the published SDK pins (PATH, ~/.attest or download).
unexport ATTEST_ENGINE_PATH
endif

.PHONY: help setup incident incident-1077 check check-py check-ts check-reproduction reproduction check-capture capture-tests check-replay replay-tests check-mutate check-view view check-parity parity parity-record-py-default parity-record-py-attest parity-record-py-reproduction parity-record-py-replay parity-record-ts-default parity-record-ts-attest parity-record-ts-reproduction parity-record-ts-replay check-parity-selftest mutate mutate-record-act1 mutate-record-all replay-types-py replay-types-ts replay-run-py replay-run-ts replay-miss outage walkthrough act1 doctor flaky capture capture-py capture-ts capture-check recapture-py recapture-ts capture-refresh capture-refresh-py capture-refresh-ts capture-1077 capture-1077-py capture-1077-ts capture-check-1077 recapture-1077-py recapture-1077-ts edge-artifacts clean

help:
	@echo "make setup [CHANNEL=released|edge]   install the Python and TS agents and attest"
	@echo "make incident [CHANNEL=edge]          run the INC-1042 request in a fresh payments world and require one refund"
	@echo "make incident-1077 [CHANNEL=edge]     reproduce INC-1077 (over-refund, wrong recipient); writes incidents/INC-1077/trace.*.otlp.json"
	@echo "make check [CHANNEL=released|edge]   lint, type-check and run the attest tests"
	@echo "make doctor [CHANNEL=released|edge]  check the INC-1042 traces' structure and coverage"
	@echo "make flaky                           seeded flaky trials: Wilson verdicts vs a baseline, judge budget"
	@echo "make capture [CHANNEL=edge]          capture the INC-1042 run of each agent into a fixture and a test"
	@echo "make capture-check [CHANNEL=edge]    re-capture INC-1042 and INC-1077, compare bytes, redaction and trace check"
	@echo "make capture-1077 [CHANNEL=edge]     capture the INC-1077 run of each agent as an expected-failure fixture"
	@echo "make capture-check-1077 [CHANNEL=edge]  re-capture INC-1077 and compare bytes and redaction"
	@echo "make replay-miss [CHANNEL=edge]      change the system prompt and show strict replay name the change"
	@echo "make walkthrough [CHANNEL=released|edge]  every act from the incident to the viewer, each outcome checked"
	@echo "make outage [CHANNEL=released|edge]        judge unreachable: not evaluated: provider_unavailable, policy warns (exit 2)"
	@echo "make mutate [CHANNEL=edge]         mutation score of the Act 1 tests vs all contracts (Act 5)"
	@echo "make check-parity [CHANNEL=edge]  compare py and ts verdicts per contract (Act 6)"
	@echo "make view [CHANNEL=edge] [BASELINE_DIR=DIR] [NO_OPEN=1]  render reports/attest-report.html from the reports of the last make check (Act 6)"
	@echo "make edge-artifacts ATTEST_SRC=DIR    build attest from a local checkout for CHANNEL=edge"

setup:
	rm -f .channel
ifeq ($(CHANNEL),edge)
	@$(foreach v,$(EDGE_VARS),test -n "$($(v))" || { echo "CHANNEL=edge needs $(v)"; exit 1; };)
endif
	cd py && uv sync --frozen --reinstall-package attest-ai
	rm -rf ts/node_modules/@attest-ai
	cd ts && pnpm install --frozen-lockfile
ifeq ($(CHANNEL),edge)
	uv pip install --python py/.venv -e "$(ATTEST_SRC)/sdks/python"
	for pkg in core vitest; do \
	  dir=ts/node_modules/@attest-ai/$$pkg; rm -rf $$dir && mkdir -p $$dir; \
	done
	tar -xzf "$(ATTEST_CORE_TGZ)" -C ts/node_modules/@attest-ai/core --strip-components=1
	tar -xzf "$(ATTEST_VITEST_TGZ)" -C ts/node_modules/@attest-ai/vitest --strip-components=1
endif
	echo $(CHANNEL) > .channel

incident:
	$(REQUIRE_CHANNEL)
	@test "$(CHANNEL)" = edge || { echo "make incident hosts the payments world with the engine in ATTEST_ENGINE_PATH: run it on the edge channel (make incident CHANNEL=edge)"; exit 1; }
	$(STACK) $(PYTHON) scripts/incident.py --incident $(INCIDENT) $(if $(UPDATE_STRUCTURE),--update-structure)

# INC-1077 is `make incident INCIDENT=1077`: the partial-refund agent (agent-spec/v2) in a healthy
# world; its traces go to incidents/INC-1077/.
incident-1077:
	$(MAKE) incident INCIDENT=1077

check:
	$(REQUIRE_CHANNEL)
	mkdir -p $(REPORTS)
	@# A suite that dies before writing its report must not be shown with the last run's data.
	rm -f $(addprefix $(REPORTS)/,$(VIEW_REPORT_NAMES)) $(VIEW_OUT)
	@# Every suite runs and writes its report even after an earlier one fails, so CI can
	@# annotate all failures; check still exits non-zero if any suite failed and names them.
	@failed=; \
	echo '$(STACK) $(MAKE) --no-print-directory -k check-py check-ts'; \
	$(STACK) $(MAKE) --no-print-directory -k check-py check-ts || failed="$$failed check-py/check-ts"; \
	echo '$(MAKE) --no-print-directory check-reproduction'; \
	$(MAKE) --no-print-directory check-reproduction || failed="$$failed check-reproduction"; \
	echo '$(MAKE) --no-print-directory check-capture'; \
	$(MAKE) --no-print-directory check-capture || failed="$$failed check-capture"; \
	echo '$(MAKE) --no-print-directory check-replay'; \
	$(MAKE) --no-print-directory check-replay || failed="$$failed check-replay"; \
	echo '$(MAKE) --no-print-directory check-mutate'; \
	$(MAKE) --no-print-directory check-mutate || failed="$$failed check-mutate"; \
	echo '$(MAKE) --no-print-directory check-parity'; \
	$(MAKE) --no-print-directory check-parity || failed="$$failed check-parity"; \
	echo '$(MAKE) --no-print-directory check-view'; \
	$(MAKE) --no-print-directory check-view || failed="$$failed check-view"; \
	echo '$(MAKE) --no-print-directory outage'; \
	$(MAKE) --no-print-directory outage || failed="$$failed outage"; \
	test -z "$$failed" || { echo >&2 "make check failed:$$failed"; exit 1; }

check-py:
	cd py && uv run --no-sync python -c "import attest; print('attest-ai', attest.__version__, attest.__file__)"
	cd py && uv run --no-sync ruff check . $(TOOLS) && uv run --no-sync ruff format --check . $(TOOLS)
	cd py && uv run --no-sync mypy
	cd py && $(REPORT_TRACES) uv run --no-sync pytest --ignore=tests/attest --ignore=tests/replay --attest-strict --attest-report=$(REPORTS)/attest-report.py.json
	cd py && uv run --no-sync attest policy evaluate --report $(REPORTS)/attest-report.py.json --policy ../attest.policy.yaml

check-ts:
	cd ts && node -p "'@attest-ai/core ' + require('./node_modules/@attest-ai/core/package.json').version"
	cd ts && pnpm exec tsc --noEmit
	cd ts && $(REPORT_TRACES) ATTEST_STRICT=1 pnpm exec vitest run --reporter=default --reporter=@attest-ai/vitest/reporter --outputFile.attest=$(REPORTS)/attest-report.ts.json
	cd ts && pnpm exec attest policy evaluate --report $(REPORTS)/attest-report.ts.json --policy ../attest.policy.yaml

# The captured INC-1042 tests load fixtures: they need the attest that has `attest capture`.
# They stay out of the default type-check and test scope (mypy `exclude`, tsconfig `exclude`,
# vitest `exclude`) and run here, outside the policy report.
check-capture: capture-tests

# The INC-1042 replay tests (Act 3b) run today's agent against the captured fixture and a fresh
# attest world for payments (the tests host it), so they call no model.
check-replay: replay-tests

replay-tests:
	$(STACK) $(MAKE) --no-print-directory -k replay-types-py replay-types-ts replay-run-py replay-run-ts

replay-types-py:
	cd py && uv run --no-sync mypy src tests/replay/test_inc_1042_replay.py $(INC1077_REPLAY_MYPY)

replay-types-ts:
	cd ts && pnpm exec tsc --noEmit -p tests/replay/$(TSC_REPLAY)

replay-run-py:
	cd py && $(REPORT_TRACES) $(REPLAY_ENV) uv run --no-sync pytest tests/replay $(INC1077_PYTEST_IGNORE) --attest-replay=strict --attest-egress=block \
	  --attest-strict --attest-report=$(REPORTS)/attest-report.replay.py.json

replay-run-ts:
	cd ts && $(REPORT_TRACES) $(REPLAY_ENV) ATTEST_STRICT=1 pnpm exec vitest run --config tests/replay/vitest.config.ts $(INC1077_VITEST_EXCLUDE) \
	  --reporter=default --reporter=@attest-ai/vitest/reporter --outputFile.attest=$(REPORTS)/attest-report.replay.ts.json

# Acceptance proof: appending a sentence to the system prompt makes strict replay fail in
# both languages with the miss message. The script restores the prompt on every exit.
replay-miss:
	$(REQUIRE_CHANNEL)
	mkdir -p $(REPORTS)
	scripts/replay-miss.sh

# Act 5: mutation score before and after the contracts. The recording runs write the specs the
# engine evaluates to $(MUTATE_DIR)/contracts-*/ and their reports next to them; no existing
# suite's report changes. Nothing here calls a paid model (scripted server, replay, frozen traces).
MUTATE_DIR := $(REPORTS)/mutate
MUTATE_ATTEST := uv run --project py --no-sync attest
# The Act 1 output-only tests are the first three in each file; the last one is the Act 4
# effect contract.
ACT1_PY_FILTER := not effect_contract
ACT1_TS_FILTER := ^(?!.*leaves one refund)
VITEST_REPORT = --reporter=default --reporter=@attest-ai/vitest/reporter --outputFile.attest=$(1)

# Act 1: the output-only tests alone, which stay green with the double refund.
act1:
	cd py && uv run --no-sync pytest tests/test_refund_desk.py -k '$(ACT1_PY_FILTER)' --attest-strict
	cd ts && ATTEST_STRICT=1 pnpm exec vitest run tests/refund-desk.test.ts -t '$(ACT1_TS_FILTER)'

check-mutate: mutate

mutate:
	$(REQUIRE_CHANNEL)
	rm -rf $(MUTATE_DIR)
	mkdir -p $(MUTATE_DIR)
	$(STACK) $(MAKE) --no-print-directory mutate-record-act1 mutate-record-all
	@# attest mutate refuses two fixtures with one name (both languages capture "inc-1042"),
	@# so each language's fixture is mutated on its own; the policy reads the Python reports.
	$(MUTATE_ATTEST) mutate py/$(FIXTURE) --contracts $(MUTATE_DIR)/contracts-act1 --json > $(MUTATE_DIR)/act1.py.json
	$(MUTATE_ATTEST) mutate ts/$(FIXTURE) --contracts $(MUTATE_DIR)/contracts-act1 --json > $(MUTATE_DIR)/act1.ts.json
	$(MUTATE_ATTEST) mutate py/$(FIXTURE) --contracts $(MUTATE_DIR)/contracts-all --json > $(MUTATE_DIR)/contracts.py.json
	$(MUTATE_ATTEST) mutate ts/$(FIXTURE) --contracts $(MUTATE_DIR)/contracts-all --json > $(MUTATE_DIR)/contracts.ts.json
	$(PYTHON) scripts/mutation_report.py $(MUTATE_DIR)/act1.py.json $(MUTATE_DIR)/contracts.py.json \
	  $(MUTATE_DIR)/act1.ts.json $(MUTATE_DIR)/contracts.ts.json
	@$(MUTATE_ATTEST) policy evaluate --policy mutation.policy.yaml \
	  --report $(MUTATE_DIR)/attest-report.act1.py.json --mutation $(MUTATE_DIR)/act1.py.json > $(MUTATE_DIR)/policy-act1.json; rc=$$?; \
	echo "policy on the Act 1 tests: exit $$rc (expected 1)"; test $$rc -eq 1 || exit 1
	@$(MUTATE_ATTEST) policy evaluate --policy mutation.policy.yaml \
	  --report $(MUTATE_DIR)/attest-report.contracts.py.json --mutation $(MUTATE_DIR)/contracts.py.json > $(MUTATE_DIR)/policy-contracts.json; rc=$$?; \
	echo "policy on all contracts: exit $$rc (expected 0)"; test $$rc -eq 0 || exit 1

mutate-record-act1:
	cd py && ATTEST_CONTRACTS_DIR=$(MUTATE_DIR)/contracts-act1 uv run --no-sync pytest tests/test_refund_desk.py \
	  -k '$(ACT1_PY_FILTER)' --attest-strict --attest-report=$(MUTATE_DIR)/attest-report.act1.py.json
	cd ts && ATTEST_CONTRACTS_DIR=$(MUTATE_DIR)/contracts-act1 ATTEST_STRICT=1 pnpm exec vitest run tests/refund-desk.test.ts \
	  -t '$(ACT1_TS_FILTER)' $(call VITEST_REPORT,$(MUTATE_DIR)/attest-report.act1.ts.json)

# Every contract suite: the default scope (Act 1 and the Act 4 effect test), the captured-fixture
# tests (tests/attest), the reproduction tests and the strict-replay tests.
mutate-record-all:
	cd py && ATTEST_CONTRACTS_DIR=$(MUTATE_DIR)/contracts-all uv run --no-sync pytest --ignore=tests/attest --ignore=tests/replay \
	  --attest-strict --attest-report=$(MUTATE_DIR)/attest-report.contracts.py.json
	cd py && ATTEST_CONTRACTS_DIR=$(MUTATE_DIR)/contracts-all uv run --no-sync pytest tests/attest $(INC1077_PYTEST_IGNORE) --attest-strict
	cd py && ATTEST_CONTRACTS_DIR=$(MUTATE_DIR)/contracts-all uv run --no-sync pytest reproduction
	cd py && ATTEST_CONTRACTS_DIR=$(MUTATE_DIR)/contracts-all $(REPLAY_ENV) uv run --no-sync pytest tests/replay $(INC1077_PYTEST_IGNORE) \
	  --attest-replay=strict --attest-egress=block --attest-strict
	cd ts && ATTEST_CONTRACTS_DIR=$(MUTATE_DIR)/contracts-all ATTEST_STRICT=1 pnpm exec vitest run \
	  $(call VITEST_REPORT,$(MUTATE_DIR)/attest-report.contracts.ts.json)
	cd ts && ATTEST_CONTRACTS_DIR=$(MUTATE_DIR)/contracts-all ATTEST_STRICT=1 pnpm exec vitest run --config tests/attest/vitest.config.ts $(INC1077_VITEST_EXCLUDE)
	cd ts && ATTEST_CONTRACTS_DIR=$(MUTATE_DIR)/contracts-all pnpm exec vitest run --config reproduction/vitest.config.ts
	cd ts && ATTEST_CONTRACTS_DIR=$(MUTATE_DIR)/contracts-all $(REPLAY_ENV) ATTEST_STRICT=1 pnpm exec vitest run --config tests/replay/vitest.config.ts $(INC1077_VITEST_EXCLUDE)

# Act 6: py and ts verdict parity. The recording runs write the specs the engine evaluates to
# $(PARITY_DIR)/{py,ts}/ and each suite's report next to them, so no existing report or policy run
# changes. scripts/verdict_parity.py joins spec to report row by assertion_id and groups by
# (type, canonical spec); per language it compares the sorted (explanation, status) pairs of
# that spec's evaluations. Nothing here calls a paid model.
PARITY_DIR := $(REPORTS)/parity

# The selftest and the real comparison both run, so a failing selftest cannot hide a difference table.
check-parity:
	@selftest=0; $(MAKE) --no-print-directory check-parity-selftest || selftest=1; \
	$(MAKE) --no-print-directory parity || exit 1; exit $$selftest

PARITY_SUITES := py-default py-attest py-reproduction py-replay ts-default ts-attest ts-reproduction ts-replay

# Every recording runs even after one fails, then the script runs; any failure fails the target.
parity:
	$(REQUIRE_CHANNEL)
	rm -rf $(PARITY_DIR)
	mkdir -p $(PARITY_DIR)/py $(PARITY_DIR)/ts
	@rc=0; \
	$(STACK) $(MAKE) --no-print-directory -k $(addprefix parity-record-,$(PARITY_SUITES)) || rc=1; \
	$(PYTHON) scripts/verdict_parity.py --allowlist parity-allowlist.json $(PARITY_DIR)/py $(PARITY_DIR)/ts || rc=1; \
	exit $$rc

# One target per suite (default scope, captured-fixture tests, reproduction, strict replay) so -k
# keeps going past a failing one.
parity-record-py-default:
	cd py && ATTEST_CONTRACTS_DIR=$(PARITY_DIR)/py uv run --no-sync pytest --ignore=tests/attest --ignore=tests/replay \
	  --attest-strict --attest-report=$(PARITY_DIR)/py/report.default.json

parity-record-py-attest:
	cd py && ATTEST_CONTRACTS_DIR=$(PARITY_DIR)/py uv run --no-sync pytest tests/attest $(INC1077_PYTEST_IGNORE) --attest-strict \
	  --attest-report=$(PARITY_DIR)/py/report.attest.json

parity-record-py-reproduction:
	cd py && ATTEST_CONTRACTS_DIR=$(PARITY_DIR)/py uv run --no-sync pytest reproduction \
	  --attest-report=$(PARITY_DIR)/py/report.reproduction.json

parity-record-py-replay:
	cd py && ATTEST_CONTRACTS_DIR=$(PARITY_DIR)/py $(REPLAY_ENV) uv run --no-sync pytest tests/replay $(INC1077_PYTEST_IGNORE) \
	  --attest-replay=strict --attest-egress=block --attest-strict --attest-report=$(PARITY_DIR)/py/report.replay.json

parity-record-ts-default:
	cd ts && ATTEST_CONTRACTS_DIR=$(PARITY_DIR)/ts ATTEST_STRICT=1 pnpm exec vitest run \
	  $(call VITEST_REPORT,$(PARITY_DIR)/ts/report.default.json)

parity-record-ts-attest:
	cd ts && ATTEST_CONTRACTS_DIR=$(PARITY_DIR)/ts ATTEST_STRICT=1 pnpm exec vitest run --config tests/attest/vitest.config.ts $(INC1077_VITEST_EXCLUDE) \
	  $(call VITEST_REPORT,$(PARITY_DIR)/ts/report.attest.json)

parity-record-ts-reproduction:
	cd ts && ATTEST_CONTRACTS_DIR=$(PARITY_DIR)/ts pnpm exec vitest run --config reproduction/vitest.config.ts \
	  $(call VITEST_REPORT,$(PARITY_DIR)/ts/report.reproduction.json)

parity-record-ts-replay:
	cd ts && ATTEST_CONTRACTS_DIR=$(PARITY_DIR)/ts $(REPLAY_ENV) ATTEST_STRICT=1 pnpm exec vitest run --config tests/replay/vitest.config.ts $(INC1077_VITEST_EXCLUDE) \
	  $(call VITEST_REPORT,$(PARITY_DIR)/ts/report.replay.json)

# The check bites: two small recording/report pairs with one differing status must fail.
check-parity-selftest:
	$(PYTHON) scripts/verdict_parity_selftest.py

# Act 6: the failure viewer. It renders whatever reports the suites above wrote, failed suites
# included, so a red run still produces the page. It never opens a browser here (NO_OPEN=1); run
# `make view` for that.
check-view:
	@$(MAKE) --no-print-directory view NO_OPEN=1

view:
	$(REQUIRE_CHANNEL)
	@reports=; baseline=; \
	for n in $(VIEW_REPORT_NAMES); do \
	  if [ -f "$(REPORTS)/$$n" ]; then reports="$$reports $(REPORTS)/$$n"; fi; \
	  if [ -n "$(BASELINE_DIR)" ] && [ -f "$(BASELINE_DIR)/$$n" ]; then baseline="$$baseline --baseline $(BASELINE_DIR)/$$n"; fi; \
	done; \
	test -n "$$reports" || { echo >&2 "no attest reports in $(REPORTS): run make check first"; exit 1; }; \
	echo "attest view$$reports$$baseline"; \
	uv run --project py --no-sync attest view $$reports $$baseline --out $(VIEW_OUT) $(if $(NO_OPEN),--no-open)

capture-tests:
	cd py && uv run --no-sync mypy tests/attest/test_inc_1042.py $(INC1077_MYPY)
	cd py && uv run --no-sync pytest tests/attest $(INC1077_PYTEST_IGNORE) --attest-strict
	cd ts && pnpm exec tsc --noEmit -p tests/attest/$(TSC_ATTEST)
	cd ts && ATTEST_STRICT=1 pnpm exec vitest run --config tests/attest/vitest.config.ts $(INC1077_VITEST_EXCLUDE)

# The INC-1042 reproduction tests read frozen traces only, so they run outside the stack.
check-reproduction: reproduction

reproduction:
	cd py && uv run --no-sync mypy reproduction
	cd py && uv run --no-sync pytest reproduction
	cd ts && pnpm exec tsc --noEmit -p reproduction
	cd ts && pnpm exec vitest run --config reproduction/vitest.config.ts

doctor:
	$(REQUIRE_CHANNEL)
	@status=0; for trace in $(TRACES); do \
	  uv run --project py --no-sync attest trace check "$$trace" || status=1; echo; \
	done; exit $$status

flaky:
	$(REQUIRE_CHANNEL)
	cd py && uv run --no-sync python ../scripts/flaky.py

capture:
	$(REQUIRE_CHANNEL)
	$(STACK) $(MAKE) --no-print-directory capture-py capture-ts

# Re-record from scratch: the fixture is removed and captured again (capture-refresh keeps it).
capture-py:
	rm -f py/$(FIXTURE)
	$(call CAPTURE_PY,tests/attest/fixtures,$(CAPTURE_NAME),$(WORLD))

capture-ts:
	rm -f ts/$(FIXTURE)
	$(call CAPTURE_TS,tests/attest/fixtures,$(CAPTURE_NAME),$(WORLD))

# Re-runs each fixture's recorded command with `attest capture --refresh` (world-aware) and reports
# the semantic diff against the committed fixture; a re-record with no change says so.
capture-refresh:
	$(REQUIRE_CHANNEL)
	$(STACK) $(MAKE) --no-print-directory capture-refresh-py capture-refresh-ts

capture-refresh-py:
	cd py && OPENAI_BASE_URL=http://127.0.0.1:$(MODEL_PORT)/v1 uv run --no-sync attest capture --refresh $(CAPTURE_NAME) --yes

capture-refresh-ts:
	cd ts && OPENAI_BASE_URL=http://127.0.0.1:$(MODEL_PORT)/v1 pnpm exec attest capture --refresh $(CAPTURE_NAME) --yes

# Re-captures both languages into a temporary directory and holds the committed fixtures to:
# byte-identical re-capture, a clean redaction check, no planted secret, a valid trace.
capture-check:
	$(REQUIRE_CHANNEL)
	rm -rf $(CAPTURE_DIR)
	$(STACK) $(MAKE) --no-print-directory recapture-py recapture-ts
	cmp py/$(FIXTURE) $(CAPTURE_DIR)/py/$(CAPTURE_NAME).attest.json
	cmp ts/$(FIXTURE) $(CAPTURE_DIR)/ts/$(CAPTURE_NAME).attest.json
	@shasum -a 256 py/$(FIXTURE) ts/$(FIXTURE)
	cd py && uv run --no-sync attest capture --check-redaction $(FIXTURE)
	cd ts && pnpm exec attest capture --check-redaction $(FIXTURE)
	@status=0; for fixture in py/$(FIXTURE) ts/$(FIXTURE); do \
	  for planted in key email; do \
	    case $$planted in key) value='$(OPENAI_API_KEY)';; email) value='$(PLANTED_EMAIL)';; esac; \
	    hits=$$(grep -cF -- "$$value" "$$fixture" || true); \
	    echo "$$fixture: $$hits hits for the planted $$planted"; \
	    test "$$hits" -eq 0 || status=1; \
	  done; \
	done; exit $$status
	cd py && uv run --no-sync attest trace check $(FIXTURE)
	cd ts && pnpm exec attest trace check $(FIXTURE)
	$(MAKE) --no-print-directory capture-check-1077

recapture-py:
	$(call CAPTURE_PY,$(CAPTURE_DIR)/py,$(CAPTURE_NAME),$(WORLD))

recapture-ts:
	$(call CAPTURE_TS,$(CAPTURE_DIR)/ts,$(CAPTURE_NAME),$(WORLD))

# INC-1077: the buggy agent under `attest capture --expect-fail` in the INC-1077 world. Needs the
# attest that drafts relational contracts from a world (attest#242).
capture-1077:
	$(REQUIRE_CHANNEL)
	$(STACK) $(MAKE) --no-print-directory capture-1077-py capture-1077-ts

capture-1077-py:
	rm -f py/$(FIXTURE_1077)
	$(call CAPTURE_PY,tests/attest/fixtures,$(CAPTURE_NAME_1077),$(WORLD_1077),$(CAPTURE_ARGS_1077),$(CAPTURE_FLAGS_1077))

capture-1077-ts:
	rm -f ts/$(FIXTURE_1077)
	$(call CAPTURE_TS,tests/attest/fixtures,$(CAPTURE_NAME_1077),$(WORLD_1077),$(CAPTURE_ARGS_1077),$(CAPTURE_FLAGS_1077))

# Re-captures INC-1077 into a temporary directory and holds the committed fixtures to byte-identical
# re-capture, a clean redaction check and a valid trace.
capture-check-1077:
	$(REQUIRE_CHANNEL)
	rm -rf $(CAPTURE_DIR)/1077
	$(STACK) $(MAKE) --no-print-directory recapture-1077-py recapture-1077-ts
	cmp py/$(FIXTURE_1077) $(CAPTURE_DIR)/1077/py/$(CAPTURE_NAME_1077).attest.json
	cmp ts/$(FIXTURE_1077) $(CAPTURE_DIR)/1077/ts/$(CAPTURE_NAME_1077).attest.json
	cd py && uv run --no-sync attest capture --check-redaction $(FIXTURE_1077)
	cd ts && pnpm exec attest capture --check-redaction $(FIXTURE_1077)

recapture-1077-py:
	$(call CAPTURE_PY,$(CAPTURE_DIR)/1077/py,$(CAPTURE_NAME_1077),$(WORLD_1077),$(CAPTURE_ARGS_1077),$(CAPTURE_FLAGS_1077))

recapture-1077-ts:
	$(call CAPTURE_TS,$(CAPTURE_DIR)/1077/ts,$(CAPTURE_NAME_1077),$(WORLD_1077),$(CAPTURE_ARGS_1077),$(CAPTURE_FLAGS_1077))

# The whole story, act by act, each act's outcome checked (scripts/walkthrough.py). It runs the
# existing targets above and a copy of this tree with the INC-1042 fix reverted, so it needs
# `make setup` first and takes about two minutes. It is not part of `make check`: that already runs
# every suite once, and the walkthrough would run them a second time.
walkthrough:
	$(REQUIRE_CHANNEL)
	$(PYTHON) scripts/walkthrough.py --channel $(CHANNEL)

# Provider outage: attest's judge is unreachable (a closed loopback port) while the agent keeps its
# scripted server. The judge rows are not evaluated: provider_unavailable; outage.policy.yaml
# warns (exit 2) where attest.policy.yaml blocks (exit 1). Nothing here calls a paid model.
outage:
	$(REQUIRE_CHANNEL)
	$(STACK) $(PYTHON) scripts/outage.py

edge-artifacts:
	@test -n "$(ATTEST_SRC)" || { echo "usage: make edge-artifacts ATTEST_SRC=<attest checkout>"; exit 1; }
	mkdir -p .attest-edge/npm
	cd "$(ATTEST_SRC)/engine" && go build -o "$(CURDIR)/.attest-edge/attest-engine" ./cmd/attest-engine/
	cd "$(ATTEST_SRC)/sdks/typescript" && pnpm install --frozen-lockfile && pnpm -r build
	rm -f .attest-edge/npm/*.tgz
	for pkg in core vitest; do \
	  (cd "$(ATTEST_SRC)/sdks/typescript/packages/$$pkg" && pnpm pack --pack-destination "$(CURDIR)/.attest-edge/npm"); \
	done
	{ echo "ATTEST_SRC ?= $(abspath $(ATTEST_SRC))"; \
	  echo "ATTEST_ENGINE_PATH ?= $(CURDIR)/.attest-edge/attest-engine"; \
	  echo "ATTEST_CORE_TGZ ?= $$(ls $(CURDIR)/.attest-edge/npm/attest-ai-core-*.tgz)"; \
	  echo "ATTEST_VITEST_TGZ ?= $$(ls $(CURDIR)/.attest-edge/npm/attest-ai-vitest-*.tgz)"; } > .attest-edge/edge.mk
	@echo "wrote .attest-edge/edge.mk; now: make setup CHANNEL=edge && make check CHANNEL=edge"

clean:
	rm -rf .stack .attest-edge .channel reports py/.venv ts/node_modules

