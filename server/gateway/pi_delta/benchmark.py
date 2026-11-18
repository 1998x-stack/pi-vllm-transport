"""Replay deterministic OpenAI requests via Gateway and collect actual HTTP-body sizes.

Requires an already running Ubuntu Gateway and vLLM. Does not start a model and
does not claim wire-level TCP bytes: SSH encryption / retransmissions are separate.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import time
import uuid
from pathlib import Path

import httpx

from .core import digest, make_delta


def corpus(turns: int = 10, prefix_kb: int = 64, model: str = "qwen3-0.6b"):
    messages = [{"role": "system", "content": "benchmark only: " + ("A" * (prefix_kb * 1024))}]
    for i in range(turns):
        messages.append({"role": "user", "content": "Turn " + str(i) + ": verify message " + str(i)})
        yield {"model": model, "messages": json.loads(json.dumps(messages)), "stream": True, "max_tokens": 16}
        messages.append({"role": "assistant", "content": "OK"})


def run_mode(client: httpx.Client, url: str, token: str, mode: str, payloads: list[dict], fingerprint: str):
    sid, bid = str(uuid.uuid4()), str(uuid.uuid4())
    previous = None
    revision = 0
    prev_hash = None
    rows = []
    for turn, upstream in enumerate(payloads):
        packet = {
            "protocol": "pi-delta/v1",
            "request_id": str(uuid.uuid4()),
            "session_id": sid, "branch_id": bid,
            "model_fingerprint": fingerprint,
            "expected_request_sha256": digest(upstream),
        }
        if previous is None or mode in ("full", "gzip"):
            # Fresh branch per full request; full reset of an existing branch is forbidden.
            if previous is not None:
                bid = str(uuid.uuid4())
                packet["branch_id"] = bid
            packet.update({
                "kind": "full", "base_revision": None, "base_hash": None,
                "full": {"request": upstream}
            })
        else:
            packet.update({
                "kind": "delta", "base_revision": revision, "base_hash": prev_hash,
                "delta": make_delta(previous, upstream),
            })
        raw = json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        compressed = "gzip" in mode
        encoded = gzip.compress(raw) if compressed else raw
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        if compressed:
            headers["Content-Encoding"] = "gzip"
        started = time.perf_counter()
        with client.stream("POST", url + "/delta/v1/infer", content=encoded, headers=headers) as res:
            if res.status_code != 200:
                raise RuntimeError(f"{mode} turn={turn} HTTP {res.status_code}: {res.read()[:500]!r}")
            revision = int(res.headers["X-Pi-Delta-Revision"])
            prev_hash = res.headers["X-Pi-Delta-Request-Hash"]
            if prev_hash != digest(upstream):
                raise RuntimeError("Gateway reconstructed request hash mismatch")
            ttft_ms = None
            response_bytes = 0
            for chunk in res.iter_bytes():
                if ttft_ms is None:
                    ttft_ms = 1000 * (time.perf_counter() - started)
                response_bytes += len(chunk)
            total_ms = 1000 * (time.perf_counter() - started)
        rows.append({
            "mode": mode, "turn": turn,
            "full_request_bytes": len(json.dumps(upstream, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
            "raw_packet_bytes": len(raw), "http_request_body_bytes": len(encoded),
            "response_body_bytes": response_bytes, "ttft_ms": round(ttft_ms or total_ms, 3),
            "total_ms": round(total_ms, 3), "revision": revision,
            "hash_ok": True,
        })
        previous = upstream
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.getenv("PI_DELTA_URL", "http://127.0.0.1:18080"))
    parser.add_argument("--model", default=os.getenv("PI_DELTA_MODEL", "qwen3-0.6b"))
    parser.add_argument("--fingerprint", default=os.getenv("PI_DELTA_MODEL_FINGERPRINT", "qwen3-0.6b@v1"))
    parser.add_argument("--turns", type=int, default=10)
    parser.add_argument("--prefix-kb", type=int, default=64)
    parser.add_argument("--output", default="benchmarks/results/benchmark.csv")
    args = parser.parse_args()
    token = os.getenv("PI_DELTA_GATEWAY_TOKEN", "")
    if not token:
        parser.error("PI_DELTA_GATEWAY_TOKEN must be set")
    payloads = list(corpus(args.turns, args.prefix_kb, args.model))
    data = []
    with httpx.Client(timeout=300) as client:
        for mode in ("full", "gzip", "delta", "delta-gzip"):
            rows = run_mode(client, args.url, token, mode, payloads, args.fingerprint)
            data.extend(rows)
            print(mode, "uploaded HTTP request bytes:", sum(r["http_request_body_bytes"] for r in rows))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
    print("Wrote", output)
    print("Note: HTTP body size != encrypted LAN wire bytes, and first-byte time != model text TTFT.")


if __name__ == "__main__":
    main()
