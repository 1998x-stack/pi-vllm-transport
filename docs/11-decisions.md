# 11 · Architecture Decision Records / 风险登记

## ADR-001：增量状态置于 Ubuntu Gateway，而不是 vLLM 内核
**状态**：选定（设计）。原因：Gateway 与 vLLM 同机，Mac→Ubuntu 可只传变化；Gateway 完整重建标准 API，复用 vLLM 前缀缓存而不耦合 CUDA/KV 管理。代价：新增存储、一致性和故障处理成本。

## ADR-002：首版用 SQLite
**状态**：选定（设计）。单 Mac/单 Ubuntu/小并发足够；事务、WAL、备份、TTL。超出并发与规模再迁移 Redis/PostgreSQL，不为实验引入多机复杂度。

## ADR-003：原生 Pi + full 作为 golden
**状态**：选定（设计）。模型每次完整请求语义不能变化。不同 Provider renderer 不一定生成相同 JSON；如 Custom Provider 改写 renderer，必须从该 renderer 导出 baseline，保持同一路径比对。

## ADR-004：先 HTTP JSON + SSE，不传 token IDs
**状态**：选定（设计）。原因：Token ID 要求 tokenizer/template 锁定并可能增加字节；有无增量同步才是主因。后续可作二进制变体实验。

## ADR-005：四个模式都保留
**状态**：选定（设计）。`full`、`gzip`、`delta`、`delta-gzip`；如果 LAN 中 gzip 性价比优于 Delta，产品可选择 gzip-only 而非坚持自定义协议。

## ADR-006：使用 SSH Tunnel
**状态**：选定（设计）。不向 LAN 公开推理 HTTP 端口，以最少运维支持单用户测试；未来多客户端再审查认证层和 TLS。

## ADR-007：暂不使用 vLLM 进程内 Responses Store 做真值存储
**状态**：选定（设计）。有状态 Responses 可作为对照实验，但服务器重启、进程实例和保存生命周期会影响可靠性。Gateway 保持可持久化的输入快照；推理路径仍采用兼容的 Chat Completions。

## ADR-008：严格 hash 而非“答案相同”
**状态**：选定（设计）。模型输出有随机性，不能以回答一致验证网络传输；每轮检查完整下游请求 JSON 的确定性哈希。

## 风险清单
| 风险 | 触发条件 | 对策 |
|---|---|---|
| Pi API 改版 | Custom Provider/hooks 签名变动 | 锁定版本+合成 golden CI |
| Qwen 工具调用不稳 | 模型能力不足/Parser 不匹配 | 以 fake vLLM 验协议；模型测试独立 |
| Cache 命中不稳 | 前缀/模板/驱逐变化 | 冷热分别测，不当传输收益 |
| 会话状态漂移 | 断线/compact/branch | version/hash + full resync |
| 大 Prompt 存储占用 | SQLite 持续扩张 | TTL/配额/压缩+脱敏 |
| 未授权访问 | LAN 暴露 8000/18080 | loopback+SSH，二次鉴权 |
| 流式中断造成副作用 | tool-call 未完成或重放 | Pi tool execution gating、status check |
| gzip 无净收益 | 不可压缩数据，CPU 瓶颈 | 基准对照和回退模式 |
| 网络数据统计失真 | SSH 加密/重传/混入其他流量 | HTTP/body+wire 双口径+独立窗口 |

## 待验证问题（不能自行补结论）
1. 目标 Mac 的 Pi 版本号与 Custom Provider/Streaming 类型是否匹配？
2. Ubuntu GPU 型号、显存与 vLLM 发行版本支持的 parser flags？
3. Qwen3-0.6B 实际工具调用的可靠性是否满足 Pi 的最低流程？
4. SSH Tunnel 的实际瓶颈是带宽、RTT、CPU 还是 TTFT？
5. gzip 与 delta 在真实测试文件大小下的增益与成本有多大？
6. 需要保留多长会话历史/是否允许存储工具结果正文？
7. 未来多客户端时，应使用每用户密钥+状态隔离还是独立 Gateway？

每个问题由 P0–P4 的测量或部署验收关闭，不在设计阶段伪造结论。
