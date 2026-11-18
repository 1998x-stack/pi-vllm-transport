import test from "node:test";
import assert from "node:assert/strict";
import extension, { sha } from "./index.ts";

const session = {
  model: { provider: "lan-delta" },
  sessionManager: { getSessionId: () => "pi-logical-session" },
};
const req = (messages) => ({
  model: "qwen3-0.6b", messages, stream: true, max_tokens: 64,
  tools: [{ type: "function", function: { name: "sum", parameters: { type: "object" } } }],
});

test("canonical SHA stable across key order", () => {
  assert.equal(sha({ b: [1, "中文", null], a: true }), sha({ a: true, b: [1, "中文", null] }));
});

test("delta hook: full handshake then incremental request", async () => {
  const hooks = {};
  extension({ on(name, fn) { hooks[name] = fn; } });
  assert.ok(hooks.before_provider_headers);
  assert.ok(hooks.before_provider_request);
  assert.ok(hooks.after_provider_response);

  const first = req([{ role: "user", content: "A".repeat(10000) }]);
  const headers1 = {};
  hooks.before_provider_headers({ headers: headers1 }, session);
  assert.equal(headers1["X-Pi-Delta-Mode"], "full");
  const result1 = hooks.before_provider_request({ payload: first }, session);
  assert.deepEqual(result1, first);
  await hooks.after_provider_response({
    status: 200, headers: {
      "x-pi-delta-request-id": headers1["X-Pi-Delta-Request-Id"],
      "x-pi-delta-request-hash": sha(first),
      "x-pi-delta-revision": "1",
    },
  }, session);

  const second = req([...first.messages,
    { role: "assistant", content: "OK" },
    { role: "user", content: "Continue" }]);
  const headers2 = {};
  hooks.before_provider_headers({ headers: headers2 }, session);
  assert.equal(headers2["X-Pi-Delta-Mode"], "delta");
  const result2 = hooks.before_provider_request({ payload: second }, session);
  assert.equal(result2.messages.length, 1);
  const packet = JSON.parse(result2.messages[0].content);
  assert.equal(packet.protocol, "pi-delta/v1");
  assert.equal(packet.kind, "delta");
  assert.equal(packet.base_revision, 1);
  assert.equal(packet.base_hash, sha(first));
  assert.equal(packet.delta.keep_count, 1);
  assert.equal(packet.delta.append_messages.length, 2);
  assert.equal(packet.expected_request_sha256, sha(second));
  assert.ok(Buffer.byteLength(JSON.stringify(result2)) < Buffer.byteLength(JSON.stringify(second)));
  assert.equal(packet.delta.envelope.kind, "ref");

  await hooks.after_provider_response({
    status: 200, headers: {
      "x-pi-delta-request-id": headers2["X-Pi-Delta-Request-Id"],
      "x-pi-delta-request-hash": sha(second),
      "x-pi-delta-revision": "2",
    },
  }, session);

  const third = req([{ role: "user", content: "Edited earlier history" }]);
  const headers3 = {};
  hooks.before_provider_headers({ headers: headers3 }, session);
  const result3 = hooks.before_provider_request({ payload: third }, session);
  const packet3 = JSON.parse(result3.messages[0].content);
  assert.equal(packet3.delta.keep_count, 0);

  // A failed response or missing ACK MUST force a new full snapshot branch.
  hooks.after_provider_response({ status: 409, headers: {} }, session);
  const headers4 = {};
  hooks.before_provider_headers({ headers: headers4 }, session);
  assert.equal(headers4["X-Pi-Delta-Mode"], "full");
  assert.notEqual(headers4["X-Pi-Delta-Branch"], headers3["X-Pi-Delta-Branch"]);
});

test("unknown provider is not rewritten", () => {
  const hooks = {};
  extension({ on(name, fn) { hooks[name] = fn; } });
  const other = { model: { provider: "other" }, sessionManager: session.sessionManager };
  const headers = {};
  assert.equal(hooks.before_provider_headers({ headers }, other), undefined);
  assert.deepEqual(headers, {});
});
