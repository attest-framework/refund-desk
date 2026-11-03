"""Refund Desk agent: an OpenAI chat-completions tool loop over three tools."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

AGENT_SPEC = Path(__file__).resolve().parents[3] / "agent-spec"
SYSTEM_PROMPT = (AGENT_SPEC / "system-prompt.txt").read_text().strip()
TOOLS: list[dict[str, Any]] = json.loads((AGENT_SPEC / "tools.json").read_text())
MAX_MODEL_CALLS = 8


@dataclass(frozen=True)
class Settings:
    model_base_url: str
    model_name: str
    model_api_key: str
    payments_base_url: str
    payments_timeout_s: float

    @classmethod
    def from_env(cls) -> Settings:
        def required(name: str) -> str:
            value = os.environ.get(name)
            if not value:
                raise RuntimeError(f"{name} is not set; run through `make` or export stack.mk")
            return value

        return cls(
            model_base_url=required("OPENAI_BASE_URL"),
            model_name=required("MODEL_NAME"),
            model_api_key=required("OPENAI_API_KEY"),
            payments_base_url=required("PAYMENTS_BASE_URL"),
            payments_timeout_s=int(required("PAYMENTS_TIMEOUT_MS")) / 1000,
        )


def canonical_json(value: Any) -> str:
    """JSON with sorted keys and no spaces, identical to the TS agent's output."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Tools:
    def __init__(self, settings: Settings) -> None:
        self.http = httpx.Client(
            base_url=settings.payments_base_url, timeout=settings.payments_timeout_s
        )

    def close(self) -> None:
        self.http.close()

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "lookup_order":
            return self.lookup_order(args["order_id"])
        if name == "issue_refund":
            return self.issue_refund(args["order_id"], args["amount_cents"], args["reason"])
        if name == "notify_customer":
            return self.notify_customer(args["order_id"], args["message"])
        raise ValueError(f"model requested unknown tool {name!r}")

    def lookup_order(self, order_id: str) -> dict[str, Any]:
        response = self.http.get(f"/orders/{order_id}")
        if response.status_code == 404:
            return {"error": "order_not_found", "order_id": order_id}
        response.raise_for_status()
        order = response.json()
        return {
            "order_id": order["order_id"],
            "amount_cents": order["amount_cents"],
            "currency": order["currency"],
            "status": order["status"],
        }

    def issue_refund(self, order_id: str, amount_cents: int, reason: str) -> dict[str, Any]:
        # No idempotency key: a retry after a timeout is a new refund (INC-1042).
        try:
            response = self.http.post(
                "/refunds",
                json={"order_id": order_id, "amount_cents": amount_cents, "reason": reason},
            )
        except httpx.TimeoutException:
            return {"error": "payments_timeout", "order_id": order_id}
        if response.status_code in (404, 422):
            return {"error": response.json()["error"], "order_id": order_id}
        response.raise_for_status()
        refund = response.json()
        return {
            "refund_id": refund["refund_id"],
            "order_id": refund["order_id"],
            "amount_cents": refund["amount_cents"],
            "status": "committed",
        }

    def notify_customer(self, order_id: str, message: str) -> dict[str, Any]:
        response = self.http.post("/notifications", json={"order_id": order_id, "message": message})
        response.raise_for_status()
        return {"notification_id": response.json()["notification_id"], "status": "sent"}


def run(settings: Settings, customer_message: str, tracer: trace.Tracer) -> str:
    """Handle one customer message and return the agent's reply."""
    client = OpenAI(base_url=settings.model_base_url, api_key=settings.model_api_key)
    tools = Tools(settings)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": customer_message},
    ]
    try:
        with tracer.start_as_current_span(
            "invoke_agent refund-desk",
            attributes={
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.agent.name": "refund-desk",
            },
        ) as root:
            for _ in range(MAX_MODEL_CALLS):
                message = chat(tracer, client, settings.model_name, messages)
                if not message.get("tool_calls"):
                    reply = message["content"]
                    if not isinstance(reply, str):
                        raise RuntimeError("model returned neither tool calls nor text")
                    root.set_attribute("refund_desk.reply", reply)
                    return reply
                messages.append(message)
                for call in message["tool_calls"]:
                    content = execute_tool(tracer, tools, call)
                    messages.append(
                        {"role": "tool", "tool_call_id": call["id"], "content": content}
                    )
            raise RuntimeError(f"no reply after {MAX_MODEL_CALLS} model calls")
    finally:
        tools.close()
        client.close()


def chat(
    tracer: trace.Tracer, client: OpenAI, model: str, messages: list[dict[str, Any]]
) -> dict[str, Any]:
    with tracer.start_as_current_span(f"chat {model}", kind=SpanKind.CLIENT) as span:
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.request.model", model)
        completion = client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            tools=TOOLS,  # type: ignore[arg-type]
        )
        choice = completion.choices[0]
        span.set_attribute("gen_ai.response.model", completion.model)
        span.set_attribute("gen_ai.response.finish_reasons", [choice.finish_reason])
        if completion.usage is None:
            raise RuntimeError("model response has no usage")
        span.set_attribute("gen_ai.usage.input_tokens", completion.usage.prompt_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", completion.usage.completion_tokens)
        message: dict[str, Any] = {"role": "assistant", "content": choice.message.content}
        if choice.message.tool_calls:
            calls = []
            for c in choice.message.tool_calls:
                if c.type != "function":
                    raise RuntimeError(f"unsupported tool call type {c.type!r}")
                calls.append(
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.function.name, "arguments": c.function.arguments},
                    }
                )
            message["tool_calls"] = calls
        return message


def execute_tool(tracer: trace.Tracer, tools: Tools, call: dict[str, Any]) -> str:
    name = call["function"]["name"]
    arguments = call["function"]["arguments"]
    with tracer.start_as_current_span(f"execute_tool {name}") as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", name)
        span.set_attribute("gen_ai.tool.call.id", call["id"])
        span.set_attribute("gen_ai.tool.call.arguments", arguments)
        result = tools.call(name, json.loads(arguments))
        content = canonical_json(result)
        span.set_attribute("gen_ai.tool.call.result", content)
        if "error" in result:
            span.set_attribute("error.type", result["error"])
            span.set_status(Status(StatusCode.ERROR))
        return content
