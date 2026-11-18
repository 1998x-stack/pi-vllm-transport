/**
 * Experimental Pi extension: send only suffix deltas over Pi's existing
 * OpenAI Chat Completions transport. The gateway unwraps a single user message
 * containing the pi-delta/v1 packet and reconstructs the original payload.
 *
 * IMPORTANT: Requires a Pi build that supports before_provider_headers,
 * before_provider_request and after_provider_response for openai-completions.
 * Use --extension client/pi-delta/index.ts and select provider "lan-delta".
 * Pi's SDK still owns SSE decoding and tool execution.
 */
import { createHash, randomUUID } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
type Request = Record<string, any>;
type State = {
  sessionId: string;
  branchId: string;
  revision: number;
  requestHash: string | null;
  snapshot: Request | null;
  pending: null | {
    requestId: string;
    hash: string;
    request: Request;
  };
};

const states = new Map<string, State>();
const provider = "lan-delta";
const fingerprint = process.env.PI_DELTA_MODEL_FINGERPRINT ?? "qwen3-0.6b@v1";
const mode = process.env.PI_DELTA_MODE === "full" ? "full" : "delta";

function canonical(value: any): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return "[" + value.map((item) => canonical(item)).join(",") + "]";
  }
  return "{" + Object.keys(value).sort().map(
    (key) => JSON.stringify(key) + ":" + canonical(value[key])
  ).join(",") + "}";
}
function sha(value: any): string {
  return "sha256:" + createHash("sha256").update(canonical(value), "utf8").digest("hex");
}
function jsonClone(value: any): any {
  // Match the wire's omission of undefined; JSON-only protocol.
  return JSON.parse(JSON.stringify(value));
}
function env(req: Request): Request {
  const { messages: _messages, ...envelope } = req;
  return envelope;
}
function diff(before: Request, after: Request) {
  let keep = 0;
  while (keep < Math.min(before.messages.length, after.messages.length)
    && sha(before.messages[keep]) === sha(after.messages[keep])) keep++;
  const oldEnv = env(before), newEnv = env(after);
  return {
    keep_count: keep,
    append_messages: after.messages.slice(keep),
    envelope: sha(oldEnv) === sha(newEnv)
      ? { kind: "ref", sha256: sha(oldEnv) }
      : { kind: "replace", value: newEnv },
  };
}
function sessionKey(ctx: any): string {
  return String(ctx.sessionManager?.getSessionId?.() ?? "unbound-session");
}
function getState(ctx: any): State {
  const key = sessionKey(ctx);
  let state = states.get(key);
  if (!state) {
    state = { sessionId: randomUUID(), branchId: randomUUID(), revision: 0,
      requestHash: null, snapshot: null, pending: null };
    states.set(key, state);
  }
  return state;
}
function reset(state: State) {
  state.branchId = randomUUID();
  state.revision = 0;
  state.requestHash = null;
  state.snapshot = null;
  state.pending = null;
}
function lowerHeader(headers: Record<string, string>, name: string): string | undefined {
  const hit = Object.entries(headers).find(([key]) => key.toLowerCase() === name);
  return hit?.[1];
}
function isOurs(ctx: any): boolean {
  return ctx.model?.provider === provider;
}

export default function (pi: ExtensionAPI) {
  pi.on("before_provider_headers", (event, ctx) => {
    if (!isOurs(ctx)) return;
    const state = getState(ctx);
    // If the last HTTP request never yielded an acknowledged response, fail closed.
    if (state.pending) reset(state);
    const requestId = randomUUID();
    state.pending = { requestId, hash: "", request: {} };
    event.headers["X-Pi-Delta-Wire"] = "pi-delta/v1";
    event.headers["X-Pi-Delta-Mode"] = state.snapshot && mode === "delta" ? "delta" : "full";
    event.headers["X-Pi-Delta-Session"] = state.sessionId;
    event.headers["X-Pi-Delta-Branch"] = state.branchId;
    event.headers["X-Pi-Delta-Request-Id"] = requestId;
    event.headers["X-Pi-Delta-Model-Fingerprint"] = fingerprint;
  });

  pi.on("before_provider_request", (event, ctx) => {
    if (!isOurs(ctx)) return;
    const state = getState(ctx);
    const pending = state.pending;
    if (!pending) return; // Safer to preserve native payload than invent a delta.
    const current = jsonClone(event.payload);
    if (typeof current !== "object" || !Array.isArray(current.messages)
        || typeof current.model !== "string" || current.stream !== true) {
      return;
    }
    pending.hash = sha(current);
    pending.request = current;
    const old = state.snapshot;
    if (!old || mode !== "delta") {
      if (process.env.PI_DELTA_DEBUG === "1") {
        console.error("[pi-delta] full bytes=" + Buffer.byteLength(JSON.stringify(current)));
      }
      return current;
    }
    const packet = {
      protocol: "pi-delta/v1",
      request_id: pending.requestId,
      session_id: state.sessionId,
      branch_id: state.branchId,
      kind: "delta",
      base_revision: state.revision,
      base_hash: state.requestHash,
      model_fingerprint: fingerprint,
      expected_request_sha256: pending.hash,
      delta: diff(old, current),
    };
    const wrapped = {
      model: current.model,
      stream: true,
      messages: [{ role: "user", content: JSON.stringify(packet) }],
    };
    if (process.env.PI_DELTA_DEBUG === "1") {
      console.error(
        "[pi-delta] full=" + Buffer.byteLength(JSON.stringify(current))
        + " delta=" + Buffer.byteLength(JSON.stringify(wrapped))
      );
    }
    return wrapped;
  });

  pi.on("after_provider_response", (event, ctx) => {
    if (!isOurs(ctx)) return;
    const state = getState(ctx);
    const pending = state.pending;
    if (!pending) return;
    const headers = event.headers as Record<string, string>;
    const gotId = lowerHeader(headers, "x-pi-delta-request-id");
    const gotHash = lowerHeader(headers, "x-pi-delta-request-hash");
    const gotRev = Number(lowerHeader(headers, "x-pi-delta-revision"));
    if (event.status === 200 && gotId === pending.requestId
      && gotHash === pending.hash && Number.isSafeInteger(gotRev)
      && gotRev === state.revision + 1) {
      state.snapshot = pending.request;
      state.requestHash = pending.hash;
      state.revision = gotRev;
      state.pending = null;
      return;
    }
    // If headers are missing, reordered or invalid, never reuse a stale prefix.
    reset(state);
  });
}
