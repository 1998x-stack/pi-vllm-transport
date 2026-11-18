#!/usr/bin/env bash
set -euo pipefail
if [[ $# -lt 1 ]]; then echo "Usage: scripts/tunnel.sh ubuntu_user@UBUNTU_LAN_IP [p0|delta]" >&2; exit 2; fi
TARGET="$1"
MODE="${2:-p0}"
case "$MODE" in
  p0) LOCAL=8000; REMOTE=8000 ;;
  delta) LOCAL=18080; REMOTE=18080 ;;
  *) echo "Mode must be p0 or delta" >&2; exit 2 ;;
esac
exec ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
  -N -L "127.0.0.1:${LOCAL}:127.0.0.1:${REMOTE}" "$TARGET"
