# Local stack settings, read by the Makefile and exported to every command.
# `?=` lets an exported environment variable override a value.
#
# Synthetic: the model is scripted (model-server/server.py) and payments are
# fake (payments/server.py). The API keys below are placeholders that the
# scripted server ignores; no paid model is called.
MODEL_PORT ?= 8790
PAYMENTS_PORT ?= 8791
MODEL_BASE_URL ?= http://127.0.0.1:$(MODEL_PORT)/v1
MODEL_NAME ?= refund-desk-scripted
MODEL_API_KEY ?= scripted-model-server-needs-no-key
PAYMENTS_BASE_URL ?= http://127.0.0.1:$(PAYMENTS_PORT)
PAYMENTS_TIMEOUT_MS ?= 1200

# attest's LLM judge (layer 6) talks to the same scripted server.
ATTEST_JUDGE_BASE_URL ?= $(MODEL_BASE_URL)
ATTEST_JUDGE_MODEL ?= refund-desk-judge
ATTEST_JUDGE_API_KEY ?= scripted-model-server-needs-no-key
