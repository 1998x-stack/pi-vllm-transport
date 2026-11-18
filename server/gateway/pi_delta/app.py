"""OpenAI-compatible SSE proxy + pi-delta/v1 session gateway (loopback only)."""
from __future__ import annotations

import gzip
import json
import os
import time
import uuid
import zlib
from dataclasses import dataclass
from hmac import compare_digest
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .core import ProtocolError, digest, validate_request
from .state import SnapshotStore


@dataclass(frozen=True)
class Settings:
    token: str
    upstream: str = "http://127.0.0.1:8000"
    model: str = "qwen3-0.6b"
    fingerprint: str = "qwen3-0.6b@v1"
    db_path: str = "./data/sessions.sqlite"
    max_body: int = 16 * 1024 * 1024
    max_decompressed: int = 64 * 1024 * 1024

    @classmethod
    def from_env(cls):
        token = os.environ.get("PI_DELTA_GATEWAY_TOKEN", "")
        if not token:
            raise RuntimeError("PI_DELTA_GATEWAY_TOKEN must be set; refusing unauthenticated startup")
        return cls(
            token=token,
            upstream=os.getenv("PI_DELTA_UPSTREAM", "http://127.0.0.1:8000"),
            model=os.getenv("PI_DELTA_MODEL", "qwen3-0.6b"),
            fingerprint=os.getenv("PI_DELTA_MODEL_FINGERPRINT", "qwen3-0.6b@v1"),
            db_path=os.getenv("PI_DELTA_DB", "./data/sessions.sqlite"),
        )


def _unpack(raw: bytes, encoding: str, limit: int) -> bytes:
    if encoding in ("", "identity"):
        return raw
    if encoding != "gzip":
        raise ProtocolError("UNSUPPORTED_ENCODING", "expected identity or gzip", 415)
    try:
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        expanded = decoder.decompress(raw, limit + 1)
        if len(expanded) > limit or decoder.unconsumed_tail:
            raise ProtocolError("PAYLOAD_TOO_LARGE", "decompressed input exceeds limit", 413)
        expanded += decoder.flush(limit + 1 - len(expanded))
        if len(expanded) > limit or not decoder.eof or decoder.unused_data:
            raise ProtocolError("INVALID_GZIP", "gzip stream invalid or exceeds limit", 400)
        return expanded
    except zlib.error as exc:
        raise ProtocolError("INVALID_GZIP", "invalid gzip body", 400) from exc


def _error(code, reason, status, request_id=None):
    return JSONResponse(
        {"error": {"code": code, "message": reason, "request_id": request_id, "retryable": status >= 500}},
        status_code=status,
    )


def create_app(settings: Settings, transport: Optional[httpx.AsyncBaseTransport] = None) -> FastAPI:
    app = FastAPI(title="pi-vllm-delta-gateway", version="0.1.0")
    app.state.store = SnapshotStore(settings.db_path, settings.model, settings.fingerprint)
    app.state.upstream_transport = transport
    app.state.stats = {"requests": 0, "received_body_bytes": 0, "decoded_body_bytes": 0, "accepted": 0}

    @app.on_event("shutdown")
    def _close():
        app.state.store.close()

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "service": "pi-delta"}

    @app.get("/delta/v1/capabilities")
    def capabilities():
        return {
            "protocol": "pi-delta/v1",
            "modes": ["full", "gzip", "delta", "delta-gzip"],
            "model": settings.model,
            "model_fingerprint": settings.fingerprint,
            "max_body_bytes": settings.max_body,
            "max_decompressed_bytes": settings.max_decompressed,
        }

    @app.get("/delta/v1/metrics")
    def metrics(request: Request):
        token = request.headers.get("authorization", "")
        if not compare_digest(token, "Bearer " + settings.token):
            return _error("UNAUTHORIZED", "invalid bearer token", 401)
        return dict(app.state.stats)

    @app.post("/delta/v1/infer")
    @app.post("/v1/chat/completions")
    async def inference(request: Request):
        rid = None
        if not compare_digest(request.headers.get("authorization", ""), "Bearer " + settings.token):
            return _error("UNAUTHORIZED", "invalid bearer token", 401)
        raw = await request.body()
        if len(raw) > settings.max_body:
            return _error("PAYLOAD_TOO_LARGE", "encoded body limit exceeded", 413)
        try:
            body = _unpack(raw, request.headers.get("content-encoding", "").lower(), settings.max_decompressed)
            app.state.stats["requests"] += 1
            app.state.stats["received_body_bytes"] += len(raw)
            app.state.stats["decoded_body_bytes"] += len(body)
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ProtocolError("INVALID_JSON", "request must be a JSON object", 400)
            headers = {}
            if request.url.path == "/delta/v1/infer":
                packet = payload
                rid = packet.get("request_id")
                upstream, revision, sha = app.state.store.apply(packet)
                headers = {
                    "X-Pi-Delta-Revision": str(revision),
                    "X-Pi-Delta-Request-Hash": sha,
                    "X-Pi-Delta-Request-Id": rid,
                }
            elif request.headers.get("x-pi-delta-wire") == "pi-delta/v1":
                mode = request.headers.get("x-pi-delta-mode", "")
                sid = request.headers.get("x-pi-delta-session", "")
                bid = request.headers.get("x-pi-delta-branch", "")
                rid = request.headers.get("x-pi-delta-request-id", "")
                fingerprint = request.headers.get("x-pi-delta-model-fingerprint", "")
                if mode == "full":
                    packet = {
                        "protocol": "pi-delta/v1",
                        "request_id": rid, "session_id": sid, "branch_id": bid,
                        "kind": "full", "base_revision": None, "base_hash": None,
                        "model_fingerprint": fingerprint,
                        "expected_request_sha256": digest(payload),
                        "full": {"request": payload},
                    }
                elif mode == "delta":
                    messages = payload.get("messages", [])
                    if len(messages) != 1 or messages[0].get("role") != "user" or not isinstance(messages[0].get("content"), str):
                        raise ProtocolError("INVALID_DELTA", "delta envelope must be a single user message", 400)
                    packet = json.loads(messages[0]["content"])
                    if not isinstance(packet, dict) or any(
                        packet.get(key) != expected for key, expected in (
                            ("request_id", rid), ("session_id", sid), ("branch_id", bid),
                            ("model_fingerprint", fingerprint), ("kind", "delta")
                        )
                    ):
                        raise ProtocolError("INVALID_DELTA", "delta envelope/header identity mismatch", 400)
                else:
                    raise ProtocolError("INVALID_MODE", "x-pi-delta-mode must be full or delta", 400)
                upstream, revision, sha = app.state.store.apply(packet)
                headers = {
                    "X-Pi-Delta-Revision": str(revision),
                    "X-Pi-Delta-Request-Hash": sha,
                    "X-Pi-Delta-Request-Id": rid,
                }
            else:
                upstream = payload
                validate_request(upstream, settings.model)
            app.state.stats["accepted"] += 1
        except ProtocolError as exc:
            return _error(exc.code, str(exc), exc.status, rid)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            return _error("INVALID_REQUEST", "invalid JSON or missing request fields", 400, rid)

        client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0), transport=app.state.upstream_transport)
        try:
            upstream_request = client.build_request(
                "POST",
                settings.upstream.rstrip("/") + "/v1/chat/completions",
                json=upstream,
                headers={"Content-Type": "application/json"},
            )
            response = await client.send(upstream_request, stream=True)
        except httpx.HTTPError:
            await client.aclose()
            return _error("UPSTREAM_UNAVAILABLE", "unable to connect to configured vLLM", 502, rid)
        if response.status_code >= 400:
            content = await response.aread()
            await response.aclose()
            await client.aclose()
            return JSONResponse(
                {"error": {"code": "UPSTREAM_ERROR", "message": content[:512].decode("utf-8", "replace"),
                           "request_id": rid, "retryable": response.status_code >= 500}},
                status_code=response.status_code,
            )

        async def body_stream():
            try:
                async for chunk in response.aiter_raw():
                    yield chunk
            finally:
                await response.aclose()
                await client.aclose()

        # Don't copy headers from vLLM indiscriminately (Content-Length, Authorization, etc).
        return StreamingResponse(body_stream(), status_code=200, media_type="text/event-stream", headers={
            **headers, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"
        })

    return app


def make_app() -> FastAPI:
    return create_app(Settings.from_env())


# uvicorn --factory pi_delta.app:make_app --host 127.0.0.1 --port 18080
