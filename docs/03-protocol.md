# 03 · pi-delta/v1 有状态传输协议（拟实现）

**状态**：Draft，非 vLLM/Pi 原生 API。正式输入输出 Schema 位于 [protocol/pi-delta-v1.schema.json](../protocol/pi-delta-v1.schema.json)。首次版本仅处理 OpenAI Chat Completions JSON（text + tools）；多模态作为未来扩展。

## 3.1 请求路径
- `GET /delta/v1/capabilities`：公开协议版本、支持的压缩类型、最大消息/请求体限制、服务端实例指纹；需认证时也遵循同一身份控制。
- `POST /delta/v1/infer`：接受 snapshot 或 delta，成功返回标准 Chat Completions `text/event-stream`。
- `GET /healthz`：存活；`GET /readyz`：验证 SQLite + upstream 可用。
- 服务器 **不得直接转发** `protocol`、`session_id`、`delta`、`expected_request_sha256` 等自定义字段给 vLLM；由 Gateway 完成重建和字段白名单校验。
- 压缩通过 `Content-Encoding: gzip` 选择，与请求 `kind` 正交。拒绝不支持的编码及解压炸弹。

## 3.2 必选公共字段
| 字段 | 含义 |
|---|---|
| `protocol` | 固定 `pi-delta/v1` |
| `request_id` | 全局唯一，作为幂等键；重复 ID + 不同正文拒绝 |
| `session_id` / `branch_id` | 客户端随机标识；分支独立 |
| `kind` | `full` 或 `delta` |
| `base_revision` / `base_hash` | delta 的上一次已接受请求版本与 hash；full 为 null |
| `model_fingerprint` | 模型权重、tokenizer、chat template、推理行为配置的稳定指纹 |
| `expected_request_sha256` | 用**完整重建请求**计算的 SHA-256 |
| `full` / `delta` | 仅出现对应 `kind` 的数据 |

SHA-256 字符串格式统一为 `sha256:<64 hex digits>`。版本从 1 起；同一 `session+branch` 每成功接受一个不同的完整输入请求增加 1。`base_hash` 指上一次已接受的完整请求哈希，**不是模型响应哈希**。

### 3.2.1 Full resync 的分支代际规则（强制）

`kind=full` **仅允许新建尚不存在的传输 branch_id**。如果 `(session_id, branch_id)` 已存在，除相同 request_id 的幂等处理以外，返回 `409 BRANCH_ALREADY_EXISTS`，不覆盖当前 revision。首次 full 创建 revision=1。

版本冲突、session 过期、模型变更、断线状态不明：客户端使用**新的传输 branch_id（随机 UUID）和新的 request_id**上传完整请求；本地维护 `Pi logical branch → active transport branch_id` 映射。旧分支在 TTL 到期前保持独立，迟到的 Delta 无法写到新分支。该规则应纳入 L2 状态机测试。

## 3.3 Snapshot 首次同步
```json
{
  "protocol": "pi-delta/v1",
  "request_id": "e3ba4c86-4ce4-4395-9a12-d165b5ce99b8",
  "session_id": "e67fd86c-74c4-408f-ad49-c25b38e9b641",
  "branch_id": "main",
  "kind": "full",
  "base_revision": null,
  "base_hash": null,
  "model_fingerprint": "qwen3-0.6b@pinned-image+template-v1",
  "expected_request_sha256": "sha256:REPLACE_WITH_CANONICAL_DIGEST",
  "full": {
    "request": {
      "model": "qwen3-0.6b",
      "messages": [{"role": "user", "content": "hello"}],
      "stream": true,
      "max_tokens": 128
    }
  }
}
```

示例中的 `expected_request_sha256` 是**占位符，不满足正式 Schema**；真实客户端必须计算 64 位十六进制哈希后才能发送。

## 3.4 Delta 增量
```json
{
  "protocol": "pi-delta/v1",
  "request_id": "04606c34-ea2e-4f86-bd2b-e0981372ca0a",
  "session_id": "e67fd86c-74c4-408f-ad49-c25b38e9b641",
  "branch_id": "main",
  "kind": "delta",
  "base_revision": 1,
  "base_hash": "sha256:PREVIOUS_REQUEST_DIGEST",
  "model_fingerprint": "qwen3-0.6b@pinned-image+template-v1",
  "expected_request_sha256": "sha256:RECONSTRUCTED_REQUEST_DIGEST",
  "delta": {
    "keep_count": 1,
    "append_messages": [
      {"role": "assistant", "content": "Hi"},
      {"role": "user", "content": "Continue"}
    ],
    "envelope": {
      "kind": "ref",
      "sha256": "sha256:PRIOR_ENVELOPE_DIGEST"
    }
  }
}
```

这里各 SHA 同样为人类可读占位符。`keep_count` 只表示保留上个请求 `messages` 数组的前 N 条消息，并不基于 token 个数。新请求 = `old.messages.slice(0, N) + append_messages`。包含消息之外全部字段的 `envelope` 由以下方式处理：
- `ref`：引用上一版 Envelope，需验证 SHA；
- `replace`：上传完整新 Envelope（如 tools、model、stream、sampling、chat_template_kwargs 变化），不能静默沿用旧设置。

Delta **不依赖** 每轮仅追加：compact、用户编辑和 branch 可能改变中间历史，`keep_count=0` 等价替换全部消息；当 Delta 大于 full 时可直接发送 full。

## 3.5 规范化与哈希
- 采用确定性 JSON 规范化（优先 RFC 8785/JCS），输入为要发给 vLLM 的**完整 OpenAI 请求对象**。
- key 顺序可标准化，数组顺序不可改变；保留数字精度、Unicode、字符串内容与 null/省略区别。
- `envelope = request 去掉 messages`，也单独计算规范化哈希。
- hash 范围不包括传输封装字段、gzip 格式、SSE headers；包括 all server-facing generation/config fields。
- `model_fingerprint` 不是可信的客户端声明。Gateway 必须与它根据当前已锁定模型权重、tokenizer、模板、解析器及部署参数计算出的**服务端权威指纹**核对，不能只依赖请求字段。
- 对无法规范化的数据（非 JSON、NaN、重复键）拒绝请求。
- OpenAI 不认识的字段必须由明确的兼容规则保留或拒绝，绝不能悄悄丢弃，以免误称等价。

## 3.6 响应与 ACK 语义
成功响应：`Content-Type: text/event-stream`，并返回 `X-Pi-Delta-Revision` 和 `X-Pi-Delta-Request-Hash`；这些头表示 Gateway 已**接纳并存储请求输入快照**，不表示模型完成、工具执行完成，也不保证所有 SSE 帧已被客户端收到。SSE 内容对 Pi 必须保持上游 Chat Completions 语义（data chunks + terminal [DONE]）。

请求状态/异常：先于流开始时以 JSON 错误返回，并包含 `code`、`request_id`、`server_revision`（可披露时）、`retryable`，不返回完整 Prompt。

| HTTP | code | 客户端行为 |
|---|---|---|
| 400 | `UNSUPPORTED_PROTOCOL`/`INVALID_REQUEST` | 关闭 delta 或修复版本 |
| 409 | `VERSION_CONFLICT`/`IDEMPOTENCY_CONFLICT` | 停止发送；full resync |
| 410 | `SESSION_EXPIRED` | full resync |
| 413 | `PAYLOAD_TOO_LARGE` | 限制/调整，不自动静默删上下文 |
| 415 | `UNSUPPORTED_ENCODING` | 使用不压缩请求 |
| 422 | `HASH_MISMATCH`/`INVALID_ENVELOPE` | 停止，记录差异诊断（不记录正文） |
| 429/503 | `OVERLOADED`/`UPSTREAM_UNAVAILABLE` | 有界指数退避；必要时 full resync |

## 3.7 版本协议与扩展
客户端先向 capabilities 获取协议版本、`max_request_bytes` 和 `max_decompressed_bytes`。若不兼容，**fail closed → 原生 full**；不能对不支持的服务端尝试 Delta。新增可选字段必须有安全默认，破坏兼容的变更提升协议版本。

## 3.8 压缩安全
Gzip 传输对象可为 full/delta JSON；记录压缩前长度、压缩后 body 长度、network capture。限制压缩 ratio、最大解压字节及 CPU 时间，防止压缩炸弹。SSE gzip 作为独立可选实验，不默认开启以免破坏逐 token 低延迟。

## 3.9 Token ID 不在 v1 范围内
v1 的发送单位是 JSON 消息，不是模型 token ids。上传原始 token IDs 会增加 tokenizer/chat template 一致性约束，且不减少重复旧 ID 的传输；未来需单独 ADR 与对照基准。
