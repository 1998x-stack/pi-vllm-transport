# 02 · Pi 客户端接入设计

## 2.1 官方接口选择
根据 [Pi Models Configuration](https://docs.pi.dev/latest/models-configuration)、[Extensions](https://docs.pi.dev/latest/extensions)、[Custom Providers](https://docs.pi.dev/latest/custom-provider)（核对日期：2026-11-18）：
- P0：`~/.pi/agent/models.json` 添加兼容 OpenAI 的自定义模型，`api: "openai-completions"`。
- P1：通过 `before_provider_request` 观测**最终 Provider payload** 字节数。该钩子在构造请求后执行，但记录的是本地序列化估算而非抓包 wire bytes。
- P2：优先尝试小型 SPIKE，使用 `before_provider_request` 重写发往自建 Gateway 的 body，**仅在实测 SDK 不丢弃自定义字段且 SSE 完全兼容时**保留。
- 正式自定义协议可能需要 `pi.registerProvider` + `streamSimple`（规范化 TranscriptContext），按 Pi 文档维护 start/text/thinking/toolcall/done/error 事件与 AbortSignal；不得假设 hook 一定能改写任意 SDK body。
- 若更换自定义 Provider 的转换逻辑，golden reference 必须用同一转换器 full 模式导出的请求，不得拿不同 Pi 转换器的 payload 做 hash 对比。

## 2.2 P0 接入
`configs/models.pi.example.json` 是基线模板，合并到 Mac 的 `~/.pi/agent/models.json`；不要覆盖已有模型。SSH 转发后 Pi 的 `baseUrl` 指向 `http://127.0.0.1:8000/v1`。选择模型后执行文本和最简单的工具调用 smoke test。

## 2.3 Extension / Provider 内部模块
```text
client/pi-delta/  (P2 规划，尚未实现)
  index.ts               注册 Pi provider / hooks
  full-renderer.ts       生成与 full 基线一致的 OpenAI 请求
  canonical.ts           规范化与 SHA-256
  sync-state.ts          每个 session/branch 的 last-ack revision/hash/snapshot
  diff.ts                公共消息前缀比较、replace_suffix
  transport.ts           HTTP / gzip / AbortSignal
  event-adapter.ts       将 Gateway SSE 正确转成 Pi StreamEvent
  recovery.ts            冲突、断线、失效后重新 full sync
  telemetry.ts           长度和延迟统计（不记录正文）
```

## 2.4 快照算法（设计伪代码）
```typescript
function makeRequest(previous, current, ackRevision) {
  if (!previous || !ackRevision) return full(current);
  const old = previous.messages;
  const next = current.messages;
  let keep = 0;
  while (keep < old.length && keep < next.length &&
         hashCanonical(old[keep]) === hashCanonical(next[keep])) keep++;
  const oldEnvelope = omit(previous, "messages");
  const nextEnvelope = omit(current, "messages");
  const envelope = equalCanonical(oldEnvelope, nextEnvelope)
      ? { kind: "ref", sha256: hashCanonical(oldEnvelope) }
      : { kind: "replace", value: nextEnvelope };
  return delta({ keep_count: keep,
                 append_messages: next.slice(keep),
                 envelope,
                 expected_request_sha256: hashCanonical(current) });
}
```

**注意**：以上代码为协议算法示意，非可运行 Pi Extension。现有响应已完成与 Pi 本地持久化动作之间可能出现断点；只在服务器明确接受并返回 revision 后更新 last-ack，本地持久化要原子化。发起请求前禁止乐观地将未确认 revision 标记为已同步。

## 2.5 Session 与 Branch 身份
- `client_id` 由 Mac 本地生成随机 UUID，并持久化；不使用硬件序列号。
- `session_id` 应绑定 Pi 的会话标识，但不用暴露敏感工作区路径。
- `branch_id` 是传输代际的稳定随机 ID；本地维护 Pi logical branch → active transport_branch_id 映射。fork 使用新传输分支；full resync 也必须创建新的 transport_branch_id，而不是重置旧 revision。
- 请求必须包含 `request_id`（随机 UUID）；同一 ID 的内容不可改变。
- 当 Pi compact、edited prompt、重试改写、模型切换、工具 schema 或 chat template 变化时，检测并使用 replace_suffix 或 full snapshot。

## 2.6 事件与错误
- 请求层：`409 VERSION_CONFLICT`、`410 SESSION_EXPIRED`、`422 HASH_MISMATCH`、`429`、`5xx`。
- 响应层：保留 Chat Completions 的 SSE 流式语义，包括 tool_calls 的 partial function arguments。
- 客户端仅在收到完整响应的 terminal event 后把 assistant 记录交给 Agent 正常入历史；对于不完整工具调用不执行。
- 不能从 SSE 头的 200 或 Gateway 的 ACK 推出模型生成完成。
- 失败/不确定状态时，采用新 request_id 和新 transport_branch_id 的全量快照重建，并禁止静默继续使用未确认的上下文。

## 2.7 模式开关
`full`、`gzip`、`delta`、`delta-gzip` 四模式共享相同上游请求 renderer。支持客户端 kill switch `PI_TRANSPORT_MODE=full`，保证出错时能够立即退回 P0。

## 2.8 与 Pi 新版本的兼容
锁定 Pi commit + 扩展 API 版本并做 startup self-check。版本升级后先跑 Provider payload golden corpus（文本、多工具、thinking、compact、分支、取消）；CI 不通过即禁用 delta。扩展可能获得敏感凭据与 prompt，必须审计依赖并严格脱敏。
