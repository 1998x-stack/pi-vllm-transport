# 12 · 官方依据与版本核验记录

**调研日期：2026-11-18**。以下是设计所依据的公开文档，文档页面可能随发布迭代；部署必须锁定实际版本而非把“latest 文档”等同于本机安装能力。

| 组件 | 原始资料 | 设计依赖点 |
|---|---|---|
| Pi | [Models Configuration](https://docs.pi.dev/latest/models-configuration) | models.json providers/api/baseUrl/compat/samplingParams |
| Pi | [Custom Providers](https://docs.pi.dev/latest/custom-provider) | registerProvider、streamSimple、事件与 instrumentation |
| Pi | [Extensions](https://docs.pi.dev/latest/extensions) | before_provider_request、headers、provider_stream_event |
| Pi | [Choose a Model](https://docs.pi.dev/latest/models) | 兼容端点优先 models.json |
| Qwen | [Qwen3-0.6B Model Card](https://huggingface.co/Qwen/Qwen3-0.6B) | 模型 ID、上下文与 thinking 能力 |
| Qwen | [Qwen3 vLLM Deployment](https://github.com/QwenLM/Qwen3/blob/main/docs/source/deployment/vllm.md) | enable_thinking 传参、部署建议 |
| vLLM | [OpenAI-compatible server](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/) | Chat Completions、Responses、API key 覆盖边界 |
| vLLM | [Tool Calling](https://docs.vllm.ai/en/latest/features/tool_calling/) | tool parser 与模型模板兼容 |
| vLLM | [Qwen3 Parser](https://docs.vllm.ai/en/latest/api/vllm/parser/qwen3/) | 最新 Qwen3 parser 格式说明 |
| vLLM | [Reasoning Outputs](https://docs.vllm.ai/en/latest/features/reasoning_outputs/) | reasoning parser、Qwen3 thinking 开关 |
| vLLM | [Automatic Prefix Caching](https://docs.vllm.ai/en/stable/features/automatic_prefix_caching/) | Prefill 复用 ≠ 网络减少 |
| vLLM | [Serve CLI](https://docs.vllm.ai/en/latest/cli/serve/) | 实际运行选项版本相关 |
| JSON | [RFC 8785: JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785) | 请求 hash 一致性 |
| JSON Schema | [2020-12 specification](https://json-schema.org/draft/2020-12) | 协议 Schema |

## 版本锁定（实机阶段填入）
```yaml
experiment_manifest:
  date: null
  client:
    os: macOS
    pi_version: null
    pi_commit: null
    node_version: null
    extension_commit: null
  server:
    os: Ubuntu
    kernel: null
    cpu_gpu: null
    nvidia_driver: null
    vllm_image_digest: null
    vllm_version: null
  model:
    id: Qwen/Qwen3-0.6B
    weights_revision: null
    tokenizer_revision: null
    chat_template_sha256: null
    parser: null
  network:
    ssh_version: null
    lan_rtt_ms: null
    link_speed_mbps: null
```

**核验方法**：vLLM 版本 CLI 的 `--help`、Pi 真实 Provider payload、模型仓库 tokenizer config、当前响应协议字段为最终实机依据。某一版本不支持的选项应明确记录，不应由“latest 文档”猜测。
