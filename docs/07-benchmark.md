# 07 · 网络/Token/推理基准测试设计

## 7.1 实验目标
对同一批固定 Pi Provider 请求，比较 `full`、`gzip`、`delta`、`delta-gzip` 在正确性、网络上传大小、延迟、CPU、存储上的代价。**网络带宽减少不是 Token 输入量下降，GPU KV Prefix Cache 与 HTTP 压缩必须分开测试。**

## 7.2 四种模式
| 模式 | Mac → Ubuntu | Gateway → vLLM | 历史语义 |
|---|---|---|---|
| full | 每轮完整 JSON | 完整 JSON | 不变 |
| gzip | 每轮完整 JSON 的 gzip | 完整 JSON | 不变 |
| delta | 首轮 full，后续引用/替换增量 | 完整 JSON | 不变 |
| delta-gzip | delta 请求再 gzip | 完整 JSON | 不变 |

辅助对照：`native-vllm`（P0 Pi→vLLM，无 Gateway）；它和 full-Gateway 的差值估计 Gateway 固定开销，但路由不同要单独标注。

## 7.3 基准数据集
固定 request replay（不让模型自己随机改变历史）：
- S1 **短对话**：5轮，消息少、正文短。
- S2 **长前缀**：20轮，初始稳定系统+代码块/文档 100–500 KiB，每轮追加少量内容。
- S3 **大工具结果**：10轮，read/grep/tool 输出短中长混合。
- S4 **交错工具调用**：assistant tool_calls + tool result + 继续讨论。
- S5 **历史分叉/编辑**：fork、替换旧 user、compact（prefix 不再稳定）。
- S6 **模板变化**：tools、samplingParams、reasoning/Chat Template 切换；强制替换 envelope。
- S7 **压缩失效**：不可压缩的随机/编码过内容，验证 gzip 不必然优于 delta。
- S8 **断线重试**：连接中断、丢包、Gateway/vLLM 重启。

只向公开仓库提交由模拟数据生成的 synthetic workload；真实 Pi 工作区内容不得提交。

## 7.4 度量口径
- `payload_uncompressed_bytes` = UTF-8 字节数（Gateway 之前 Pi 完整请求 renderer）。
- `http_request_body_bytes` = 实际 Content-Encoding 后上传到 Gateway 的 HTTP body bytes（gzip 前后分别记录）。
- `wire_bytes_client_to_server` = 特定时间窗口 Mac→Ubuntu 流量（单独记录 SSH/TCP/IP 开销，避免与 HTTP body 相混）。
- `wire_bytes_server_to_client` = SSE/ACK 返回字节，不与上传字节相加后仍声称 upload savings。
- `gateway_to_vllm_bytes` = 完整重建 JSON 的 HTTP request bytes。
- `model_prompt_tokens` = vLLM 真实报告的 token input（包含模板渲染）及缺失说明。
- `ttft_ms` 从发出请求到首个可见内容（另可记录首 SSE frame），`total_latency_ms` 到终止事件。
- `prefill/cache metrics` = vLLM 公开指标，若某版本没有字段则标记 N/A，禁止臆测。
- `gateway_cpu_ms, rss_mb, sqlite_size_mb, fallback_rate` 是优化开销。

## 7.5 计算公式
```text
upload_savings = 1 - (sum(delta_http_body_bytes) / sum(full_http_body_bytes))
wire_savings   = 1 - (sum(delta_mac_upload_wire_bytes) / sum(full_mac_upload_wire_bytes))
gateway_cost   = median(TTFT_full_gateway) - median(TTFT_native_vllm)
```
分母 0 或异常缺测时报告 N/A。每个实验记录样本 n、均值、中位数、p95、最小/最大，并报告冷/热缓存条件；不能将不同延迟样本混合而不标注。

## 7.6 网络测量建议
- HTTP 层由客户端和 Gateway 按 `Content-Length` 或实际读取 bytes 记录（chunked 情形记录实际总数）。
- 链路层使用 Mac/Ubuntu 的 `tcpdump`/`tshark`/`nettop` 等对指定 SSH peer、指定测试窗口抓取，排除其他流量。SSH 隧道使 HTTP payload 处于加密流内，抓包获得的总网络字节**不等同**于 JSON body。
- 每个模式独立运行同一 corpus（相同 Pi serialization + 模型 fingerprint），使用稳定连接与相同硬件；随机化实验顺序，先热机再采样，另做 cold-cache 对照。
- 采集 RTT、GPU 利用率、Mac CPU、Ubuntu CPU 与 Docker RSS，避免只观察单一数字。

## 7.7 正确性先于性能
每轮 Gateway 在转发 vLLM 之前应计算 `request_sha256`，与 Pi 在本地同一 renderer 导出的 hash 逐轮比对。任何一轮 mismatch → 本组性能试验无效；不能用模型回答一致作为替代指标。

## 7.8 报告结构
```text
benchmarks/results/<run-id>/
  manifest.json           两机硬件、网络、版本/模型指纹
  per_request.csv         mode,turn,body_bytes,wire_bytes,TTFT,hash_ok,...
  summary.json            n,median,p95,missing_count
  report.md               结果、归因、限制、回退案例
```

**验收策略**：若在局域网中 gzip 已几乎消除重复上传，Delta 提升小于其复杂度与 CPU/存储成本，应优先保留 gzip/full；最终选择由真实测量决定，不能预设赢家。
