# 00 · 研究目标、范围与度量术语

**状态**：架构规格 v0.1，2026-11-18；未实施、未实机测量。

## 0.1 研究问题
给定 Mac 运行 Pi Coding Agent（管理会话和本地工具），Ubuntu 运行可替换模型的 vLLM，如何在同一个局域网中，让每轮请求尽量只上传新增上下文，而 vLLM 最终接收的逻辑请求与原生模式完全相同？

## 0.2 不可混用的四种量
| 量 | 定义 | 负责组件 | 是否被 Delta 直接减少 |
|---|---|---|---|
| `pi_serialized_bytes` | Pi 生成的完整 Provider 请求 JSON 的 UTF-8 字节 | Pi | 否；用来做完整基线 |
| `mac_wire_bytes` | Mac → Ubuntu 实际 TCP/IP 应用负载/链路字节（注明口径） | 双端抓包/采样 | 是，目标 |
| `gateway_upstream_bytes` | Gateway → vLLM 的 HTTP 请求正文大小 | Gateway | 初版通常否 |
| `prompt_tokens` | vLLM chat template + tokenizer 渲染后逻辑输入 token 数量 | vLLM | **不应**因等价 Delta 减少 |
| `prefix_cached_tokens` | 实际复用的此前 KV 前缀（若该版本可观测） | vLLM | 间接且不保证 |
| `TTFT` | 从网络发起请求至收到首个文本/内容增量的耗时 | 客户端 | 可能变化 |
| `prefill_ms / decode_tps` | GPU 预填充 / 解码性能 | vLLM | Delta 不直接保证 |

**关键**：一个 token 是模型 tokenizer 的单位，不是网络协议必须传输的二进制单元。Pi 通常发送 JSON 字符串，vLLM 端再 tokenize；传输 Token IDs 仍可重复上传所有旧 ID，不自动解决问题。

## 0.3 范围（in scope）
- macOS / Ubuntu 同 LAN；P0 使用 SSH 本地端口转发，端口 8000 和 18080 只在 Ubuntu loopback 暴露。
- 模型默认 `Qwen/Qwen3-0.6B`，推理后端 `vLLM`，模型/上下文/输出上限可配置。
- Pi 原生请求基线、gzip 压缩基线、自定义 Delta、Delta+gzip；工具调用与流式 SSE。
- 单用户、一条主分支起步；逐步覆盖 compact、fork、终止、重启、冲突、多会话。
- SQLite 存储 Gateway *已接受的完整请求快照*、分支 revision/哈希和幂等请求日志。
- 定量基准、协议 Schema、故障测试、日志隐私。

## 0.4 非目标（out of scope, v1）
- 不改 vLLM 的 KV Page Manager / GPU 内核，不在 Mac 维护 KV Cache。
- 不承诺 Qwen3-0.6B 能稳定自主完成复杂 coding agent 任务；简单 tool-calling smoke test 与传输正确性分别验收。
- 不对外暴露多租户 API，不解决 WAN/CDN 负载均衡。
- 不把语义摘要、RAG 裁剪视为“等价网络传输”。
- 不做自定义二进制 Token ID 协议、跨推理进程共享 KV 或把 vLLM 的进程内 Responses Store 当成唯一可靠数据库。
- 不承诺 exactly-once 的 Mac 本地工具执行。

## 0.5 核心不变量
令 P 为 Pi 在 **full 基线** 将发送的完整下游 Chat Completions 请求，S 为 Gateway 上个已确认快照，D 为客户端 Delta，则：

```text
CanonicalJSON(Apply(S, D)) == CanonicalJSON(P)
SHA256(CanonicalJSON(Apply(S, D))) == expected_request_sha256
```

要求字段和值一致，包括消息顺序、工具调用 ID、工具 schema、采样参数、chat-template kwargs；禁止将“LLM 输出差不多”替代为正确性检查。规范化应固定 RFC 8785/JCS 风格的确定性 JSON 规则；跨语言对 Unicode、浮点、null 和数组进行测试。

## 0.6 成功判定
- P0：Mac 可通过隧道访问 Ubuntu 模型，文本成功；工具调用作为独立可选门槛。
- P1：能记录四层大小、RTT/TTFT、版本指纹，gzip 对照工作。
- P2：多轮请求重新构建的完整请求 hash 相同；有真实流量下降（不预设固定百分比）。
- P3：异常后既不静默丢失上下文也不错误执行旧请求，必要时 full resync。
- P4：在相同固定回放工作负载中报告中位数、p95、原始记录/脚本，明确模型质量与协议质量分离。

## 0.7 威胁模型/环境前提
LAN 不是天然安全网络；同网段其他设备可能探测端口，任何具有模型服务访问权的用户可能送入任意代码/提示词。默认使用 SSH Tunnel，权限最小化，禁止公网暴露。详细见 [09-security](09-security.md)。
