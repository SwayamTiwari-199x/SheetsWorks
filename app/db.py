"""SQLite storage.

Plain sqlite3: one table per entity, JSON column for the nested body, WAL so
reads do not block while a write is in flight.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import get_settings

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
    id         TEXT PRIMARY KEY,
    body       TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _resolve_path(database_url: str) -> Path:
    prefix = "sqlite:///"
    if database_url.startswith(prefix):
        raw = database_url[len(prefix) :]
    elif database_url == ":memory:":
        raw = ":memory:"
    else:
        raw = database_url
    return Path(raw)


def _connect() -> sqlite3.Connection:
    settings = get_settings()
    path = _resolve_path(settings.database_url)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def get_profile(profile_id: str = "default") -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT body FROM profile WHERE id = ?", (profile_id,)).fetchone()
    return json.loads(row["body"]) if row else None


def put_profile(body: dict[str, Any], profile_id: str = "default") -> dict[str, Any]:
    """Full replace of the single profile row.

    Keyed on ``profile_id``, never on ``body["id"]``: Profile auto-generates an
    id, so trusting it would scatter rows across random keys and GET /profile
    would 404.
    """
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO profile (id, body) VALUES (?, ?)
               ON CONFLICT(id) DO UPDATE SET body = excluded.body,
                                             updated_at = datetime('now')""",
            (profile_id, json.dumps(body)),
        )
    return body
