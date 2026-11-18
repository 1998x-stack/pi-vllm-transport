#!/usr/bin/env bash
set -euo pipefail
URL="${VLLM_BASE_URL:-http://127.0.0.1:8000/v1}"
MODEL="${VLLM_SERVED_NAME:-qwen3-0.6b}"
echo "[1/2] models"
curl --fail --max-time 10 --silent --show-error "$URL/models"
echo
echo "[2/2] chat completion"
curl --fail --max-time 120 --silent --show-error "$URL/chat/completions" \
  -H "Content-Type: application/json" \
  -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with OK.\"}],\"stream\":false,\"max_tokens\":32}"
echo
