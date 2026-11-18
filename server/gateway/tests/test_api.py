import gzip
import json
import uuid

import httpx
from fastapi.testclient import TestClient

from pi_delta.app import Settings, create_app
from pi_delta.core import digest, make_delta


SSE = b'data: {"id":"chatcmpl-test","choices":[{"delta":{"content":"OK"},"index":0}]}\n\ndata: [DONE]\n\n'


def request(messages):
    return {"model": "qwen3-0.6b", "messages": messages, "stream": True, "max_tokens": 16}


def packet(payload, session_id=None, branch_id=None, rid=None):
    return {
        "protocol": "pi-delta/v1",
        "request_id": rid or str(uuid.uuid4()),
        "session_id": session_id or str(uuid.uuid4()),
        "branch_id": branch_id or str(uuid.uuid4()),
        "kind": "full",
        "base_revision": None,
        "base_hash": None,
        "model_fingerprint": "qwen3-0.6b@v1",
        "expected_request_sha256": digest(payload),
        "full": {"request": payload},
    }


def build_client(tmp_path):
    upstream_seen = []
    def fake(req):
        upstream_seen.append(json.loads(req.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=SSE)
    app = create_app(
        Settings(token="secret-token", upstream="http://fake", db_path=str(tmp_path / "db.sqlite")),
        transport=httpx.MockTransport(fake)
    )
    return TestClient(app), upstream_seen


def test_auth_required_and_health(tmp_path):
    with build_client(tmp_path)[0] as client:
        assert client.get("/healthz").status_code == 200
        assert client.post("/delta/v1/infer", json={}).status_code == 401


def test_full_delta_sse_and_wire_bytes(tmp_path):
    client, upstream_seen = build_client(tmp_path)
    headers = {"Authorization": "Bearer secret-token"}
    old = request([{"role": "user", "content": "A" * 10000}])
    p1 = packet(old)
    with client:
        first = client.post("/delta/v1/infer", json=p1, headers=headers)
        assert first.status_code == 200
        assert b"[DONE]" in first.content
        assert first.headers["x-pi-delta-revision"] == "1"
        new = request(old["messages"] + [{"role": "assistant", "content": "OK"}, {"role": "user", "content": "go"}])
        p2 = {
            **{k: v for k, v in p1.items() if k not in ["kind", "full", "base_revision", "base_hash", "expected_request_sha256", "request_id"]},
            "request_id": str(uuid.uuid4()),
            "kind": "delta",
            "base_revision": 1,
            "base_hash": digest(old),
            "expected_request_sha256": digest(new),
            "delta": make_delta(old, new),
        }
        second = client.post("/delta/v1/infer", json=p2, headers=headers)
        assert second.status_code == 200
        assert second.headers["x-pi-delta-revision"] == "2"
        assert upstream_seen == [old, new]
        assert len(json.dumps(p2)) < len(json.dumps(p1))
        metrics = client.get("/delta/v1/metrics", headers=headers).json()
        assert metrics["accepted"] == 2


def test_pi_hook_wire_wrapper(tmp_path):
    client, upstream_seen = build_client(tmp_path)
    old = request([{"role": "user", "content": "hello"}])
    p1 = packet(old)
    headers = {
        "Authorization": "Bearer secret-token", "X-Pi-Delta-Wire": "pi-delta/v1",
        "X-Pi-Delta-Mode": "full", "X-Pi-Delta-Session": p1["session_id"],
        "X-Pi-Delta-Branch": p1["branch_id"], "X-Pi-Delta-Request-Id": p1["request_id"],
        "X-Pi-Delta-Model-Fingerprint": p1["model_fingerprint"],
    }
    with client:
        result = client.post("/v1/chat/completions", json=old, headers=headers)
        assert result.status_code == 200
        assert result.headers["x-pi-delta-request-hash"] == digest(old)
        new = request(old["messages"] + [{"role": "assistant", "content": "OK"}])
        p2 = {
            **{k: v for k, v in p1.items() if k not in ["kind", "full", "base_revision", "base_hash", "expected_request_sha256", "request_id"]},
            "request_id": str(uuid.uuid4()), "kind": "delta", "base_revision": 1,
            "base_hash": digest(old), "expected_request_sha256": digest(new),
            "delta": make_delta(old, new),
        }
        headers["X-Pi-Delta-Mode"] = "delta"
        headers["X-Pi-Delta-Request-Id"] = p2["request_id"]
        wrapped = {"model": "qwen3-0.6b", "stream": True, "messages": [{"role": "user", "content": json.dumps(p2)}]}
        result = client.post("/v1/chat/completions", json=wrapped, headers=headers)
        assert result.status_code == 200
        assert upstream_seen == [old, new]


def test_bad_gzip_rejected_and_valid_gzip_works(tmp_path):
    client, upstream_seen = build_client(tmp_path)
    headers = {"Authorization": "Bearer secret-token", "Content-Encoding": "gzip"}
    p1 = packet(request([{"role": "user", "content": "hello"}]))
    with client:
        assert client.post("/delta/v1/infer", content=b"not-gzip", headers=headers).status_code == 400
        compressed = gzip.compress(json.dumps(p1).encode("utf-8"))
        assert client.post("/delta/v1/infer", content=compressed, headers=headers).status_code == 200
        assert len(upstream_seen) == 1


def test_raw_openai_proxy(tmp_path):
    client, seen = build_client(tmp_path)
    req = request([{"role": "user", "content": "test"}])
    with client:
        res = client.post("/v1/chat/completions", headers={"Authorization": "Bearer secret-token"}, json=req)
        assert res.status_code == 200
        assert seen == [req]
