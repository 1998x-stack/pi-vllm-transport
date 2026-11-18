# 13 · 初次运行：Mac Pi → Ubuntu vLLM → Pi Delta Gateway

> 当前代码是 **实验性开发版本**。Ubuntu / Mac 还没有被远程部署，操作需要在实际两台机器分别执行。先完成 P0 再启用 Delta。

## Ubuntu：P0 服务启动

1. 在 Ubuntu 上克隆仓库并进入目录：

```bash
git clone https://github.com/1998x-stack/pi-vllm-transport.git
cd pi-vllm-transport
bash scripts/doctor-server.sh
```

2. 选择 NVIDIA CUDA / CPU / ROCm 的对应安装路径。CUDA 路径上，先安装 vLLM 后运行（Qwen3 官方工具调用示例使用 `hermes`；请按固定的 vLLM 版本核验）：

```bash
VLLM_MODEL=Qwen/Qwen3-0.6B \
VLLM_TOOL_PARSER=hermes \
bash scripts/serve-vllm.sh
```

可选 Docker Compose 路径：

```bash
cp deploy/env.example deploy/.env
# 修改 deploy/.env，填入有效的 PINNED vLLM 镜像和随机 token
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build
```

`docker compose` 示例专供 NVIDIA，要求 NVIDIA Container Toolkit、可用镜像和足够显存。非 GPU 主机不得使用 `gpus: all` 运行。由于模型下载可能需要公网访问，LAN 本身并不能替代首次权重拉取。

3. 另一个 Ubuntu 终端运行：

```bash
bash scripts/smoke-vllm.sh
```

## Mac：P0 SSH 隧道 + Pi

```bash
git clone https://github.com/1998x-stack/pi-vllm-transport.git
cd pi-vllm-transport
bash scripts/doctor-mac.sh
bash scripts/tunnel.sh ubuntu_user@UBUNTU_LAN_IP p0
```

在另一个 Mac 终端： `curl http://127.0.0.1:8000/v1/models`。根据 Pi 官方安装文档安装 Pi，将 `configs/models.pi.example.json` 中的 provider **合并**到 `~/.pi/agent/models.json`，运行 `pi` 后选 `lan-vllm/qwen3-0.6b`。

## Ubuntu：P2 Gateway

可在另一 Ubuntu 终端独立运行，不停止已启动的 vLLM：

```bash
cd pi-vllm-transport
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e "./server/gateway[test]"
export PI_DELTA_GATEWAY_TOKEN="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
export PI_DELTA_UPSTREAM=http://127.0.0.1:8000
export PI_DELTA_MODEL=qwen3-0.6b
export PI_DELTA_MODEL_FINGERPRINT=qwen3-0.6b@v1
python -m pi_delta
```

**注意**：Pi 使用的 token 必须与 Gateway 一致。通过安全的手工方式向 Mac 传递环境变量，不要把 token 写入仓库。若使用 Compose，token 必须在 `deploy/.env` 中另外配置。

## Mac：P2 启用 Delta

```bash
bash scripts/tunnel.sh ubuntu_user@UBUNTU_LAN_IP delta
# 在另一个 Mac shell 输入与 Ubuntu 一致的 secret
export PI_DELTA_GATEWAY_TOKEN='PASTE_THE_MATCHING_TOKEN'
export PI_DELTA_MODEL_FINGERPRINT='qwen3-0.6b@v1'
export PI_DELTA_MODE=delta
pi -e ./client/pi-delta/index.ts
```

把 `configs/models.delta.pi.example.json` 的 `lan-delta` provider 合并进 Pi models.json，使用 Pi `/model` 选择 `lan-delta/qwen3-0.6b`。

- 先 `PI_DELTA_MODE=full` 做基线：Pi 直接向 Gateway 发送原生完整请求，不使用会话缓存。
- 再 `PI_DELTA_MODE=delta` 做多轮测试：首次 full 建立 revision，后续可能发送 delta。
- 若 Pi 某个版本不返回 `x-pi-delta-*` 响应头，客户端会自动回到 full。使用 `PI_DELTA_DEBUG=1` 在客户端查看**字节数量**而非内容。
- 当前 Pi 扩展属于实验性 Hook SPIKE；尚未在目标 Mac 的 Pi 上验证。不能把模拟网关测试误当作 Pi 实机端到端 PASS。

## A/B 实验（任意能访问 Gateway 的 Python 环境）

```bash
export PI_DELTA_GATEWAY_TOKEN='PASTE_THE_MATCHING_TOKEN'
python -m pi_delta.benchmark --url http://127.0.0.1:18080 --turns 10 --prefix-kb 64
```

运行 `full / gzip / delta / delta-gzip`，CSV 默认写入 `benchmarks/results/benchmark.csv`。它记录实际 HTTP request body 长度和 SSE 首字节耗时，但不等同于加密后的 SSH 网络链路字节，更不等于真正模型 TTFT。后续要用独立抓包与 GPU 指标交叉验证。

## 维护

- 不需要 Delta 时：撤销 `-e` 扩展，选择 `lan-vllm` 并将隧道切回 8000。
- 机密：仅在本地 shell/.env（已 gitignore），不要提交模型 token 或对话。
- 版本：固定 Pi/vLLM/模型与 tokenizer 版本，记录在基准 manifest 中。
