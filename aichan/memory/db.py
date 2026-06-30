"""SQLite スキーマと低レベルCRUD(docs/specification.md §8.2)。"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import DATA_DIR

DB_PATH = DATA_DIR / "aichan.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS persona (
  character_id TEXT PRIMARY KEY,
  content TEXT NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS user_profile (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  role TEXT NOT NULL,          -- user | assistant
  source TEXT NOT NULL,        -- text|voice|screen|proactive|discord
  text TEXT NOT NULL,
  emotion TEXT,
  meta TEXT,                   -- JSON
  summarized INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS memory_summaries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  level INTEGER NOT NULL DEFAULT 0,   -- 0=会話塊, 1=日次, 2=週次...
  period_start REAL,
  period_end REAL,
  topic TEXT,
  summary TEXT NOT NULL,
  salience REAL NOT NULL DEFAULT 0.5,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts);
CREATE INDEX IF NOT EXISTS idx_summaries_level ON memory_summaries(level);
"""


@dataclass
class MessageRow:
    id: int
    ts: float
    role: str
    source: str
    text: str
    emotion: str | None
    meta: dict


class MemoryDB:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # orchestrator/scheduler 等 複数スレッドから使うため共有を許可しロックで直列化。
        # timeout: 一時的なロック待ち(ネットワークFS対策の保険)。
        self.conn = sqlite3.connect(
            str(self.path), check_same_thread=False, timeout=10.0
        )
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # ---- persona ------------------------------------------------------
    def get_persona(self, character_id: str) -> str | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT content FROM persona WHERE character_id=?", (character_id,)
            ).fetchone()
        return row["content"] if row else None

    def set_persona(self, character_id: str, content: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO persona(character_id, content, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(character_id) DO UPDATE SET content=excluded.content, "
                "updated_at=excluded.updated_at",
                (character_id, content, time.time()),
            )
            self.conn.commit()

    # ---- user profile -------------------------------------------------
    def get_profile(self) -> dict[str, str]:
        with self._lock:
            rows = self.conn.execute("SELECT key, value FROM user_profile").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def set_profile(self, key: str, value: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO user_profile(key, value, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at",
                (key, value, time.time()),
            )
            self.conn.commit()

    # ---- messages -----------------------------------------------------
    def add_message(
        self, role: str, text: str, source: str = "text",
        emotion: str | None = None, meta: dict | None = None,
    ) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO messages(ts, role, source, text, emotion, meta) "
                "VALUES(?,?,?,?,?,?)",
                (time.time(), role, source, text, emotion,
                 json.dumps(meta or {}, ensure_ascii=False)),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def recent_messages(self, limit: int) -> list[MessageRow]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_msg(r) for r in reversed(rows)]

    def unsummarized_messages(self, before_recent: int) -> list[MessageRow]:
        """直近 before_recent 件を除く、未要約メッセージ(古い順)。"""
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM messages WHERE summarized=0 AND id NOT IN "
                "(SELECT id FROM messages ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
                (before_recent,),
            ).fetchall()
        return [_row_to_msg(r) for r in rows]

    def mark_summarized(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            self.conn.executemany(
                "UPDATE messages SET summarized=1 WHERE id=?", [(i,) for i in ids]
            )
            self.conn.commit()

    def message_count(self) -> int:
        with self._lock:
            return int(
                self.conn.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"]
            )

    # ---- summaries ----------------------------------------------------
    def add_summary(
        self, summary: str, *, level: int = 0, topic: str = "",
        period_start: float | None = None, period_end: float | None = None,
        salience: float = 0.5,
    ) -> int:
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO memory_summaries(level, period_start, period_end, topic, "
                "summary, salience, updated_at) VALUES(?,?,?,?,?,?,?)",
                (level, period_start, period_end, topic, summary, salience, time.time()),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def summaries(self, level: int | None = None, limit: int = 50) -> list[sqlite3.Row]:
        with self._lock:
            if level is None:
                return self.conn.execute(
                    "SELECT * FROM memory_summaries ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
            return self.conn.execute(
                "SELECT * FROM memory_summaries WHERE level=? ORDER BY id DESC LIMIT ?",
                (level, limit),
            ).fetchall()

    def delete_summaries(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            self.conn.executemany(
                "DELETE FROM memory_summaries WHERE id=?", [(i,) for i in ids]
            )
            self.conn.commit()


def _row_to_msg(r: sqlite3.Row) -> MessageRow:
    try:
        meta = json.loads(r["meta"]) if r["meta"] else {}
    except (json.JSONDecodeError, TypeError):
        meta = {}
    return MessageRow(
        id=r["id"], ts=r["ts"], role=r["role"], source=r["source"],
        text=r["text"], emotion=r["emotion"], meta=meta,
    )
