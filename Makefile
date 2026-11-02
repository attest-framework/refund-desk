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
REPORTS := $(CURDIR)/reports
PYTHON := uv run --no-project --python 3.12 python
STACK := $(PYTHON) scripts/stack.py --
TOOLS := ../scripts ../model-server ../payments
EDGE_VARS := ATTEST_SRC ATTEST_ENGINE_PATH ATTEST_CORE_TGZ ATTEST_VITEST_TGZ
REQUIRE_CHANNEL = @test "$$(cat .channel 2>/dev/null)" = "$(CHANNEL)" || \
	  { echo "installed channel is '$$(cat .channel 2>/dev/null)', not $(CHANNEL); run make setup CHANNEL=$(CHANNEL)"; exit 1; }
TRACES := incidents/INC-1042/trace.py.otlp.json incidents/INC-1042/trace.ts.otlp.json
# Exits 3 when the engine the installed SDK resolves has no `trace` command (attest <= rc.1).
TRACE_PROBE := from attest.cli.admin import engine_commands; \
  from attest.engine_manager import resolve_engine; \
  raise SystemExit(0 if "trace" in (engine_commands(resolve_engine()) or {}) else 3)
# Exit 3 when the installed SDKs have no behavior contracts (attest <= rc.1).
CONTRACT_PROBE_PY := from attest import ExpectChain; \
  raise SystemExit(0 if hasattr(ExpectChain, "tool_cardinality") else 3)
CONTRACT_PROBE_TS := import { ExpectChain } from "@attest-ai/core"; \
  process.exit(typeof ExpectChain.prototype.toolCardinality === "function" ? 0 : 3)

ifeq ($(filter $(CHANNEL),released edge),)
$(error CHANNEL must be released or edge, got "$(CHANNEL)")
endif
ifeq ($(CHANNEL),released)
# The released channel finds the engine the published SDK pins (PATH, ~/.attest or download).
unexport ATTEST_ENGINE_PATH
endif

.PHONY: help setup incident check check-py check-ts check-reproduction reproduction doctor flaky edge-artifacts clean

help:
	@echo "make setup [CHANNEL=released|edge]   install the Python and TS agents and attest"
	@echo "make incident                         reproduce INC-1042 and regenerate its traces"
	@echo "make check [CHANNEL=released|edge]   lint, type-check and run the attest tests"
	@echo "make doctor [CHANNEL=released|edge]  check the INC-1042 traces' structure and coverage"
	@echo "make flaky [CHANNEL=edge]            seeded flaky trials: Wilson verdicts vs a baseline, judge budget"
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
	$(STACK) $(PYTHON) scripts/incident.py $(if $(UPDATE_STRUCTURE),--update-structure)

check:
	$(REQUIRE_CHANNEL)
	mkdir -p $(REPORTS)
	$(STACK) $(MAKE) --no-print-directory check-py check-ts
	$(MAKE) --no-print-directory check-reproduction

check-py:
	cd py && uv run --no-sync python -c "import attest; print('attest-ai', attest.__version__, attest.__file__)"
	cd py && uv run --no-sync ruff check . $(TOOLS) && uv run --no-sync ruff format --check . $(TOOLS)
	cd py && uv run --no-sync mypy
	cd py && uv run --no-sync pytest --attest-strict --attest-report=$(REPORTS)/attest-report.py.json
	cd py && uv run --no-sync attest policy evaluate --report $(REPORTS)/attest-report.py.json --policy ../attest.policy.yaml

check-ts:
	cd ts && node -p "'@attest-ai/core ' + require('./node_modules/@attest-ai/core/package.json').version"
	cd ts && pnpm exec tsc --noEmit
	cd ts && ATTEST_STRICT=1 pnpm exec vitest run --reporter=default --reporter=@attest-ai/vitest/reporter --outputFile.attest=$(REPORTS)/attest-report.ts.json
	cd ts && pnpm exec attest policy evaluate --report $(REPORTS)/attest-report.ts.json --policy ../attest.policy.yaml

# The INC-1042 reproduction tests read frozen traces only, so they run outside the stack.
# CHANNEL=released skips them while its attest has no behavior contracts; edge requires them.
check-reproduction:
	@rc=0; (cd py && uv run --no-sync python -c '$(CONTRACT_PROBE_PY)') && \
	  (cd ts && node --input-type=module -e '$(CONTRACT_PROBE_TS)') || rc=$$?; \
	if [ $$rc -eq 3 ] && [ "$(CHANNEL)" = released ]; then \
	  echo "skipping the INC-1042 reproduction tests: behavior contracts need attest >= 1.0.0-rc.2, and CHANNEL=released has an older attest. They run on CHANNEL=edge."; \
	  exit 0; \
	fi; \
	test $$rc -ne 3 || echo >&2 "the attest on CHANNEL=$(CHANNEL) has no behavior contracts (tool_cardinality)"; \
	test $$rc -eq 0 || exit $$rc; \
	$(MAKE) --no-print-directory reproduction

reproduction:
	cd py && uv run --no-sync mypy reproduction
	cd py && uv run --no-sync pytest reproduction
	cd ts && pnpm exec tsc --noEmit -p reproduction
	cd ts && pnpm exec vitest run --config reproduction/vitest.config.ts

doctor:
	$(REQUIRE_CHANNEL)
	@uv run --project py --no-sync python -c '$(TRACE_PROBE)' || { rc=$$?; \
	  test $$rc -ne 3 || echo >&2 "make doctor needs attest >= 1.0.0-rc.2: the attest-engine on CHANNEL=$(CHANNEL) has no trace command. Run it on the edge channel: make edge-artifacts ATTEST_SRC=<attest checkout> && make setup CHANNEL=edge && make doctor CHANNEL=edge"; \
	  exit $$rc; }
	@status=0; for trace in $(TRACES); do \
	  uv run --project py --no-sync attest trace check "$$trace" || status=1; echo; \
	done; exit $$status

flaky:
	$(REQUIRE_CHANNEL)
	@cd py && uv run --no-sync python ../scripts/flaky.py || { rc=$$?; \
	  test $$rc -ne 3 || echo >&2 "make flaky needs attest >= 1.0.0-rc.2: the attest-ai on CHANNEL=$(CHANNEL) has no --attest-trials. Run it on the edge channel: make edge-artifacts ATTEST_SRC=<attest checkout> && make setup CHANNEL=edge && make flaky CHANNEL=edge"; \
	  exit $$rc; }

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
