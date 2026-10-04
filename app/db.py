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

-- Stage 2 needs one place to store a rendered-snapshot document so that
-- POST /export/{version_id} has something to export. Tailoring and the
-- JD/application links are Stage 6/8 and deliberately not here.
--
-- `template` became a column in Stage 5b. It is index data, not resume content:
-- without it, GET /versions would have to read the whole profile snapshot of
-- every row just to print one word in a listbox -- and it would have had to
-- either guess "blank" for everything or skip the field. Both are worse than
-- storing it.
CREATE TABLE IF NOT EXISTS versions (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    jd_id      TEXT,
    template   TEXT NOT NULL DEFAULT 'blank',
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
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
        _add_column_if_missing(conn, "versions", "template",
                               "TEXT NOT NULL DEFAULT 'blank'")


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, decl: str
) -> None:
    """Add a column to a table that already exists.

    `CREATE TABLE IF NOT EXISTS` does nothing for a database created before the
    column was introduced, so a developer with an existing resume.db would get an
    OperationalError on the first write rather than a working app. Cheap to do
    properly, and SQLite has no other way to add a NOT NULL column to a table
    with rows -- it has to be a constant default.

    Reads PRAGMA output by position rather than by name: the pragma's columns are
    fixed and documented as (cid, name, type, notnull, dflt_value, pk), so this
    works on a connection with any row_factory, not just the one `get_conn()`
    happens to set.
    """
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


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


def get_version(version_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT body FROM versions WHERE id = ?", (version_id,)).fetchone()
    return json.loads(row["body"]) if row else None


def list_versions(limit: int = 100) -> list[dict[str, Any]]:
    """Every stored version, newest first.

    The columns are selected explicitly rather than `SELECT *` because the
    `body` column holds the whole profile snapshot -- a resume. A version list
    only needs the index fields, and reading personal details to decide which
    rows to show is not a reason to touch them.

    The tie-break is the reason this function exists in this shape.
    `created_at` is a plain ISO *date*, at day resolution, so every snapshot
    taken in one afternoon shares a value. Ordering by `created_at DESC, id DESC`
    looked right and was not: ids are random hex, so same-day versions came back
    in an arbitrary order that changed with the data rather than with the time.
    `rowid` is SQLite's implicit insertion counter and it is monotonic, so
    `rowid DESC` is genuine latest-first within a day.
    """
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, name, jd_id, template, created_at FROM versions
               ORDER BY created_at DESC, rowid DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_version(version_id: str) -> bool:
    """Remove one version. Returns whether anything was there to remove."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM versions WHERE id = ?", (version_id,))
        return cur.rowcount > 0


def put_version(body: dict[str, Any]) -> dict[str, Any]:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO versions (id, name, jd_id, template, body, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET name    = excluded.name,
                                             jd_id   = excluded.jd_id,
                                             template = excluded.template,
                                             body    = excluded.body,
                                             created_at = excluded.created_at""",
            (
                body["id"],
                body["name"],
                body.get("jd_id"),
                body.get("template", "blank"),
                json.dumps(body),
                body.get("created_at", ""),
            ),
        )
    return body
