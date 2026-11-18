#!/usr/bin/env bash
set -euo pipefail
echo "== Ubuntu environment =="
uname -a
cat /etc/os-release || true
echo "== Network =="
hostname -I || true
echo "== Resources =="
free -h || true
df -h . || true
if command -v nvidia-smi >/dev/null 2>&1; then nvidia-smi; else echo "NVIDIA GPU not detected (use CPU/ROCm path after verification)."; fi
echo "== Software =="
for cmd in docker vllm python3 ssh; do command -v "$cmd" || true; done
echo "== Ports =="
ss -ltn 2>/dev/null | grep -E '(:8000|:18080)' || true
echo "== Runtime probes =="
curl --fail --max-time 5 -sS http://127.0.0.1:8000/v1/models || true
echo
