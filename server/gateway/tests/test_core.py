import json
import uuid

import pytest

from pi_delta.core import ProtocolError, digest, envelope, make_delta, reconstruct, validate
from pi_delta.state import SnapshotStore


def packet(request, branch=None, request_id=None):
    return {
        "protocol": "pi-delta/v1",
        "request_id": request_id or str(uuid.uuid4()),
        "session_id": str(uuid.uuid4()),
        "branch_id": branch or str(uuid.uuid4()),
        "kind": "full",
        "base_revision": None,
        "base_hash": None,
        "model_fingerprint": "qwen3-0.6b@v1",
        "expected_request_sha256": digest(request),
        "full": {"request": request},
    }


def req(messages, **kwargs):
    return {"model": "qwen3-0.6b", "stream": True, "messages": messages, **kwargs}


def test_canonical_stable_keys_and_unicode():
    assert digest({"b": [1, "中文", None], "a": True}) == digest({"a": True, "b": [1, "中文", None]})
    assert digest({"a": 1}) == digest({"a": 1.0})  # RFC8785 number normalization


def test_delta_append_and_replace():
    old = req([{"role": "user", "content": "one"}], max_tokens=64)
    new = req(old["messages"] + [{"role": "assistant", "content": "two"}], max_tokens=64)
    patch = make_delta(old, new)
    assert patch["keep_count"] == 1
    assert patch["envelope"]["kind"] == "ref"
    assert reconstruct(old, patch) == new
    changed = req([{"role": "user", "content": "edited"}], max_tokens=32)
    patch = make_delta(old, changed)
    assert patch["keep_count"] == 0
    assert patch["envelope"]["kind"] == "replace"
    assert reconstruct(old, patch) == changed


def test_bad_keep_and_envelope_ref():
    old = req([{"role": "user", "content": "hi"}])
    with pytest.raises(ProtocolError) as exc:
        reconstruct(old, {"keep_count": 20, "append_messages": [], "envelope": {"kind": "ref", "sha256": digest(envelope(old))}})
    assert exc.value.code == "INVALID_DELTA"
    with pytest.raises(ProtocolError) as exc:
        reconstruct(old, {"keep_count": 1, "append_messages": [], "envelope": {"kind": "ref", "sha256": "sha256:" + "0" * 64}})
    assert exc.value.code == "INVALID_ENVELOPE"


def test_schema_and_revisions(tmp_path):
    store = SnapshotStore(str(tmp_path / "sessions.sqlite"), "qwen3-0.6b", "qwen3-0.6b@v1")
    first = req([{"role": "user", "content": "hello"}], tools=[{"type": "function", "function": {"name": "sum", "parameters": {"type": "object"}}}])
    p1 = packet(first)
    validate(p1)
    got, r1, h1 = store.apply(p1)
    assert got == first
    assert r1 == 1 and h1 == digest(first)
    p2 = {
        **{k: v for k, v in p1.items() if k not in ("kind", "full", "base_revision", "base_hash", "expected_request_sha256", "request_id")},
        "request_id": str(uuid.uuid4()),
        "kind": "delta",
        "base_revision": 1,
        "base_hash": h1,
        "expected_request_sha256": digest(req(first["messages"] + [{"role": "assistant", "content": "ok"}], tools=first["tools"])),
        "delta": make_delta(first, req(first["messages"] + [{"role": "assistant", "content": "ok"}], tools=first["tools"])),
    }
    got, r2, h2 = store.apply(p2)
    assert r2 == 2 and h2 == digest(got)
    assert got["messages"][-1]["content"] == "ok"
    with pytest.raises(ProtocolError, match="already been accepted"):
        store.apply(p2)
    stale = {**p2, "request_id": str(uuid.uuid4())}
    with pytest.raises(ProtocolError) as exc:
        store.apply(stale)
    assert exc.value.code == "VERSION_CONFLICT"
    collision = {**p1, "request_id": str(uuid.uuid4())}
    with pytest.raises(ProtocolError) as exc:
        store.apply(collision)
    assert exc.value.code == "BRANCH_ALREADY_EXISTS"
    assert store.get(p1["session_id"], p1["branch_id"])["revision"] == 2
    store.close()


def test_invalid_hash_rejects_without_mutating(tmp_path):
    store = SnapshotStore(str(tmp_path / "x.sqlite"), "qwen3-0.6b", "qwen3-0.6b@v1")
    p = packet(req([{"role": "user", "content": "hello"}]))
    p["expected_request_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ProtocolError) as exc:
        store.apply(p)
    assert exc.value.code == "HASH_MISMATCH"
    assert store.get(p["session_id"], p["branch_id"]) is None
    store.close()


def test_fingerprint_change_requires_reset(tmp_path):
    store = SnapshotStore(str(tmp_path / "x.sqlite"), "qwen3-0.6b", "qwen3-0.6b@v1")
    p = packet(req([{"role": "user", "content": "hello"}]))
    p["model_fingerprint"] = "qwen3-0.6b@another"
    with pytest.raises(ProtocolError) as exc:
        store.apply(p)
    assert exc.value.code == "MODEL_FINGERPRINT_MISMATCH"
    store.close()


def test_tool_calls_survive_delta():
    old = req([{"role": "user", "content": "sum"}], tools=[{"type": "function", "function": {"name": "sum", "parameters": {}}}])
    new = req(old["messages"] + [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function",
         "function": {"name": "sum", "arguments": "{\"a\":1,\"b\":2}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "3"},
    ], tools=old["tools"])
    assert reconstruct(old, make_delta(old, new)) == new
