#!/usr/bin/env bash
# Optional P0 smoke test: checks whether pinned vLLM + Qwen can produce a
# structured tool call. A failure here is a MODEL/PARSER integration failure,
# not proof that the delta transport protocol is incorrect.
set -euo pipefail
URL="${VLLM_BASE_URL:-http://127.0.0.1:8000/v1}"
MODEL="${VLLM_SERVED_NAME:-qwen3-0.6b}"
PAYLOAD="$(cat <<JSON
{
  "model": "$MODEL",
  "stream": false,
  "max_tokens": 128,
  "messages": [
    {"role": "user", "content": "Call the sum tool with a=1 and b=2. Do not answer directly."}
  ],
  "tools": [{
    "type": "function",
    "function": {
      "name": "sum",
      "description": "Add two integers",
      "parameters": {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a", "b"]
      }
    }
  }],
  "tool_choice": {"type":"function","function":{"name":"sum"}}
}
JSON
)"
curl --fail --silent --show-error --max-time 180 \
  "$URL/chat/completions" \
  -H 'Content-Type: application/json' \
  -d "$PAYLOAD" | python3 -c '
import json,sys
data = json.load(sys.stdin)
calls = data.get("choices",[{}])[0].get("message",{}).get("tool_calls",[])
if not calls:
    raise SystemExit("FAIL: no structured tool_calls; check vLLM tool parser, model and template")
call = calls[0]
if call.get("function",{}).get("name") != "sum":
    raise SystemExit("FAIL: unexpected tool name")
args = json.loads(call["function"]["arguments"])
if args.get("a") != 1 or args.get("b") != 2:
    raise SystemExit("FAIL: unexpected tool arguments")
print("PASS: structured sum(a=1,b=2) tool call produced")
'
