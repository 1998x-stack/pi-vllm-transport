#!/usr/bin/env bash
set -euo pipefail
if ! command -v vllm >/dev/null 2>&1; then
  echo "vllm not installed; follow docs/06-deployment.md for CPU/CUDA setup" >&2
  exit 1
fi
MODEL="${VLLM_MODEL:-Qwen/Qwen3-0.6B}"
NAME="${VLLM_SERVED_NAME:-qwen3-0.6b}"
MAX_LEN="${VLLM_MAX_MODEL_LEN:-8192}"
ARGS=(serve "$MODEL" --served-model-name "$NAME" --host 127.0.0.1 --port 8000
  --max-model-len "$MAX_LEN" --enable-prefix-caching)
if [[ "${VLLM_TOOL_PARSER:-}" != "" ]]; then
  ARGS+=(--enable-auto-tool-choice --tool-call-parser "$VLLM_TOOL_PARSER")
fi
if [[ "${VLLM_EXTRA_ARGS:-}" != "" ]]; then
  echo "Use a script edit for additional flags; whitespace-split env options are disallowed." >&2
  exit 2
fi
exec vllm "${ARGS[@]}"
