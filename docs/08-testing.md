# 08 · 测试矩阵和交付验收

## 8.1 测试层级
L0 Schema & canonical JSON unit tests → L1 diff algorithm → L2 Gateway session/state/SQLite → L3 Pi Provider adapter + SSE parser → L4 Mac/Ubuntu 集成 → L5 性能/故障注入。所有层级必须能在 CI 中用 fake vLLM 运行，实机 GPU 仅用于 L4/L5。

## 8.2 协议契约测试
| 用例 | 输入/操作 | 必须保证 |
|---|---|---|
| T01 首次快照 | valid full | 创建 revision 1，保存 hash |
| T02 纯追加 | delta keep=n, append=m | request 完全等价 |
| T03 历史替换 | keep<n | replace_suffix 正确 |
| T04 历史清空 | keep=0 | 等价于全量替换消息 |
| T05 工具调用 | assistant.tool_calls + tool role | ID、参数、顺序不变 |
| T06 配置变化 | tools/model/sampling changed | envelope replace/full |
| T07 hash 错误 | expected 与重建不同 | 422，vLLM **0 次调用** |
| T08 版本冲突 | stale revision | 409，旧状态不污染新状态 |
| T09 session expired | TTL 删除 | 410，full resync |
| T10 幂等 | 同 request_id 同 body | 不重复创建 revision |
| T11 幂等冲突 | 同 request_id 不同 body | 409 |
| T12 重启 | SQLite 已接受 snapshot | 恢复完整 revision/hash |
| T13 断线 | 接受请求后 SSE 中断 | 不将生成完成/工具执行成功误判 |
| T14 并发 | 同分支两条 delta | 最多一条成功或正确串行 |
| T15 模型升级 | fingerprint 变化 | full resync |
| T16 攻击/超限 | 非法 gzip / 解压炸弹 | 413/415，不读取任意大正文 |
| T17 Streaming | 多块 text/toolcall/thinking | 索引、内容、done/error、取消正确 |
| T18 Unicode | emoji/中文/surrogate/float | 双语言 canonical digest 一致 |
| T19 大工具结果 | 100 KiB–数 MiB | 不截断、不修改内容 |
| T20 索引越界 | keep>old.len | 422，状态无变化 |
| T21 重同步隔离 | 已存在 branch 收到另一个 full | 409，必须使用新 transport_branch_id |
| T22 旧请求晚到 | 新 branch full resync 后旧 Delta 到达 | 旧消息不能写入新 branch |
| T23 模型指纹伪造 | 客户端指纹与服务器模型不匹配 | 拒绝，不调用错误模型 |

## 8.3 黄金语料（golden corpus）
必须包含至少：
- 没有工具的单轮与 20 轮；
- 仅 tool_call 且 assistant content 为 null；
- assistant 同时包含文本和 tool_calls；
- tool arguments 的 JSON 字符串分块；
- 稳定 system prompt 以及动态 tools 变更；
- compact 后中间消息被完全替换；
- 可选 reasoning 输出被转换到 Provider 请求的情况；
- 空数组、null、中文 Unicode、超长消息。

**做法**：在同一个 Pi 版本、同一 Renderer 中捕获 *脱敏或合成* 的 full 请求；四种模式对同一 corpus replay，比较 Canonical hash。

## 8.4 端到端实时测试
- P0：从 Mac Pi 发起短问答，正常 SSE；本地允许目录读取，结果回到模型。
- P2：每轮用 Gateway 的重建请求 hash 与 P0 Renderer hash 对比，验证 SSE 工具调用后 Pi 在 Mac 执行，而不是 Ubuntu。
- 断线故障注入应在请求发出前/已接受但未开始/工具结果产生后/流输出中间/终止前分别执行。
- 多次失败不得导致 Pi 误执行工具、损坏文件或无限重试。

## 8.5 性能交付门槛（不虚构数值）
| Gate | 条件 |
|---|---|
| Correctness | synthetic corpus 每个请求 hash 全部一致 |
| Functional | 文本+工具往返无异常；不支持的模型工具行为单独归类 |
| Resilience | T07–T16 在规定的安全回退路径通过 |
| Measurement | 上下行、HTTP body、逻辑 tokens、TTFT 均有样本或明确 N/A |
| Reproducibility | Pi/vLLM/model/driver fingerprint 与脚本、seed 可复现 |
| Security | 仅 loopback + SSH、无密钥或真实 prompt 泄露 |
| Decision | 报告 Delta 在 LAN 相比 gzip 的净收益和运营成本 |

## 8.6 CI 计划
- JSON Schema 语法检查与正/负样例；
- lint/typecheck + Python formatter（代码实现后启用）；
- 单元/契约/状态机测试；
- 文档相对链接与 Mermaid 语法检查；
- Release manifest 内容验证；
- 无 GPU CI 不能宣称推理性能 PASS。
