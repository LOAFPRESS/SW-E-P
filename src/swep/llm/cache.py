"""Persistent response cache (REQ-1.17, optional feature).

Rationale: a gold subset of 150 comments costs two calls each, and prompt
tuning means re-running the same inputs many times.  Caching by
``(model, temperature, max_output_tokens, messages)`` makes re-runs free and
idempotent, and a cache hit is reported as such in the output CSV.

SQLite is used instead of JSON so that an interrupted run leaves a valid file
behind and lookups stay O(log n).
"""

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

from ..logging_utils import get_logger

_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
    key        TEXT PRIMARY KEY,
    model      TEXT NOT NULL,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class ResponseCache:
    """Content-addressed store of successful LLM responses."""

    def __init__(self, path, enabled: bool = True):
        self.path = Path(path) if path is not None else None
        self.enabled = bool(enabled) and self.path is not None
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        if self.enabled:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
            self._conn.execute(_SCHEMA)
            self._conn.commit()

    # ----------------------------------------------------------------- keys
    @staticmethod
    def make_key(
        model: str,
        temperature: float,
        max_output_tokens: int,
        messages: List[dict],
        params: Optional[dict] = None,
    ) -> str:
        """Stable key over everything that can change the completion."""
        canonical = json.dumps(
            {
                "model": model,
                "temperature": float(temperature),
                "max_output_tokens": int(max_output_tokens),
                "messages": messages,
                "params": params or {},
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------- read/write
    def get(self, key: str) -> Optional[dict]:
        if not self.enabled or self._conn is None:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM responses WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:  # corrupt row: treat as a miss
            get_logger().warning("cache entry %s is corrupt; ignoring", key[:12])
            return None

    def put(self, key: str, model: str, payload: dict):
        if not self.enabled or self._conn is None:
            return
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO responses(key, model, payload) VALUES (?, ?, ?)",
                (key, model, json.dumps(payload, ensure_ascii=False)),
            )
            self._conn.commit()

    def count(self) -> int:
        if not self.enabled or self._conn is None:
            return 0
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0])

    def close(self):
        if self._conn is not None:
            with self._lock:
                self._conn.close()
                self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
