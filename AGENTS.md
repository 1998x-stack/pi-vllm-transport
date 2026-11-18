# Repository rules — Pi × vLLM Transport Lab

## Project stage
- 当前是 **design-first** 仓库。未明确交付的代码与基准测试不得标记为 implemented / PASS。
- 用户目标是 **Mac Pi → Ubuntu vLLM 的网络上传字节优化**。不把 GPU KV reuse、逻辑 prompt token 数量和网络压缩混成同一个指标。
- 不要悄悄修改 Pi 原有上下文、工具声明、模型参数、tool_call_id 或模型生成结果。压缩历史属于独立实验，不算等价的 Delta Transport。

## Implementation constraints
1. 先实现 P0 完整请求与测量，再实现 P1 gzip、P2 delta、P3 恢复、P4 benchmark。
2. 所有自定义协议都必须通过 `protocol/pi-delta-v1.schema.json` 校验；变更协议时同步更新 `docs/03-protocol.md`、Schema 和契约测试。
3. Pi 接入前固定 Pi 版本/commit，核实 Custom Provider 与 hook 的生命周期；不能假定未知字段一定被 HTTP SDK 透传。
4. vLLM 权重、镜像版本、tokenizer/chat template、tool/reasoning parser 和运行参数必须记录到运行清单中。
5. 保留 P0 full 模式作为 golden reference；同样的 Pi 渲染请求在 Gateway 端必须满足规范化请求散列相同（不是仅语义近似）。
6. 对逐步推理模型的中间内容、tool call streams、abort、工具执行状态要制定回放和故障测试，不得只测试文本。
7. Mac/Ubuntu 互信默认仅 SSH Tunnel；vLLM / Gateway 监听 loopback；禁止提交私钥、令牌、真实 prompt、仓库源码或完整工具结果。
8. 在工具调用可能产生副作用时，不能宣称跨 Agent 的 exactly-once；Gateway 的 request-id 幂等仅涵盖其自身受控状态。
9. 指标必须按 full/gzip/delta/delta-gzip 四模式在同一任务回放；不能凭模拟值声称性能提升。
10. 对失败情形先保守回退完整快照，所有失配必须可追踪。

## Definition of done
- 可复现部署步骤与锁定版本；
- 请求重建前后 Canonical SHA-256 完全相同；
- 多轮文本、工具调用、compact、branch、abort、断线、重启、并发测试通过；
- 包含 Mac 实际 wire bytes 与 Gateway 接收 bytes 的真实数据；
- 安全评审和日志脱敏通过；
- README 文档链接、CHANGELOG/decision log 同步更新。

官方参考见 [docs/12-references.md](docs/12-references.md)。