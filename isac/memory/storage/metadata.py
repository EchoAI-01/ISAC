"""MetadataStore: SQLite + FTS5 元数据存储 (ARCHITECTURE.md 3.6)。

所有表带 agent_id 命名空间 (SPECIFICATION.md 1.6/2.4)。
"""

from __future__ import annotations

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
    """SQLite 元数据存储。

    TODO(Day 18): aiosqlite 连接管理 + init_schema + CRUD (全表按 agent_id 过滤)。
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init_schema(self) -> None:
        """初始化 Schema (SCHEMA_SQL)。"""
        raise NotImplementedError("TODO(Day 18): 执行 SCHEMA_SQL 初始化")

    async def store_episode(self, agent_id: str, episode: dict) -> str:
        raise NotImplementedError("TODO(Day 18): 写入 episode + FTS 同步")

    async def search_fts(self, agent_id: str, query: str, limit: int = 10) -> list[dict]:
        raise NotImplementedError("TODO(Day 18): FTS5 全文搜索")

    async def get_person_profile(self, agent_id: str, person_id: str) -> dict | None:
        raise NotImplementedError("TODO(Day 18): 查询人物画像")

    async def upsert_person_profile(self, agent_id: str, profile: dict) -> None:
        raise NotImplementedError("TODO(Day 18): 更新人物画像")

    async def upsert_jargon(self, agent_id: str, word: str, meaning: str, context: str = "") -> None:
        raise NotImplementedError("TODO(Day 18): 更新行话")
