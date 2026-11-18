# 06 · Mac + Ubuntu 局域网部署手册（设计/实验 Runbook）

> P0 命令可以按实际硬件适配执行；Gateway 尚未开发，因此 P2 的启动步骤为待实现清单，**不可视为现有可运行脚本**。固定版本后将命令写入 scripts 和锁定清单。

## 6.1 物理拓扑与先决条件
- Mac：macOS、可安装 Pi 的 Node/CLI、OpenSSH 客户端；本地工作区。
- Ubuntu：SSH Server、Docker（如使用 NVIDIA CUDA）、vLLM 与 Qwen3-0.6B 权重的存储空间。
- 两台机器处于同一可信 LAN，Mac 能 SSH 登录 Ubuntu；首次连接人工核验 SSH host key。
- Ubuntu 不向 LAN 直接开放 GPU 推理端口；仅 SSH (22 或自定义) 对 Mac 可达。

### Ubuntu 环境盘点（先保存日志）
```bash
uname -a
uname -m
cat /etc/os-release
ip -4 addr
free -h
df -h
command -v nvidia-smi && nvidia-smi || true
command -v docker && docker version || true
command -v vllm && vllm --version || true
```
将硬件、driver/CUDA、模型权重 revision、Pi commit 和 vLLM Docker image digest 记入当次实验 manifest。若非 NVIDIA，切换到 `05-vllm-models.md` 的 CPU/ROCm 分支，不运行 CUDA 示例。

## 6.2 P0 · Ubuntu 运行 vLLM
需要先安装 Docker、NVIDIA Container Toolkit，并确认 `docker run --rm --gpus all <verified CUDA image> nvidia-smi` 成功。基于一个**已经查实存在**的 vLLM image tag/digest：
```bash
docker run -d --name pi-vllm-qwen --gpus all --ipc=host \
  -p 127.0.0.1:8000:8000 \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
  "vllm/vllm-openai:<PINNED_IMAGE_TAG>" \
  --model Qwen/Qwen3-0.6B \
  --served-model-name qwen3-0.6b \
  --max-model-len 8192 \
  --enable-prefix-caching \
  --default-chat-template-kwargs '{"enable_thinking": false}'
docker logs -f pi-vllm-qwen
```
这里不能原样复制 `<PINNED_IMAGE_TAG>` 占位符；先在对应版本跑 `vllm serve --help` 校验 flags。权重下载首次可能需要外网，但后续推理仅用局域网。

Ubuntu 本机测试：
```bash
curl -fsS http://127.0.0.1:8000/v1/models
curl -fsS http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3-0.6b","messages":[{"role":"user","content":"Only reply OK"}],"stream":false,"max_tokens":40}'
```

## 6.3 P0 · Mac 用 SSH Tunnel
先确定 Ubuntu 的固定 LAN 地址（DHCP reservation、局域网 DNS 都可），然后在 Mac 终端：
```bash
ssh -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -N -L 8000:127.0.0.1:8000 \
    ubuntu_user@UBUNTU_LAN_IP
```
命令持续运行时，在另一个 Mac 终端测试：
```bash
curl -fsS http://127.0.0.1:8000/v1/models
```
切记：SSH tunnel 的 `127.0.0.1` 是 Mac 端本地端口，远端目标 `127.0.0.1` 是 Ubuntu 本机；`-L` 的目标不会自动替你路由到容器外部地址，需事先成功配置 Docker 端口映射。

## 6.4 P0 · Pi 使用模型
按 [Pi 官方安装/配置](https://docs.pi.dev/latest/models) 安装并确认 `pi --version`。把 [models.pi.example.json](../configs/models.pi.example.json) 的 provider 合并进 `~/.pi/agent/models.json`（**不要覆盖原有配置**）。启动 `pi` 后用 `/model` 选择 `lan-vllm / qwen3-0.6b`。

先发简短文本，再发只使用安全的 read/列目录工具的任务；若工具调用失败，检查 Qwen3 parser/Chat Template，并独立记录失败类型（模型格式、Pi 解析、GPU 服务，还是网络）。

## 6.5 P1 · 网络采样
- Mac：Pi Provider 记录原始请求体的 UTF-8 字节；独立抓包记录 SSH 隧道实际链路字节。真实 TCP 计数需注明 TCP 重传、SSH 加密开销与响应流量。
- Ubuntu：Gateway 尚未加入时，可在 vLLM 前加只观测不改写的 HTTP 代理或统计 socket 以获得 request Content-Length；不依靠 `usage.prompt_tokens` 估算字节。
- 将重放语料与抓包去标识化后在本地持久化。默认不上传原始代码/对话到公开仓库。

## 6.6 P2 · 加入 Gateway（待实现）
网关应通过独立虚拟环境/容器运行，绑定 `127.0.0.1:18080`，upstream `http://127.0.0.1:8000/v1`。启用 SQLite WAL，备份与过期清理、health/readiness、请求体大小限制。

Ubuntu 本机先调用 `GET /delta/v1/capabilities`，再验证 full snapshot 与 delta 重建。此时 **Mac 不再转发 8000**，而是：
```bash
ssh -o ExitOnForwardFailure=yes -N \
  -L 18080:127.0.0.1:18080 ubuntu_user@UBUNTU_LAN_IP
```
Pi Delta Provider 指向 `http://127.0.0.1:18080`；`full` 模式应可与 P0 完全对照。**在 Gateway 和客户端代码完成前，以上只属于拓扑规格，不是可运行部署。**

## 6.7 运维与回退
- Mac 端 transport 可切回 `full`，或恢复原生 Pi 模型连接并转发 8000。
- vLLM 重启后客户端 full 仍可工作，但 Prefix Cache 命中会从冷状态重新开始。
- Gateway 重启后根据 SQLite 快照恢复 session revision；未完成 SSE 不能自动当成完成。
- 每次切换模型权重/模板/工具 parser，刷新 `model_fingerprint`，触发 full resync。

## 6.8 升级与维护
每次升级先运行 `08-testing.md` 的基准和兼容性检查。禁止直接将 Docker `latest`、Pi `latest`、vLLM `latest` 的性能差异与“优化效果”混为一谈。
