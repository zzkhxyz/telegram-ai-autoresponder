"""
SQLite manager — stores per-user chat history and session counters.

Schema
------
messages  — chat history (user_id, role, content, timestamp)
sessions  — reply counter per user (user_id, count, paused_until)
"""

import time
import aiosqlite
from config import DB_PATH


_CREATE_MESSAGES = """
CREATE TABLE IF NOT EXISTS messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL,
    role      TEXT    NOT NULL CHECK(role IN ('user', 'assistant')),
    content   TEXT    NOT NULL,
    ts        REAL    NOT NULL DEFAULT (unixepoch('now'))
);
"""

_CREATE_SESSIONS = """
CREATE TABLE IF NOT EXISTS sessions (
    user_id      INTEGER PRIMARY KEY,
    reply_count  INTEGER NOT NULL DEFAULT 0,
    paused_until REAL    NOT NULL DEFAULT 0
);
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(_CREATE_MESSAGES)
        await db.execute(_CREATE_SESSIONS)
        await db.commit()


async def add_message(user_id: int, role: str, content: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content),
        )
        await db.commit()


async def get_recent_messages(user_id: int, limit: int) -> list[dict]:
    """Return the last `limit` messages for user_id, oldest first."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT role, content FROM (
                SELECT role, content, ts
                FROM messages
                WHERE user_id = ?
                ORDER BY ts DESC
                LIMIT ?
            ) ORDER BY ts ASC
            """,
            (user_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


# ---------------------------------------------------------------------------
# Session / rate-limit helpers
# ---------------------------------------------------------------------------

async def get_reply_count(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT reply_count FROM sessions WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row else 0


async def increment_reply_count(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO sessions (user_id, reply_count) VALUES (?, 1)
            ON CONFLICT(user_id) DO UPDATE SET reply_count = reply_count + 1
            """,
            (user_id,),
        )
        await db.commit()
        async with db.execute(
            "SELECT reply_count FROM sessions WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
    return row[0]


async def is_paused(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT paused_until FROM sessions WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
    if not row:
        return False
    return time.time() < row[0]


async def pause_user(user_id: int, seconds: int = 3600) -> None:
    """Silence the bot for this user for `seconds` (default 1 hour)."""
    until = time.time() + seconds
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO sessions (user_id, paused_until) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET paused_until = ?
            """,
            (user_id, until, until),
        )
        await db.commit()
