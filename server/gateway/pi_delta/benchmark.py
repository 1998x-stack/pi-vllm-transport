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
    """Return HTTP-body metrics; full/gzip hit the raw OpenAI proxy, delta modes use versioned packets."""
    import codecs
    sid, bid = str(uuid.uuid4()), str(uuid.uuid4())
    previous = None
    revision = None
    prev_hash = None
    rows = []
    for turn, upstream in enumerate(payloads):
        if mode in ("full", "gzip"):
            target = url + "/v1/chat/completions"
            body_obj = upstream
        else:
            packet = {
                "protocol": "pi-delta/v1", "request_id": str(uuid.uuid4()),
                "session_id": sid, "branch_id": bid,
                "model_fingerprint": fingerprint,
                "expected_request_sha256": digest(upstream),
            }
            if previous is None:
                packet.update({
                    "kind": "full", "base_revision": None, "base_hash": None,
                    "full": {"request": upstream},
                })
            else:
                packet.update({
                    "kind": "delta", "base_revision": revision, "base_hash": prev_hash,
                    "delta": make_delta(previous, upstream),
                })
            target = url + "/delta/v1/infer"
            body_obj = packet
        raw = json.dumps(body_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encoded = gzip.compress(raw) if mode in ("gzip", "delta-gzip") else raw
        headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
        if mode in ("gzip", "delta-gzip"):
            headers["Content-Encoding"] = "gzip"
        started = time.perf_counter()
        with client.stream("POST", target, content=encoded, headers=headers) as res:
            if res.status_code != 200:
                raise RuntimeError(f"{mode} turn={turn} HTTP {res.status_code}: {res.read()[:500]!r}")
            if mode.startswith("delta"):
                revision = int(res.headers["X-Pi-Delta-Revision"])
                prev_hash = res.headers["X-Pi-Delta-Request-Hash"]
                if prev_hash != digest(upstream):
                    raise RuntimeError("Gateway reconstructed request hash mismatch")
            first_byte_ms = None
            first_content_ms = None
            prompt_tokens = None
            response_bytes = 0
            decoder = codecs.getincrementaldecoder("utf-8")()
            text_buffer = ""
            for chunk in res.iter_bytes():
                if first_byte_ms is None:
                    first_byte_ms = 1000 * (time.perf_counter() - started)
                response_bytes += len(chunk)
                text_buffer += decoder.decode(chunk)
                normalized = text_buffer.replace("\r\n", "\n")
                events = normalized.split("\n\n")
                text_buffer = events.pop()
                for event in events:
                    for line in event.split("\n"):
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(obj.get("usage"), dict):
                            prompt_tokens = obj["usage"].get("prompt_tokens", prompt_tokens)
                        for choice in obj.get("choices", []):
                            d = choice.get("delta") or {}
                            if d.get("content") or d.get("tool_calls"):
                                if first_content_ms is None:
                                    first_content_ms = 1000 * (time.perf_counter() - started)
            total_ms = 1000 * (time.perf_counter() - started)
        rows.append({
            "mode": mode, "turn": turn,
            "full_request_bytes": len(json.dumps(upstream, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
            "raw_packet_bytes": len(raw), "http_request_body_bytes": len(encoded),
            "response_body_bytes": response_bytes,
            "first_byte_ms": round(first_byte_ms, 3) if first_byte_ms is not None else "",
            "ttft_ms": round(first_content_ms, 3) if first_content_ms is not None else "",
            "total_ms": round(total_ms, 3), "prompt_tokens": prompt_tokens if prompt_tokens is not None else "",
            "revision": revision if mode.startswith("delta") else "",
            "hash_ok": mode.startswith("delta") and prev_hash == digest(upstream),
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
    print("Note: HTTP body size != SSH-encrypted LAN wire bytes; ttft_ms means first SSE text/tool-call delta.")


if __name__ == "__main__":
    main()
