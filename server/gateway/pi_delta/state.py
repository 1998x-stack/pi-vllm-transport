"""Transactional SQLite snapshot store with revision isolation and request idempotency."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

from .core import ProtocolError, digest, reconstruct, validate, validate_request


class SnapshotStore:
    def __init__(self, path: str, model: str, fingerprint: str, ttl_seconds: int = 86400, max_branches: int = 100):
        self.path = path
        self.model = model
        self.fingerprint = fingerprint
        self.ttl_seconds = ttl_seconds
        self.max_branches = max_branches
        if path != ":memory:":
            db = Path(path).expanduser().resolve()
            db.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                os.chmod(db.parent, 0o700)
            except OSError:
                pass
        self._lock = threading.RLock()
        # One persistent connection also permits an in-memory store in unit tests.
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA busy_timeout = 30000")
        self._db.execute("PRAGMA secure_delete = ON")
        if path != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS branches (
              session_id TEXT NOT NULL,
              branch_id TEXT NOT NULL,
              revision INTEGER NOT NULL,
              request_hash TEXT NOT NULL,
              model_fingerprint TEXT NOT NULL,
              request_json TEXT NOT NULL,
              updated_at REAL NOT NULL DEFAULT 0,
              PRIMARY KEY(session_id, branch_id)
            );
            CREATE TABLE IF NOT EXISTS requests (
              request_id TEXT PRIMARY KEY,
              packet_hash TEXT NOT NULL,
              session_id TEXT NOT NULL,
              branch_id TEXT NOT NULL,
              target_revision INTEGER NOT NULL,
              request_hash TEXT NOT NULL,
              created_at REAL NOT NULL DEFAULT 0
            );
        """)
        # Existing development databases from the initial code need additive migration.
        for table, column, ddl in (
            ("branches", "updated_at", "REAL NOT NULL DEFAULT 0"),
            ("requests", "created_at", "REAL NOT NULL DEFAULT 0"),
        ):
            cols = {row["name"] for row in self._db.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def get(self, session: str, branch: str):
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM branches WHERE session_id=? AND branch_id=?", (session, branch)
            ).fetchone()
        return dict(row) if row is not None else None

    def apply(self, packet: dict) -> tuple[dict, int, str]:
        validate(packet)
        if packet["model_fingerprint"] != self.fingerprint:
            raise ProtocolError("MODEL_FINGERPRINT_MISMATCH", "model deployment fingerprint changed", 409)
        sid, bid, rid = packet["session_id"], packet["branch_id"], packet["request_id"]
        packet_hash = digest(packet)
        with self._lock:
            db = self._db
            db.execute("BEGIN IMMEDIATE")
            try:
                now = time.time()
                cutoff = now - self.ttl_seconds
                db.execute("DELETE FROM branches WHERE updated_at < ?", (cutoff,))
                db.execute("DELETE FROM requests WHERE created_at < ?", (cutoff,))
                old_request = db.execute("SELECT packet_hash FROM requests WHERE request_id=?", (rid,)).fetchone()
                if old_request:
                    code = "IDEMPOTENT_REPLAY" if old_request["packet_hash"] == packet_hash else "IDEMPOTENCY_CONFLICT"
                    raise ProtocolError(code, "request_id has already been accepted", 409)
                row = db.execute(
                    "SELECT * FROM branches WHERE session_id=? AND branch_id=?", (sid, bid)
                ).fetchone()
                if packet["kind"] == "full":
                    if row:
                        raise ProtocolError("BRANCH_ALREADY_EXISTS", "full resync requires a new branch_id", 409)
                    count = db.execute("SELECT COUNT(*) FROM branches").fetchone()[0]
                    if count >= self.max_branches:
                        raise ProtocolError("SESSION_LIMIT", "maximum active branches reached", 429)
                    upstream = packet["full"]["request"]
                    revision = 1
                else:
                    if row is None:
                        raise ProtocolError("SESSION_EXPIRED", "session/branch not found; full resync required", 410)
                    if row["revision"] != packet["base_revision"] or row["request_hash"] != packet["base_hash"]:
                        raise ProtocolError("VERSION_CONFLICT", "stale base_revision or base_hash", 409)
                    if row["model_fingerprint"] != packet["model_fingerprint"]:
                        raise ProtocolError("MODEL_FINGERPRINT_MISMATCH", "stored model fingerprint differs", 409)
                    upstream = reconstruct(json.loads(row["request_json"]), packet["delta"])
                    revision = row["revision"] + 1
                validate_request(upstream, self.model)
                request_hash = digest(upstream)
                if request_hash != packet["expected_request_sha256"]:
                    raise ProtocolError("HASH_MISMATCH", "reconstructed upstream request hash mismatch", 422)
                serialized = json.dumps(upstream, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                if row is None:
                    db.execute(
                        "INSERT INTO branches VALUES(?,?,?,?,?,?,?)",
                        (sid, bid, revision, request_hash, self.fingerprint, serialized, now),
                    )
                else:
                    db.execute(
                        "UPDATE branches SET revision=?,request_hash=?,model_fingerprint=?,request_json=?,updated_at=? "
                        "WHERE session_id=? AND branch_id=?",
                        (revision, request_hash, self.fingerprint, serialized, now, sid, bid),
                    )
                db.execute(
                    "INSERT INTO requests VALUES (?,?,?,?,?,?,?)",
                    (rid, packet_hash, sid, bid, revision, request_hash, now),
                )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return upstream, revision, request_hash
