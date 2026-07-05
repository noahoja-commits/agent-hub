"""
SQLite persistence layer for Agent Hub.
Replaces the in-memory _tasks dict with async SQLite storage.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import aiosqlite

logger = logging.getLogger("agent-hub.db")

DB_PATH = os.environ.get("AGENT_HUB_DB", "agent_hub.db")

_db: aiosqlite.Connection | None = None
_db_lock = asyncio.Lock()


async def get_db() -> aiosqlite.Connection:
    """Get or create the database connection."""
    global _db
    if _db is not None:
        return _db
    async with _db_lock:
        if _db is not None:
            return _db
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
        await _migrate(_db)
        logger.info("SQLite database ready at %s", DB_PATH)
        return _db


async def _migrate(db: aiosqlite.Connection) -> None:
    """Create tables if they don't exist."""
    await db.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            agent TEXT NOT NULL,
            action TEXT NOT NULL,
            params TEXT DEFAULT '{}',
            status TEXT DEFAULT 'queued',
            result TEXT,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)
    """)
    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(agent)
    """)
    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC)
    """)
    await db.commit()


async def close_db() -> None:
    """Close the database connection."""
    global _db
    if _db:
        await _db.close()
        _db = None


# ---------------------------------------------------------------------------
# Task CRUD
# ---------------------------------------------------------------------------

async def create_task(agent: str, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a new task and return it as a dict."""
    db = await get_db()
    task_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    params_json = json.dumps(params or {})

    await db.execute(
        "INSERT INTO tasks (id, agent, action, params, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'queued', ?, ?)",
        (task_id, agent, action, params_json, now, now),
    )
    await db.commit()

    return {
        "id": task_id, "agent": agent, "action": action,
        "params": params or {}, "status": "queued",
        "result": None, "error": None,
        "created_at": now, "updated_at": now,
    }


async def get_task(task_id: str) -> dict[str, Any] | None:
    """Get a single task by ID."""
    db = await get_db()
    cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = await cursor.fetchone()
    if not row:
        return None
    return _row_to_dict(row)


async def list_tasks(agent: str | None = None, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """List tasks with optional filters."""
    db = await get_db()
    query = "SELECT * FROM tasks WHERE 1=1"
    params: list[Any] = []

    if agent:
        query += " AND agent = ?"
        params.append(agent)
    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [_row_to_dict(r) for r in rows]


async def update_task(task_id: str, **fields: Any) -> dict[str, Any] | None:
    """Update task fields. Returns the updated task or None if not found."""
    db = await get_db()

    existing = await get_task(task_id)
    if not existing:
        return None

    # Build SET clause
    set_clauses = []
    values: list[Any] = []

    for key, value in fields.items():
        if key in ("id", "created_at"):
            continue
        if key in ("result", "params") and value is not None:
            value = json.dumps(value) if not isinstance(value, str) else value
        set_clauses.append(f"{key} = ?")
        values.append(value)

    set_clauses.append("updated_at = ?")
    values.append(datetime.now(timezone.utc).isoformat())
    values.append(task_id)

    await db.execute(
        f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = ?",
        values,
    )
    await db.commit()

    return await get_task(task_id)


async def get_task_count(status: str | None = None) -> int:
    """Count tasks, optionally filtered by status."""
    db = await get_db()
    if status:
        cursor = await db.execute("SELECT COUNT(*) FROM tasks WHERE status = ?", (status,))
    else:
        cursor = await db.execute("SELECT COUNT(*) FROM tasks")
    row = await cursor.fetchone()
    return row[0] if row else 0


async def cleanup_old_tasks(days: int = 30) -> int:
    """Delete completed/failed tasks older than N days. Returns count deleted."""
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM tasks WHERE status IN ('completed', 'failed') AND created_at < datetime('now', ?)",
        (f"-{days} days",),
    )
    await db.commit()
    return cursor.rowcount


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert a database row to a dict with proper types."""
    d = dict(row)
    # Parse JSON fields
    for field in ("params", "result"):
        if d.get(field) and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return d
