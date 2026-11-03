# Local stack settings, read by the Makefile and exported to every command.
# `?=` lets an exported environment variable override a value.
#
# Synthetic: the model is scripted (model-server/server.py) and payments are
# fake (payments/server.py). The API key below is a planted fake that the
# scripted server ignores (it looks like a real key so capture's redaction has something
# to catch); no paid model is called.
MODEL_PORT ?= 8790
PAYMENTS_PORT ?= 8791
OPENAI_BASE_URL ?= http://127.0.0.1:$(MODEL_PORT)/v1
MODEL_NAME ?= refund-desk-scripted
OPENAI_API_KEY ?= sk-refunddesk-FAKE-7Qm2LxP9vT4rN8cWb3KdYz5H
PAYMENTS_BASE_URL ?= http://127.0.0.1:$(PAYMENTS_PORT)
PAYMENTS_TIMEOUT_MS ?= 1200

# attest's LLM judge (layer 6) talks to the same scripted server.
ATTEST_JUDGE_BASE_URL ?= $(OPENAI_BASE_URL)
ATTEST_JUDGE_MODEL ?= refund-desk-judge
ATTEST_JUDGE_API_KEY ?= scripted-model-server-needs-no-key
