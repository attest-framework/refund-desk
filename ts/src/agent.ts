// Refund Desk agent: an OpenAI chat-completions tool loop over three tools.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  context,
  SpanKind,
  SpanStatusCode,
  trace,
  type Context,
  type Span,
  type Tracer,
} from "@opentelemetry/api";
import OpenAI from "openai";
import type {
  ChatCompletionAssistantMessageParam,
  ChatCompletionMessageParam,
  ChatCompletionTool,
} from "openai/resources/chat/completions";

const AGENT_SPEC = new URL("../../agent-spec/", import.meta.url);
const SYSTEM_PROMPT = readFileSync(fileURLToPath(new URL("system-prompt.txt", AGENT_SPEC)), "utf8").trim();
const TOOLS = JSON.parse(
  readFileSync(fileURLToPath(new URL("tools.json", AGENT_SPEC)), "utf8"),
) as ChatCompletionTool[];
const MAX_MODEL_CALLS = 8;

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
type ToolResult = { [key: string]: Json };

export interface Settings {
  modelBaseUrl: string;
  modelName: string;
  modelApiKey: string;
  paymentsBaseUrl: string;
  paymentsTimeoutMs: number;
}

function positiveInteger(name: string, raw: string): number {
  const value = Number(raw);
  if (!Number.isInteger(value) || value <= 0) throw new Error(`${name} must be a positive integer, got ${raw}`);
  return value;
}

function stringArg(args: Record<string, unknown>, key: string): string {
  const value = args[key];
  if (typeof value !== "string") throw new Error(`tool argument ${key} must be a string`);
  return value;
}

function integerArg(args: Record<string, unknown>, key: string): number {
  const value = args[key];
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new Error(`tool argument ${key} must be an integer`);
  }
  return value;
}

export function settingsFromEnv(): Settings {
  const required = (name: string): string => {
    const value = process.env[name];
    if (!value) throw new Error(`${name} is not set; run through \`make\` or export stack.mk`);
    return value;
  };
  return {
    modelBaseUrl: required("OPENAI_BASE_URL"),
    modelName: required("MODEL_NAME"),
    modelApiKey: required("OPENAI_API_KEY"),
    paymentsBaseUrl: required("PAYMENTS_BASE_URL"),
    paymentsTimeoutMs: positiveInteger("PAYMENTS_TIMEOUT_MS", required("PAYMENTS_TIMEOUT_MS")),
  };
}

/** JSON with sorted keys and no spaces, identical to the Python agent's output. */
export function canonicalJson(value: Json): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const keys = Object.keys(value).sort();
    return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalJson(value[k] as Json)}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

/** Field of a payments response; a missing field is a contract break, so it throws. */
function field(body: { [key: string]: Json }, key: string): Json {
  const value = body[key];
  if (value === undefined) throw new Error(`payments response has no ${key}: ${JSON.stringify(body)}`);
  return value;
}

/** Same derivation as the Python agent: first 16 hex digits of sha256("<order>:<amount>"). */
export function idempotencyKey(orderId: string, amountCents: number): string {
  return createHash("sha256").update(`${orderId}:${amountCents}`).digest("hex").slice(0, 16);
}

function committed(refund: { [key: string]: Json }): ToolResult {
  return {
    refund_id: field(refund, "refund_id"),
    order_id: field(refund, "order_id"),
    amount_cents: field(refund, "amount_cents"),
    status: "committed",
  };
}

class Tools {
  constructor(private readonly settings: Settings) {}

  async call(name: string, args: Record<string, unknown>): Promise<ToolResult> {
    if (name === "lookup_order") return this.lookupOrder(stringArg(args, "order_id"));
    if (name === "issue_refund") {
      return this.issueRefund(
        stringArg(args, "order_id"),
        integerArg(args, "amount_cents"),
        stringArg(args, "reason"),
      );
    }
    if (name === "notify_customer") {
      return this.notifyCustomer(stringArg(args, "order_id"), stringArg(args, "message"));
    }
    throw new Error(`model requested unknown tool ${JSON.stringify(name)}`);
  }

  private async request(
    method: string,
    path: string,
    body?: Json,
    headers: Record<string, string> = {},
  ): Promise<Response> {
    return fetch(`${this.settings.paymentsBaseUrl}${path}`, {
      method,
      headers: { "Content-Type": "application/json", ...headers },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(this.settings.paymentsTimeoutMs),
    });
  }

  private static async json(response: Response): Promise<{ [key: string]: Json }> {
    if (!response.ok) {
      throw new Error(`payments ${response.status}: ${await response.text()}`);
    }
    return (await response.json()) as { [key: string]: Json };
  }

  async lookupOrder(orderId: string): Promise<ToolResult> {
    const response = await this.request("GET", `/orders/${orderId}`);
    if (response.status === 404) return { error: "order_not_found", order_id: orderId };
    const order = await Tools.json(response);
    return {
      order_id: field(order, "order_id"),
      amount_cents: field(order, "amount_cents"),
      currency: field(order, "currency"),
      status: field(order, "status"),
    };
  }

  async issueRefund(orderId: string, amountCents: number, reason: string): Promise<ToolResult> {
    // The key derives from the order and the amount, so a retry of the same refund carries the
    // same key and the payments API answers it with the first refund (INC-1042).
    let response: Response;
    try {
      response = await this.request(
        "POST",
        "/refunds",
        { order_id: orderId, amount_cents: amountCents, reason },
        { "Idempotency-Key": idempotencyKey(orderId, amountCents) },
      );
    } catch (error) {
      if (error instanceof DOMException && error.name === "TimeoutError") {
        return (
          (await this.committedRefund(orderId, amountCents)) ?? {
            error: "payments_timeout",
            order_id: orderId,
          }
        );
      }
      throw error;
    }
    if (response.status === 404 || response.status === 422) {
      const body = (await response.json()) as { error: string };
      return { error: field(body, "error"), order_id: orderId };
    }
    return committed(await Tools.json(response));
  }

  /** The refund the payments API committed before the timeout, if there is one. */
  private async committedRefund(orderId: string, amountCents: number): Promise<ToolResult | null> {
    const response = await this.request("GET", `/refunds?order_id=${encodeURIComponent(orderId)}`);
    if (!response.ok) throw new Error(`payments ${response.status}: ${await response.text()}`);
    const { refunds } = (await response.json()) as { refunds: { [key: string]: Json }[] };
    const match = refunds.find((refund) => refund.amount_cents === amountCents);
    return match === undefined ? null : committed(match);
  }

  async notifyCustomer(orderId: string, message: string): Promise<ToolResult> {
    const response = await this.request("POST", "/notifications", { order_id: orderId, message });
    const body = await Tools.json(response);
    return { notification_id: field(body, "notification_id"), status: "sent" };
  }
}

/**
 * One clock for every span boundary, in epoch milliseconds. The SDK's own default clock
 * rounds each span's start to a millisecond but not its end, so a child can end after
 * its parent and the trace check warns that it runs outside it.
 */
function now(): number {
  return performance.timeOrigin + performance.now();
}

/** Mark a span failed the way Python's start_as_current_span does on an exception. */
function failSpan(span: Span, error: unknown): void {
  span.recordException(error instanceof Error ? error : String(error));
  span.setStatus({ code: SpanStatusCode.ERROR, message: String(error) });
}

/** Handle one customer message and return the agent's reply. */
export async function run(settings: Settings, customerMessage: string, tracer: Tracer): Promise<string> {
  const client = new OpenAI({ baseURL: settings.modelBaseUrl, apiKey: settings.modelApiKey });
  const tools = new Tools(settings);
  const messages: ChatCompletionMessageParam[] = [
    { role: "system", content: SYSTEM_PROMPT },
    { role: "user", content: customerMessage },
  ];
  const root = tracer.startSpan("invoke_agent refund-desk", {
    startTime: now(),
    attributes: { "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "refund-desk" },
  });
  const rootContext = trace.setSpan(context.active(), root);
  try {
    for (let i = 0; i < MAX_MODEL_CALLS; i++) {
      const message = await chat(tracer, rootContext, client, settings.modelName, messages);
      if (!message.tool_calls?.length) {
        const reply = message.content;
        if (typeof reply !== "string") throw new Error("model returned neither tool calls nor text");
        root.setAttribute("refund_desk.reply", reply);
        return reply;
      }
      messages.push(message);
      for (const call of message.tool_calls) {
        if (call.type !== "function") throw new Error(`unsupported tool call type ${call.type}`);
        const content = await executeTool(tracer, rootContext, tools, call);
        messages.push({ role: "tool", tool_call_id: call.id, content });
      }
    }
    throw new Error(`no reply after ${MAX_MODEL_CALLS} model calls`);
  } catch (error) {
    failSpan(root, error);
    throw error;
  } finally {
    root.end(now());
  }
}

async function chat(
  tracer: Tracer,
  parent: Context,
  client: OpenAI,
  model: string,
  messages: ChatCompletionMessageParam[],
): Promise<ChatCompletionAssistantMessageParam> {
  const span = tracer.startSpan(`chat ${model}`, { kind: SpanKind.CLIENT, startTime: now() }, parent);
  try {
    span.setAttribute("gen_ai.operation.name", "chat");
    span.setAttribute("gen_ai.request.model", model);
    const completion = await client.chat.completions.create({ model, messages, tools: TOOLS });
    const choice = completion.choices[0];
    if (choice === undefined) throw new Error("model response has no choices");
    if (completion.usage === undefined) throw new Error("model response has no usage");
    span.setAttribute("gen_ai.response.model", completion.model);
    span.setAttribute("gen_ai.response.finish_reasons", [choice.finish_reason]);
    span.setAttribute("gen_ai.usage.input_tokens", completion.usage.prompt_tokens);
    span.setAttribute("gen_ai.usage.output_tokens", completion.usage.completion_tokens);
    const message: ChatCompletionAssistantMessageParam = {
      role: "assistant",
      content: choice.message.content,
    };
    const calls = choice.message.tool_calls ?? [];
    if (calls.length > 0) {
      message.tool_calls = calls.map((c) => {
        if (c.type !== "function") throw new Error(`unsupported tool call type ${c.type}`);
        return {
          id: c.id,
          type: "function",
          function: { name: c.function.name, arguments: c.function.arguments },
        };
      });
    }
    return message;
  } catch (error) {
    failSpan(span, error);
    throw error;
  } finally {
    span.end(now());
  }
}

async function executeTool(
  tracer: Tracer,
  parent: Context,
  tools: Tools,
  call: { id: string; function: { name: string; arguments: string } },
): Promise<string> {
  const { name, arguments: args } = call.function;
  const span = tracer.startSpan(`execute_tool ${name}`, { startTime: now() }, parent);
  try {
    span.setAttribute("gen_ai.operation.name", "execute_tool");
    span.setAttribute("gen_ai.tool.name", name);
    span.setAttribute("gen_ai.tool.call.id", call.id);
    span.setAttribute("gen_ai.tool.call.arguments", args);
    const result = await tools.call(name, JSON.parse(args) as Record<string, unknown>);
    const content = canonicalJson(result);
    span.setAttribute("gen_ai.tool.call.result", content);
    if ("error" in result) {
      span.setAttribute("error.type", String(result.error));
      span.setStatus({ code: SpanStatusCode.ERROR });
    }
    return content;
  } catch (error) {
    failSpan(span, error);
    throw error;
  } finally {
    span.end(now());
  }
}
