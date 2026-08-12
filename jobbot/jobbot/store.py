from __future__ import annotations

import sqlite3
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_jobs (
    uid        TEXT PRIMARY KEY,
    title      TEXT,
    url        TEXT,
    first_seen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (
    uid     TEXT NOT NULL,
    ts      REAL NOT NULL,
    status  TEXT NOT NULL,   -- applied | notified | failed | skipped
    detail  TEXT
);
"""


class Store:
    """SQLite-backed dedupe + application log. Single-threaded async use."""

    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def mark_seen(self, uid: str, title: str, url: str) -> bool:
        """Record a job. Returns True only the first time a uid is seen."""
        cur = self._db.execute(
            "INSERT OR IGNORE INTO seen_jobs (uid, title, url, first_seen) VALUES (?, ?, ?, ?)",
            (uid, title, url, time.time()),
        )
        self._db.commit()
        return cur.rowcount == 1

    def record(self, uid: str, status: str, detail: str = "") -> None:
        self._db.execute(
            "INSERT INTO applications (uid, ts, status, detail) VALUES (?, ?, ?, ?)",
            (uid, time.time(), status, detail),
        )
        self._db.commit()

    def applications_in_last(self, seconds: float) -> int:
        cur = self._db.execute(
            "SELECT COUNT(*) FROM applications WHERE status = 'applied' AND ts > ?",
            (time.time() - seconds,),
        )
        return int(cur.fetchone()[0])

    def close(self) -> None:
        self._db.close()
