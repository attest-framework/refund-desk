# Local stack settings, read by the Makefile and exported to every command.
# `?=` lets an exported environment variable override a value.
#
# Synthetic: the model is scripted (model-server/server.py) and payments are an attest
# world (world/*.world.yaml) that every run hosts for itself and that puts its own
# base URL in PAYMENTS_BASE_URL. The API key below is a planted fake that the
# scripted server ignores (it looks like a real key so capture's redaction has something
# to catch); no paid model is called.
MODEL_PORT ?= 8790
OPENAI_BASE_URL ?= http://127.0.0.1:$(MODEL_PORT)/v1
MODEL_NAME ?= refund-desk-scripted
OPENAI_API_KEY ?= sk-refunddesk-FAKE-7Qm2LxP9vT4rN8cWb3KdYz5H
PAYMENTS_TIMEOUT_MS ?= 1200
# Which agent-spec/ version the agents run: 1 is agent-spec/ itself (INC-1042), 2 is agent-spec/v2/.
AGENT_SPEC_VERSION ?= 1

# attest's LLM judge (layer 6) talks to the same scripted server.
ATTEST_JUDGE_BASE_URL ?= $(OPENAI_BASE_URL)
ATTEST_JUDGE_MODEL ?= refund-desk-judge
ATTEST_JUDGE_API_KEY ?= scripted-model-server-needs-no-key
