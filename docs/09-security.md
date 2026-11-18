# 09 · 局域网安全、隐私和数据保留

## 9.1 默认拓扑
Mac 只通过 SSH 隧道到 Ubuntu loopback，远端 vLLM:8000 与 Gateway:18080 不绑定 `0.0.0.0`。限制 Ubuntu sshd 的登录用户、公钥、来源 IP，优先关闭密码认证（根据主机现有管理方式决定）。

**LAN 不等于受信的 API 平面**。SSH 隧道之外，设备被盗、恶意扩展、共享账号与不安全的网关日志也可能泄露 Pi 的完整历史和源代码。

## 9.2 vLLM 网络隔离
[vLLM 官方文档](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/) 指出 `--api-key` 并非覆盖服务器全部可访问路径，因此不能只依靠它保护公网服务。限制监听/防火墙以及 SSH 访问范围；未来如果 LAN 直连必须使用受认证的反向代理/TLS。

## 9.3 Gateway 认证授权
- P0 通过 SSH 认证；P2 也沿用 SSH，减少额外公网身份体系。
- Gateway 即使只监听 loopback，也建议校验随机客户端 token（从环境变量/安全存储读取）和 session ownership，方便未来增强安全边界。
- 防止客户端读取、修改其他 session/branch 快照：查询、修改、状态接口均要校验 owner。
- 认证失败不返回任何提示词/会话内容；审计日志只记录 request id、状态码、大小、耗时和非敏感 fingerprint。

## 9.4 提示词与本地代码属于敏感数据
Gateway 存储完整模型请求快照可能包含工作区源代码、shell stdout、.env 值和隐私材料。设计要求：
- SQLite 文件仅服务进程用户可读，权限 0600，父目录 0700；备份加密。
- TTL 24h 是实验初始建议，但需要主动删除过期快照、VACUUM/敏感数据残留处理；SQLite 单纯 DELETE 不等于物理安全抹除。
- 默认不保存完整请求正文的指标日志；开发调试需 opt-in 并自动过期，任何公开仓库不得上传真实对话。
- 必须限制 `max_request_bytes`、`max_decompressed_bytes`、gzip ratio 与处理耗时。
- 错误消息、SSE 代理异常都不能输出完整提示词或认证头。

## 9.5 Agent 工具副作用
Pi 的工具可读写 Mac 本地文件、运行命令，Gateway 不能替代 Pi 的安全确认机制。`request_id` 去重不会自动阻止 Agent 在重连后重复执行本地写文件/commit/shell。设计独立的 tool execution tracking，遇到不确定状态优先停止并人工确认。

## 9.6 供应链与版本
Pi Extension 运行在客户端进程中，可获得完整 Provider payload 和部分凭据；审核依赖、锁定版本，尽量减少第三方包。Docker 镜像固定 digest，校验 SHA/签名可用性，升级时进行回归。

## 9.7 最小安全验收
`ss -ltnp` / `docker ps` 确认只监听 127.0.0.1；LAN 第三台机器无法直接请求 8000/18080；SSH 凭证不在 git；日志扫描无密钥/源代码，停止服务后能清理活跃会话数据。
