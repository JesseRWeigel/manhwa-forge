"""Local, transactional status storage. No prompts, paths or provider data."""
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path


def valid_job_id(job_id: str) -> bool:
    """IDs are UUID prefixes, not paths."""
    return re.fullmatch(r"[a-f0-9]{12}", job_id) is not None


class JobStatusStore:
    """Tiny SQLite index for one local server, independent of live SSE history."""

    def __init__(self, path: Path, instance: str):
        self.path = path
        self.instance = instance
        with closing(self._connect()) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS jobs ("
                " id TEXT PRIMARY KEY, instance TEXT NOT NULL, status TEXT NOT NULL"
                " CHECK (status IN ('pending', 'running', 'done', 'error'))"
                ")"
            )

    def _connect(self) -> sqlite3.Connection:
        if self.path.is_symlink():
            raise sqlite3.OperationalError("job database must not be a symbolic link")
        return sqlite3.connect(self.path)

    def reserve(self, job_id: str) -> None:
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT INTO jobs (id, instance, status) VALUES (?, ?, 'pending')",
                (job_id, self.instance),
            )

    def transition(self, job_id: str, status: str) -> None:
        before = {
            "running": ("pending",),
            "done": ("running",),
            "error": ("pending", "running"),
        }[status]
        placeholders = ", ".join("?" for _ in before)
        with closing(self._connect()) as db, db:
            changed = db.execute(
                "UPDATE jobs SET status = ? WHERE id = ? AND instance = ? "
                f"AND status IN ({placeholders})",
                (status, job_id, self.instance, *before),
            ).rowcount
            if changed != 1:
                raise sqlite3.OperationalError("invalid local job transition")

    def read(self, job_id: str) -> str | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT instance, status FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        instance, status = row
        if instance != self.instance and status in ("pending", "running"):
            return "interrupted"
        return status
