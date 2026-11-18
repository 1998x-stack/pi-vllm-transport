# 实现验证记录 / Verification log

更新日期：2026-11-18

| Gate | 当前状态 | 证据 / 限制 |
|---|---|---|
| P0 Ubuntu vLLM 真实启动 | NOT RUN | 没有目标 Ubuntu 的硬件/驱动/模型访问 |
| P0 Mac Pi 实际连接 | NOT RUN | 没有目标 Mac 的运行访问 |
| P1 HTTP 传输测量脚本 | IMPLEMENTED | `pi_delta.benchmark` 读取真实 HTTP body 与 SSE |
| P1 真实 LAN 抓包 | NOT RUN | 必须在用户局域网实机采集 |
| P2 Gateway 单元/集成 | CI AUTOMATED | 使用 MockTransport / synthetic messages，不需要 GPU |
| P2 Pi 扩展真实 hook | EXPERIMENTAL | 代码存在，目标 Pi 版本尚未现场验证 |
| P3 SQLite version/hash/幂等 | CI AUTOMATED | 基础状态机覆盖，异常与竞争测试需扩大 |
| P3 全部故障恢复 | PARTIAL | fail-closed/full resync；durable SSE replay 未实现 |
| P4 四模式 A/B Runner | IMPLEMENTED | 程序已提交，尚无真实结果 |
| P4 GPU/TTFT/Prefix Cache | NOT RUN | 模型实机和硬件指标尚未采集 |

CI 只能证明同一代码库内的部分模拟测试，不能证明 GPU、Pi SDK、真实网络端到端兼容。任何基准数据需附相同 workload、配置 fingerprint、原始 CSV 和测量口径。 
