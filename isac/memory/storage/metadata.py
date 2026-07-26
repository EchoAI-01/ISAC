"""MetadataStore: SQLite + FTS5 元数据存储 (ARCHITECTURE.md 3.6)。

所有表带 agent_id 命名空间 (SPECIFICATION.md 1.6/2.4)。

CR3-L2 (O1/P5): 可选注入 TenantIsolationGuard + TenantContext —— 写入时给
episodes 行打 organization_id/tenant_id 标, 读查询用 guard.enforce() 子查询
包裹加租户谓词。未注入 (默认) 或 guard.enabled=False 时零行为变化 (单租户
passthrough); 注入按运行时实例进行, 不 import runtime 层 (DEVELOP.md 1.2)。
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

# 与 isac.runtime.tenancy.models.DEFAULT_ORG/DEFAULT_TENANT 对齐的字面量
# (不能 import runtime 层, 见 DEVELOP.md 导入顺序)。
_DEFAULT_TENANT_VALUE = "default"

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
-- group_id 列由 init_schema() 按需 ALTER TABLE 补齐 (老库无此列, SQLite ALTER TABLE
-- ADD COLUMN 没有 IF NOT EXISTS 语法, 需先探测再执行, 见 _ensure_column)。

CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
    content, summary, topics, participants,
    content=episodes, content_rowid=rowid
);

-- external content FTS5 表标准同步模式: episodes 增/删/改时增量维护 episodes_fts,
-- 取代写入路径上的全量 rebuild (CODE_REVIEW_REPORT.md #12)。
-- INSERT OR REPLACE 命中 PRIMARY KEY 冲突时会先触发 DELETE 再触发 INSERT (新行拿到
-- 新 rowid); 但 SQLite 默认关闭 recursive_triggers, REPLACE 隐式删除旧行时不会
-- 激活 DELETE 触发器, 必须在连接上 PRAGMA recursive_triggers = ON 才会触发
-- (见 store_episode(), 这是本改动里最容易踩的坑)。保留 AFTER UPDATE 触发器是为了
-- 真正执行 SQL UPDATE 语句的场景 (防御性覆盖, 当前代码未使用)。
CREATE TRIGGER IF NOT EXISTS episodes_fts_ai AFTER INSERT ON episodes BEGIN
    INSERT INTO episodes_fts(rowid, content, summary, topics, participants)
    VALUES (new.rowid, new.content, new.summary, new.topics, new.participants);
END;
CREATE TRIGGER IF NOT EXISTS episodes_fts_ad AFTER DELETE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, content, summary, topics, participants)
    VALUES ('delete', old.rowid, old.content, old.summary, old.topics, old.participants);
END;
CREATE TRIGGER IF NOT EXISTS episodes_fts_au AFTER UPDATE ON episodes BEGIN
    INSERT INTO episodes_fts(episodes_fts, rowid, content, summary, topics, participants)
    VALUES ('delete', old.rowid, old.content, old.summary, old.topics, old.participants);
    INSERT INTO episodes_fts(rowid, content, summary, topics, participants)
    VALUES (new.rowid, new.content, new.summary, new.topics, new.participants);
END;

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

-- N2 记忆治理 (MEMORY_DESIGN.md §7): episodes 软删除/冻结/保护/纠正历史。
-- frozen=1: 冻结 (不再自动更新); protected=1: 保护 (不被自动清理/覆盖);
-- deleted=1: 软删除 (审计保留); corrected_by: 指向最近一次纠正的 revision_id。
CREATE TABLE IF NOT EXISTS memory_revisions (
    revision_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    old_content TEXT,
    new_content TEXT,
    corrected_at INTEGER NOT NULL,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_revisions_item ON memory_revisions(item_id);
CREATE TABLE IF NOT EXISTS memory_audit (
    audit_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL,
    action TEXT NOT NULL,  -- freeze/protect/correct/delete/restore
    operator TEXT,          -- 操作者标识 (控制面 token 指纹 / 调用方名); CR3-L5 起真实写入
    agent_id TEXT,          -- 被操作条目所属 Agent (CR3-L5; 老库由 _ensure_column 补齐)
    occurred_at INTEGER NOT NULL,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_item ON memory_audit(item_id);
"""


class MetadataStore:
    """SQLite 元数据存储。"""

    def __init__(self, db_path: str, *, tenant_guard: Any = None, tenant_context: Any = None):
        """
        Args:
            db_path: SQLite 文件路径
            tenant_guard: 可选 TenantIsolationGuard (CR3-L2; 鸭子类型, 需有
                enforce(query, params, tenant) 方法)。None = 单租户 passthrough。
            tenant_context: 可选 TenantContext (organization_id/tenant_id)。
        """
        self.db_path = db_path
        self._tenant_guard = tenant_guard
        self._tenant_context = tenant_context

    def _tenant_scope(self, query: str, params: list) -> tuple[str, list]:
        """给读查询加租户谓词 (CR3-L2); 未注入 guard/context 时原样返回。"""
        if self._tenant_guard is None or self._tenant_context is None:
            return query, list(params)
        return self._tenant_guard.enforce(query, list(params), self._tenant_context)

    def _tenant_row_values(self) -> tuple[str, str]:
        """写入行的 (organization_id, tenant_id) 标记值。"""
        if self._tenant_context is None:
            return (_DEFAULT_TENANT_VALUE, _DEFAULT_TENANT_VALUE)
        return (
            str(getattr(self._tenant_context, "organization_id", _DEFAULT_TENANT_VALUE)),
            str(getattr(self._tenant_context, "tenant_id", _DEFAULT_TENANT_VALUE)),
        )

    async def init_schema(self) -> None:
        """初始化 Schema。"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA_SQL)
            await self._ensure_column(db, "episodes", "group_id", "TEXT")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_episodes_group ON episodes(group_id)")
            # N2: episodes 治理列 (向后兼容老库, 默认 0/NULL)
            await self._ensure_column(db, "episodes", "frozen", "INTEGER DEFAULT 0")
            await self._ensure_column(db, "episodes", "protected", "INTEGER DEFAULT 0")
            await self._ensure_column(db, "episodes", "deleted", "INTEGER DEFAULT 0")
            await self._ensure_column(db, "episodes", "corrected_by", "TEXT")
            # CR3-L5: memory_audit 补 agent_id 列 (老库迁移; 新库建表语句已含)
            await self._ensure_column(db, "memory_audit", "agent_id", "TEXT")
            # CR3-L2 (O1): episodes 租户列 (老库/新库统一走 _ensure_column 迁移,
            # 默认 'default' = 单租户退化态; 常量默认值可用于 ADD COLUMN)
            await self._ensure_column(db, "episodes", "organization_id", "TEXT DEFAULT 'default'")
            await self._ensure_column(db, "episodes", "tenant_id", "TEXT DEFAULT 'default'")
            await db.commit()

    @staticmethod
    async def _ensure_column(db: aiosqlite.Connection, table: str, column: str, decl_type: str) -> None:
        """SQLite 的 ALTER TABLE ADD COLUMN 没有 IF NOT EXISTS, 需先探测再决定是否执行。

        table/column/decl_type 均为调用方硬编码的 schema 常量, 非用户输入, 拼接安全。
        """
        cursor = await db.execute(f"PRAGMA table_info({table})")
        existing_columns = {row[1] for row in await cursor.fetchall()}
        if column not in existing_columns:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl_type}")

    async def store_episode(self, agent_id: str, episode: dict) -> str:
        """写入 episode，并同步 FTS。"""
        memory_id = str(episode.get("id") or uuid.uuid4())
        now = int(time.time())
        summary = str(episode.get("summary", "") or "")
        topics = self._json_text(episode.get("topics", []))
        participants = self._json_text(episode.get("participants", []))
        group_id = str(episode.get("group_id") or "") or None  # 空字符串规范化为 NULL (= 私聊)
        async with aiosqlite.connect(self.db_path) as db:
            # SQLite 默认关闭 recursive_triggers: INSERT OR REPLACE 命中 PRIMARY KEY
            # 冲突时隐式删除旧行, 若不开启这个 PRAGMA, 该隐式删除不会激活 AFTER DELETE
            # 触发器, episodes_fts 倒排索引会残留旧 rowid 的词项 (MATCH 旧内容仍命中;
            # search_fts() 因为额外 JOIN episodes 才没有把这些孤儿行暴露出来)。
            await db.execute("PRAGMA recursive_triggers = ON")
            # CR3-L2: organization_id/tenant_id 必须在 INSERT OR REPLACE 的列清单里
            # —— 覆盖写入时缺列会把已有行的租户标重置为默认值。
            organization_id, tenant_id = self._tenant_row_values()
            await db.execute(
                """
                INSERT OR REPLACE INTO episodes (
                    id, agent_id, session_id, user_id, group_id, content, summary, topics,
                    participants, emotion, importance, created_at, updated_at,
                    organization_id, tenant_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory_id,
                    agent_id,
                    str(episode.get("session_id", "")),
                    str(episode.get("user_id", "")),
                    group_id,
                    str(episode.get("content", "")),
                    summary,
                    topics,
                    participants,
                    str(episode.get("emotion", "") or ""),
                    float(episode.get("importance", 0.5) or 0.5),
                    int(episode.get("created_at", now) or now),
                    int(episode.get("updated_at", now) or now),
                    organization_id,
                    tenant_id,
                ),
            )
            # episodes_fts 由 episodes_fts_ai/ad/au 触发器增量同步, 此处不再需要
            # 手动全量 rebuild (见 rebuild_fts_index() 的运维用途说明)。
            await db.commit()
        return memory_id

    async def search_fts(
        self,
        agent_id: str,
        query: str,
        limit: int = 10,
        user_id: str = "",
        group_id: str = "",
    ) -> list[dict]:
        """按 agent_id 隔离执行 FTS5 搜索, 并按 user_id/group_id 做访问控制。

        user_id/group_id 均为空时不过滤 (向后兼容); group_id 非空时按群聊场景过滤
        (群内共享); group_id 为空但 user_id 非空时按私聊场景过滤 (仅自己的私聊记忆,
        不含该用户在群聊中的发言)。
        """
        clean_query = " ".join(str(query or "").split())
        if not clean_query:
            return []
        conditions = ["episodes_fts MATCH ?", "episodes.agent_id = ?", "episodes.deleted = 0"]
        params: list[Any] = [self._fts_query(clean_query), agent_id]
        if group_id:
            conditions.append("episodes.group_id = ?")
            params.append(group_id)
        elif user_id:
            conditions.append("episodes.user_id = ? AND episodes.group_id IS NULL")
            params.append(user_id)
        where_clause = " AND ".join(conditions)
        query = f"""
            SELECT episodes.*, bm25(episodes_fts) AS score
            FROM episodes_fts
            JOIN episodes ON episodes_fts.rowid = episodes.rowid
            WHERE {where_clause}
            ORDER BY score ASC, episodes.created_at DESC
            LIMIT ?
        """
        # CR3-L2: 租户谓词用子查询包裹 (enforce), 内层 episodes.* 投影已含租户列
        query, scoped_params = self._tenant_scope(query, [*params, max(1, int(limit))])
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(query, scoped_params)
        return [self._episode_row_to_dict(row) for row in rows]

    async def get_episodes_by_ids(
        self,
        agent_id: str,
        memory_ids: list[str],
        user_id: str = "",
        group_id: str = "",
    ) -> list[dict]:
        """按 ID 批量读取 episode，保持输入 ID 顺序 (过滤语义同 search_fts)。"""
        ordered_ids = [memory_id for memory_id in memory_ids if memory_id]
        if not ordered_ids:
            return []
        placeholders = ",".join("?" for _ in ordered_ids)
        conditions = ["agent_id = ?", f"id IN ({placeholders})", "deleted = 0"]
        params: list[Any] = [agent_id, *ordered_ids]
        if group_id:
            conditions.append("group_id = ?")
            params.append(group_id)
        elif user_id:
            conditions.append("user_id = ? AND group_id IS NULL")
            params.append(user_id)
        where_clause = " AND ".join(conditions)
        query, scoped_params = self._tenant_scope(f"SELECT * FROM episodes WHERE {where_clause}", params)
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(query, scoped_params)
        rows_by_id = {str(row["id"]): self._episode_row_to_dict(row) for row in rows}
        return [rows_by_id[memory_id] for memory_id in ordered_ids if memory_id in rows_by_id]

    async def iter_episodes_by_namespace(self, agent_id: str) -> list[tuple[str, str]]:
        """按 agent_id 列出全部 (memory_id, content) 供 SparseBM25Index 重启恢复。

        SparseBM25Index 是内存数据结构, 进程重启后会丢失倒排索引; 启动时从 SQLite
        episodes 表加载现有记忆重建索引, 让 BM25 检索在重启后立即可用
        (K3, DEVELOPMENT_PLAN.md)。

        CR3-L3: 排除软删除行 (deleted=1)。此前预热把墓碑也灌进 BM25 内存索引,
        抬高 total_docs/平均长度, 污染存活项的 IDF 与长度归一。
        CR3-L2: 投影带上租户列并经 _tenant_scope 过滤 (enforce 的外层谓词需要
        内层投影出 organization_id/tenant_id; 返回值仍只取前两列)。
        """
        query, scoped_params = self._tenant_scope(
            "SELECT id, content, organization_id, tenant_id FROM episodes "
            "WHERE agent_id = ? AND content != '' AND deleted = 0",
            [agent_id],
        )
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(query, scoped_params)
            rows = await cursor.fetchall()
        return [(str(row[0]), str(row[1])) for row in rows]

    async def delete_namespace(self, agent_id: str) -> int:
        """Q0: 硬删除某命名空间的全部记忆数据 (episodes/person_profiles/jargon_entries)。

        供 ``AgentManager.destroy(keep_memory=False)`` 调用。episodes 的 AFTER
        DELETE 触发器同步清理 episodes_fts 倒排索引 (显式 DELETE 语句总会触发,
        无需 recursive_triggers)。agent_id 为多租户场景下已含前缀的完整命名空间,
        天然租户隔离。返回删除的 episodes 行数。
        """
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM episodes WHERE agent_id = ?", (agent_id,))
            removed = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
            await db.execute("DELETE FROM person_profiles WHERE agent_id = ?", (agent_id,))
            await db.execute("DELETE FROM jargon_entries WHERE agent_id = ?", (agent_id,))
            await db.commit()
        logger.info("记忆命名空间已清空", agent_id=agent_id, episodes_removed=removed)
        return removed

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

    async def rebuild_fts_index(self) -> None:
        """全量重建 episodes_fts 索引。

        运维用途: 修复因触发器缺失/异常导致的索引不一致。写入路径 (store_episode)
        依赖 episodes_fts_ai/ad/au 触发器增量同步, 不应该也不会调用这个全量方法。
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("INSERT INTO episodes_fts(episodes_fts) VALUES ('rebuild')")
            await db.commit()

    def _episode_row_to_dict(self, row: aiosqlite.Row) -> dict:
        data = dict(row)
        data["topics"] = self._json_loads(data.get("topics"), [])
        data["participants"] = self._json_loads(data.get("participants"), [])
        # SQLite FTS5 bm25() 返回负值, 越负越相关 (ORDER BY score ASC 已让最相关在前)。
        # 保留原值而非 abs(), 让 score 字段与 FTS5 原生语义一致, 避免调用方按
        # "越大越相关"误解 (CODE_REVIEW_REPORT.md #21)。
        data["score"] = float(data.get("score", 0.0) or 0.0)
        return data

    def _profile_row_to_dict(self, row: aiosqlite.Row) -> dict:
        data = dict(row)
        data["traits"] = self._json_loads(data.get("traits"), [])
        return data
