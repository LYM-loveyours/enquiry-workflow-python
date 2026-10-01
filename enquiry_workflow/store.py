"""SQLite state machine. No network work occurs while a transaction is held."""

import hashlib
import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import Enquiry


class ConflictError(Exception):
    pass


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                """CREATE TABLE IF NOT EXISTS enquiries (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
                state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                updated REAL NOT NULL)"""
            )

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    @staticmethod
    def payload(enquiry: Enquiry) -> tuple[str, str]:
        data = json.dumps(enquiry.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return data, hashlib.sha256(data.encode()).hexdigest()

    def register(self, enquiry: Enquiry) -> tuple[dict[str, Any], bool]:
        data, fingerprint = self.payload(enquiry)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                cursor = db.execute(
                    "INSERT OR IGNORE INTO enquiries VALUES (?, ?, ?, 'pending', 0, ?)",
                    (enquiry.enquiry_id, fingerprint, data, time.time()),
                )
                row = db.execute(
                    "SELECT * FROM enquiries WHERE id=?", (enquiry.enquiry_id,)
                ).fetchone()
                assert row is not None
                if row["fingerprint"] != fingerprint:
                    raise ConflictError(
                        "An existing identifier cannot be reused for a different payload."
                    )
                db.execute("COMMIT")
                return dict(row), cursor.rowcount == 0
            except Exception:
                db.execute("ROLLBACK")
                raise

    def claim(self, identifier: str) -> bool:
        with self.connection() as db:
            result = db.execute(
                """UPDATE enquiries SET state='processing', attempts=attempts+1, updated=?
                WHERE id=? AND state IN ('pending','retryable') AND attempts < 3""",
                (time.time(), identifier),
            )
            return result.rowcount == 1

    def finish(self, identifier: str, state: str) -> None:
        with self.connection() as db:
            db.execute(
                "UPDATE enquiries SET state=?, updated=? WHERE id=? AND state='processing'",
                (state, time.time(), identifier),
            )

    def get(self, identifier: str) -> dict[str, Any] | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM enquiries WHERE id=?", (identifier,)).fetchone()
            return dict(row) if row is not None else None

    def quarantine_stale(self, older_than_seconds: float = 300) -> int:
        """A crashed delivery may have succeeded. Never automatically retry it."""
        with self.connection() as db:
            result = db.execute(
                "UPDATE enquiries SET state='uncertain', updated=? "
                "WHERE state='processing' AND updated < ?",
                (time.time(), time.time() - older_than_seconds),
            )
            return result.rowcount
