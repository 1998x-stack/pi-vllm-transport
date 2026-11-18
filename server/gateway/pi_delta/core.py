"""Canonical request hashing and lossless message suffix deltas."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_PATH = Path(__file__).resolve().parents[3] / "protocol" / "pi-delta-v1.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


class ProtocolError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.status = status


def canonical(value: Any) -> bytes:
    try:
        return rfc8785.dumps(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ProtocolError("INVALID_JSON", "Input cannot be canonically encoded") from exc


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def validate(packet: dict) -> None:
    errors = sorted(VALIDATOR.iter_errors(packet), key=lambda e: tuple(map(str, e.path)))
    if errors:
        raise ProtocolError("INVALID_PACKET", "pi-delta/v1 schema violation: " + errors[0].message, 400)


def validate_request(request: dict, model_name: str) -> None:
    if not isinstance(request, dict):
        raise ProtocolError("INVALID_REQUEST", "upstream request must be a JSON object", 400)
    if request.get("model") != model_name:
        raise ProtocolError("MODEL_MISMATCH", "model is not the configured backend model", 422)
    if not isinstance(request.get("messages"), list) or not request["messages"]:
        raise ProtocolError("INVALID_REQUEST", "messages must be a nonempty array", 422)
    if request.get("stream") is not True:
        raise ProtocolError("INVALID_REQUEST", "only stream=true requests are supported", 422)
    for message in request["messages"]:
        if not isinstance(message, dict) or message.get("role") not in (
            "system", "developer", "user", "assistant", "tool"
        ):
            raise ProtocolError("INVALID_REQUEST", "invalid chat message", 422)


def envelope(request: dict) -> dict:
    return {k: v for k, v in request.items() if k != "messages"}


def reconstruct(previous: dict, delta: dict) -> dict:
    before = previous["messages"]
    keep = delta["keep_count"]
    if not isinstance(keep, int) or isinstance(keep, bool) or keep < 0 or keep > len(before):
        raise ProtocolError("INVALID_DELTA", "keep_count out of range", 422)
    env = delta["envelope"]
    if env["kind"] == "ref":
        current_envelope = envelope(previous)
        if digest(current_envelope) != env["sha256"]:
            raise ProtocolError("INVALID_ENVELOPE", "cached envelope hash mismatch", 422)
    else:
        current_envelope = env["value"]
    result = dict(current_envelope)
    result["messages"] = before[:keep] + delta["append_messages"]
    return result


def make_delta(previous: dict, current: dict) -> dict:
    """Reference encoder used by CLI benchmarks; production Pi has its own JS implementation."""
    old, new = previous["messages"], current["messages"]
    keep = 0
    while keep < min(len(old), len(new)) and digest(old[keep]) == digest(new[keep]):
        keep += 1
    return {
        "keep_count": keep,
        "append_messages": new[keep:],
        "envelope": (
            {"kind": "ref", "sha256": digest(envelope(previous))}
            if digest(envelope(previous)) == digest(envelope(current))
            else {"kind": "replace", "value": envelope(current)}
        ),
    }
