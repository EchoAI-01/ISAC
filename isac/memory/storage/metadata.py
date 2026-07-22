"""MetadataStore: SQLite + FTS5 元数据存储 (ARCHITECTURE.md 3.6)。

所有表带 agent_id 命名空间 (SPECIFICATION.md 1.6/2.4)。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import aiosqlite

from isac.utils.logger import get_logger

logger = get_logger(__name__)

# ARCHITECTURE.md 3.6 存储层 Schema (含 agent_id 命名空间)
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT,
    topics TEXT,
    participants TEXT,
    emotion TEXT,
    importance REAL DEFAULT 0.5,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_episodes_agent ON episodes(agent_id);
CREATE INDEX IF NOT EXISTS idx_episodes_user ON episodes(user_id);
CREATE INDEX IF NOT EXISTS idx_episodes_time ON episodes(created_at);

CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
    content, summary, topics, participants,
    content=episodes, content_rowid=rowid
);

CREATE TABLE IF NOT EXISTS person_profiles (
    agent_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    name TEXT NOT NULL,
    profile_text TEXT,
    traits TEXT,
    relationship_depth REAL DEFAULT 0.0,
    interaction_count INTEGER DEFAULT 0,
    first_seen INTEGER,
    last_seen INTEGER,
    embedding_hash TEXT,
    PRIMARY KEY (agent_id, person_id)
);

CREATE TABLE IF NOT EXISTS jargon_entries (
    agent_id TEXT NOT NULL,
    word TEXT NOT NULL,
    meaning TEXT NOT NULL,
    context TEXT,
    usage_count INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (agent_id, word)
);
"""


class MetadataStore:
    """SQLite 元数据存储。"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init_schema(self) -> None:
        """初始化 Schema。"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA_SQL)
            await db.commit()

    async def store_episode(self, agent_id: str, episode: dict) -> str:
        """写入 episode，并同步 FTS。"""
        memory_id = str(episode.get("id") or uuid.uuid4())
        now = int(time.time())
        summary = str(episode.get("summary", "") or "")
        topics = self._json_text(episode.get("topics", []))
        participants = self._json_text(episode.get("participants", []))
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO episodes (
                    id, agent_id, session_id, user_id, content, summary, topics, participants,
                    emotion, importance, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    agent_id,
                    str(episode.get("session_id", "")),
                    str(episode.get("user_id", "")),
                    str(episode.get("content", "")),
                    summary,
                    topics,
                    participants,
                    str(episode.get("emotion", "") or ""),
                    float(episode.get("importance", 0.5) or 0.5),
                    int(episode.get("created_at", now) or now),
                    int(episode.get("updated_at", now) or now),
                ),
            )
            await self._rebuild_fts_row(db, memory_id)
            await db.commit()
        return memory_id

    async def search_fts(self, agent_id: str, query: str, limit: int = 10) -> list[dict]:
        """按 agent_id 隔离执行 FTS5 搜索。"""
        clean_query = " ".join(str(query or "").split())
        if not clean_query:
            return []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                """
                SELECT episodes.*, bm25(episodes_fts) AS score
                FROM episodes_fts
                JOIN episodes ON episodes_fts.rowid = episodes.rowid
                WHERE episodes_fts MATCH ? AND episodes.agent_id = ?
                ORDER BY score ASC, episodes.created_at DESC
                LIMIT ?
                """,
                (self._fts_query(clean_query), agent_id, max(1, int(limit))),
            )
        return [self._episode_row_to_dict(row) for row in rows]

    async def get_episodes_by_ids(self, agent_id: str, memory_ids: list[str]) -> list[dict]:
        """按 ID 批量读取 episode，保持输入 ID 顺序。"""
        ordered_ids = [memory_id for memory_id in memory_ids if memory_id]
        if not ordered_ids:
            return []
        placeholders = ",".join("?" for _ in ordered_ids)
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                f"SELECT * FROM episodes WHERE agent_id = ? AND id IN ({placeholders})",
                (agent_id, *ordered_ids),
            )
        rows_by_id = {str(row["id"]): self._episode_row_to_dict(row) for row in rows}
        return [rows_by_id[memory_id] for memory_id in ordered_ids if memory_id in rows_by_id]

    async def get_person_profile(self, agent_id: str, person_id: str) -> dict | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM person_profiles WHERE agent_id = ? AND person_id = ?",
                (agent_id, person_id),
            )
            row = await cursor.fetchone()
        return None if row is None else self._profile_row_to_dict(row)

    async def upsert_person_profile(self, agent_id: str, profile: dict) -> None:
        person_id = str(profile.get("person_id", "")).strip()
        if not person_id:
            raise ValueError("person profile 缺少 person_id")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO person_profiles (
                    agent_id, person_id, name, profile_text, traits, relationship_depth,
                    interaction_count, first_seen, last_seen, embedding_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_id,
                    person_id,
                    str(profile.get("name", person_id)),
                    str(profile.get("profile_text", "") or ""),
                    self._json_text(profile.get("traits", [])),
                    float(profile.get("relationship_depth", 0.0) or 0.0),
                    int(profile.get("interaction_count", 0) or 0),
                    profile.get("first_seen"),
                    profile.get("last_seen"),
                    profile.get("embedding_hash"),
                ),
            )
            await db.commit()

    async def upsert_jargon(self, agent_id: str, word: str, meaning: str, context: str = "") -> None:
        clean_word = str(word or "").strip()
        if not clean_word:
            raise ValueError("行话 word 不能为空")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO jargon_entries (agent_id, word, meaning, context, usage_count, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(agent_id, word) DO UPDATE SET
                    meaning = excluded.meaning,
                    context = excluded.context,
                    usage_count = jargon_entries.usage_count + 1
                """,
                (agent_id, clean_word, str(meaning), str(context or ""), int(time.time())),
            )
            await db.commit()

    async def list_jargon(self, agent_id: str) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(
                """
                SELECT word, meaning, context, usage_count
                FROM jargon_entries
                WHERE agent_id = ?
                ORDER BY usage_count DESC, word ASC
                """,
                (agent_id,),
            )
        return [dict(row) for row in rows]

    @staticmethod
    def _json_text(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _json_loads(value: str | None, default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default

    @staticmethod
    def _fts_query(query: str) -> str:
        terms = [term.replace('"', "") for term in query.split() if term.strip()]
        return " OR ".join(f'"{term}"' for term in terms) or '""'

    async def _rebuild_fts_row(self, db: aiosqlite.Connection, memory_id: str) -> None:
        del memory_id
        await db.execute("INSERT INTO episodes_fts(episodes_fts) VALUES ('rebuild')")

    def _episode_row_to_dict(self, row: aiosqlite.Row) -> dict:
        data = dict(row)
        data["topics"] = self._json_loads(data.get("topics"), [])
        data["participants"] = self._json_loads(data.get("participants"), [])
        data["score"] = abs(float(data.get("score", 0.0) or 0.0))
        return data

    def _profile_row_to_dict(self, row: aiosqlite.Row) -> dict:
        data = dict(row)
        data["traits"] = self._json_loads(data.get("traits"), [])
        return data
