# 05 · Ubuntu vLLM 与可替换模型策略

**默认实验模型**：`Qwen/Qwen3-0.6B`；其模型能力仅用来执行小型 smoke/协议测试，并不是稳定 coding-agent 能力承诺。[模型卡](https://huggingface.co/Qwen/Qwen3-0.6B)。

## 5.1 Hardware discovery
Ubuntu 必须先记录 `uname -m`、`lsb_release -a`、`nvidia-smi`、`docker --version`、显存、CUDA 驱动、vLLM 版本、CPU 架构。
- NVIDIA + 合适驱动：优先 CUDA vLLM；生产镜像固定可验证 tag/digest。
- 仅 CPU：先核查 vLLM CPU 官方安装路径和 ISA/依赖，不能套用 `--gpus all`。若改用 llama.cpp，则记录为 **不同 backend 对照**，不可宣称完成 vLLM 性能基准。
- AMD ROCm：使用官方对应构建并验证卡型；不默认适用 CUDA 镜像。
- 在内存受限环境首先缩小测试上下文、并发和输出，而不是假定 0.6B 必然轻松运行。

## 5.2 P0 启动（NVIDIA 条件下，示例待实际版本锁定）
```bash
# 请先完成 NVIDIA Container Toolkit 配置与 docker run --gpus all 的验证
# <PINNED_VLLM_IMAGE_TAG> 必须替换为实际发布并验证的版本
docker run --rm --gpus all --ipc=host \
  -p 127.0.0.1:8000:8000 \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
  "vllm/vllm-openai:<PINNED_VLLM_IMAGE_TAG>" \
  --model Qwen/Qwen3-0.6B \
  --served-model-name qwen3-0.6b \
  --max-model-len 8192 \
  --enable-prefix-caching \
  --default-chat-template-kwargs '{"enable_thinking": false}'
```

先验证文本生成，不要在第一次启动时把 tool parser、reasoning parser、Gateway、gzip 全部混在一起排错。Docker 镜像有些版本不支持上面某个 flag：固定镜像后用 `vllm serve --help` 校验，记录差异。`--max-model-len 8192` 是实验限制，和模型卡上标注的理论上下文长度是两回事。

## 5.3 文本 Smoke
```bash
curl -fsS http://127.0.0.1:8000/v1/models
curl -fsS http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3-0.6b","messages":[{"role":"user","content":"Reply OK"}],"max_tokens":40,"stream":false}'
```

客户端 Pi 配置使用 [models.pi.example.json](../configs/models.pi.example.json)。

## 5.4 Tool calling / thinking：必须分开验证
Qwen3 可使用思考与非思考模式；vLLM 新版本提供 `qwen3` reasoning/parser 相关支持，但 parser 的具体 flags 与模型 chat template 存在版本差异。[vLLM Reasoning](https://docs.vllm.ai/en/latest/features/reasoning_outputs/)、[Qwen3 parser](https://docs.vllm.ai/en/latest/api/vllm/parser/qwen3/)、[vLLM Tool Calling](https://docs.vllm.ai/en/latest/features/tool_calling/)。

推荐流程：
1. 文本 smoke，先使用 `enable_thinking=false` 并观察 `content` 是否按预期输出。
2. 查固定 vLLM 版本的 `--tool-call-parser` 可选值，优先测试与 Qwen3 模板一致的 parser（如该版本支持 `qwen3`），不要照搬 Qwen2.5 对应的 `hermes` 假设。
3. 启用 `--enable-auto-tool-choice` + 已验证 parser，使用一个无副作用的 `sum(a,b)` 工具测试 `tool_calls`、id、arguments 和 tool result round trip。
4. 单独开启 thinking 与 reasoning parser，对 `reasoning` / `content` 分离和 SSE 事件做回归。
5. 若仅模型无法稳定做工具调用，应将其记作模型能力限制，而不是把网络 Delta 判定 FAIL。

## 5.5 版本指纹
```yaml
model_fingerprint_fields:
  - served_model_name
  - model_weights_revision
  - tokenizer_revision
  - chat_template_hash
  - vllm_build_or_image_digest
  - tool_call_parser
  - reasoning_parser
  - default_chat_template_kwargs
  - transport_renderer_version
```

配置见 [model.yaml](../configs/model.yaml)。模型和配置发生影响渲染的变化，客户端必须 full resync；缓存命中不做保障。

## 5.6 Prefix Cache 的本质
vLLM APC 复用先前 GPU 计算得到的 KV 前缀，**不会**自动使 Pi → Ubuntu 的 JSON 请求变短。缓存可能因显存压力、变更 system/tools/template、实例切换而失效；仅能优化 prefill，不能缩短 decode。报告必须分别测量传输和计算。

## 5.7 不采用 Token ID 序列作为 v1 方案
本设计传输 `messages + envelope`。如果发送 token IDs，则 Pi 需使用与 Ubuntu 完全一致的 tokenizer 和 chat template；整数数组还可能比文本更大。若历史 token IDs 每轮都完整发送，仍有重复传输。须先有 Delta/引用协议，Token ID 二进制化才能作为第二层优化。
