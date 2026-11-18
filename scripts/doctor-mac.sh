#!/usr/bin/env bash
set -euo pipefail
echo "== macOS =="
sw_vers || true
uname -m
echo "== Pi / SSH =="
command -v pi && pi --version || true
ssh -V || true
echo "== Tunnel probes =="
curl --fail --max-time 5 -sS http://127.0.0.1:8000/v1/models || true
echo
curl --fail --max-time 5 -sS http://127.0.0.1:18080/healthz || true
echo
