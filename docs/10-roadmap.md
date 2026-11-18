# 10 · 实施路线图与里程碑

**现在的交付类型：设计文档，不是已部署系统。** 下述事项是待实施任务清单；不得凭代码示例将其标记 PASS。

## P0 — 原生服务可用
交付：Ubuntu 环境盘点、固定 vLLM 镜像+模型 revision、loopback Serve、Mac SSH Tunnel、Pi models.json 配置、文本 smoke、工具调用兼容记录。
- [ ] Ubuntu GPU/CPU/ROCm 硬件路径确定
- [ ] 模型及 vLLM 版本写入 manifest
- [ ] Ubuntu localhost curl 成功
- [ ] Mac tunnel curl 成功
- [ ] Pi 文字对话成功
- [ ] 简单工具回环测试（模型不支持则明确标记）

DoD：P0 原生链路可重复运行；真实输出与环境信息已记录。

## P1 — 测量基线与 gzip 对照
- [ ] Pi 原始请求 payload capture（仅长度/脱敏）
- [ ] Mac wire + Ubuntu 收包测量
- [ ] 生成合成请求 Replay Corpus
- [ ] full 与 gzip 对照保持请求等价
- [ ] 记录 TTFT/RTT/prompt_tokens
- [ ] 形成首份基线报告

DoD：同一 corpus 可重放，清楚地区分网络字节数/Token/GPU 计算量。

## P2 — 自定义增量协议最小闭环
- [ ] 自定义 Pi Provider SPIKE（或经验证可行的 hook adapter）
- [ ] `/delta/v1/capabilities` + `/infer` + Schema
- [ ] SQLite session/branch/revision/snapshot
- [ ] full + delta replace_suffix
- [ ] envelope ref/replace 与 SHA-256 校验
- [ ] 标准 Chat Completions SSE 透传
- [ ] 与 full golden hash 一致
- [ ] Mac 实测 Delta 上传小于 full 的增长型工作负载

DoD：支持文本和基本 tools，网关重建后请求逐轮等价。

## P3 — 故障恢复与安全上线
- [ ] 409/410/422 行为与全量回退
- [ ] request_id 去重、transaction & lock
- [ ] 断线/取消/retry、请求状态查询
- [ ] 分支、历史压缩、模型/工具升级
- [ ] gzip+delta、体积/TTL/配额
- [ ] loopback+SSH、数据清理和日志审计
- [ ] 首个全量集成故障测试 PASS

DoD：不静默丢失历史，不跨分支混写，不意外执行未完成工具。

## P4 — 真实 benchmark 与决策
- [ ] S1–S8 负载按四模式全量测试
- [ ] 冷/热缓存、不同上下文长度、可压缩与不可压缩数据
- [ ] 请求体、wire bytes、TTFT、GPU cache 全量报告
- [ ] CPU/存储开销与失败回退率
- [ ] 根据数据评估保留 gzip-only 或 delta
- [ ] README、ADR、实验记录与 reproducibility pack

DoD：将**实测结果**发布为报告，明确边界、版本、样本数与未知项。

## 优先级依赖
```mermaid
flowchart LR
 P0["P0 native baseline"] --> P1["P1 measurements + gzip"]
 P1 --> P2["P2 delta + gateway"]
 P2 --> P3["P3 recovery + security"]
 P3 --> P4["P4 rigorous benchmark"]
```

不建议在 P0 未通过时并行写大量 Gateway 业务代码；模型调用失败、Pi 兼容失败与网络同步失败必须分离诊断。

## 交付产物
每个阶段在 `docs/verification.md`（未来创建）记录机器标识（脱敏）、实际版本、命令、输出摘要、成功/失败、已知问题。不要将设计期任务完成误标为运行期验收完成。
