"""MetadataStore: SQLite + FTS5 元数据存储 (ARCHITECTURE.md 3.6)。

所有表带 agent_id 命名空间 (SPECIFICATION.md 1.6/2.4)。

CR3-L2 (O1/P5): 可选注入 TenantIsolationGuard + TenantContext —— 写入时给
episodes 行打 organization_id/tenant_id 标, 读查询用 guard.enforce() 子查询
包裹加租户谓词。未注入 (默认) 或 guard.enabled=False 时零行为变化 (单租户
passthrough); 注入按运行时实例进行, 不 import runtime 层 (DEVELOP.md 1.2)。

U4: 租户机制强制 —— 租户读写原语统一经 TenantBoundDB (tenant_bound.py):
SELECT 走 scoped() (enforce 子查询), UPDATE/DELETE 走 predicate(), INSERT 走
row_values() 打标。五张记忆表 (episodes/person_profiles/jargon_entries/
memory_revisions/memory_audit) 全部带 organization_id/tenant_id 列。
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import aiosqlite

from isac.memory.storage.tenant_bound import TenantBoundDB
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
        # U4: 租户机制强制层 —— 读写原语 (scoped/predicate/row_values) 唯一入口。
        self._tenant_db = TenantBoundDB(
            db_path, tenant_guard=tenant_guard, tenant_context=tenant_context
        )

    def _tenant_scope(self, query: str, params: list) -> tuple[str, list]:
        """给读查询加租户谓词 (CR3-L2); U4 起委托 TenantBoundDB.scoped。"""
        return self._tenant_db.scoped(query, params)

    def _tenant_row_values(self) -> tuple[str, str]:
        """写入行的 (organization_id, tenant_id) 标记值 (U4 委托 TenantBoundDB)。"""
        return self._tenant_db.row_values()

    async def init_schema(self) -> None:
        """初始化 Schema。"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            # R6: WAL 模式让并发写不互斥 (一写多读), busy_timeout=5000ms 在
            # 偶发锁等待时让 SQLite 等待而非立即抛 SQLITE_BUSY。WAL 是数据库
            # 级别持久化属性, 一次设置后续连接继承; busy_timeout 是 connection
            # 级别, 每次 connect 都需要重设 (此处只设初始化连接)。
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute("PRAGMA foreign_keys=ON")
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
            # U4: 租户机制强制 —— person_profiles/jargon_entries/memory_revisions/
            # memory_audit 同样补租户列 (此前仅 episodes 有, 其余四表裸奔)。
            for table in ("person_profiles", "jargon_entries", "memory_revisions", "memory_audit"):
                await self._ensure_column(db, table, "organization_id", "TEXT DEFAULT 'default'")
                await self._ensure_column(db, table, "tenant_id", "TEXT DEFAULT 'default'")
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
        filters: dict | None = None,
    ) -> list[dict]:
        """按 agent_id 隔离执行 FTS5 搜索, 并按 user_id/group_id 做访问控制。

        user_id/group_id 均为空时不过滤 (向后兼容); group_id 非空时按群聊场景过滤
        (群内共享); group_id 为空但 user_id 非空时按私聊场景过滤 (仅自己的私聊记忆,
        不含该用户在群聊中的发言)。filters 为可选结构化过滤 (topics/时间范围, 见
        ``_build_filter_clause``), None 时向后兼容不加过滤。
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
        filter_clause, filter_params = self._build_filter_clause(filters)
        if filter_clause:
            conditions.append(filter_clause)
            params.extend(filter_params)
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
        filters: dict | None = None,
    ) -> list[dict]:
        """按 ID 批量读取 episode，保持输入 ID 顺序 (过滤语义同 search_fts)。

        filters 为可选结构化过滤 (topics/时间范围, 见 ``_build_filter_clause``),
        None 时向后兼容不加过滤。
        """
        ordered_ids = [memory_id for memory_id in memory_ids if memory_id]
        if not ordered_ids:
            return []
        # R9: SQLite 默认 SQLITE_MAX_VARIABLE_NUMBER=999, IN 子句占用的占位符
        # 数量若超限会报错。cap 到 500 (留余量给 agent_id/group_id/user_id 参数)
        # 避免极端 recall_limit * 3 场景溢出。下游 RRF 已 cap, 不影响召回完整性。
        if len(ordered_ids) > 500:
            ordered_ids = ordered_ids[:500]
        placeholders = ",".join("?" for _ in ordered_ids)
        conditions = ["agent_id = ?", f"id IN ({placeholders})", "deleted = 0"]
        params: list[Any] = [agent_id, *ordered_ids]
        if group_id:
            conditions.append("group_id = ?")
            params.append(group_id)
        elif user_id:
            conditions.append("user_id = ? AND group_id IS NULL")
            params.append(user_id)
        filter_clause, filter_params = self._build_filter_clause(filters)
        if filter_clause:
            conditions.append(filter_clause)
            params.extend(filter_params)
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
        无需 recursive_triggers)。agent_id 为多租户场景下已含前缀的完整命名空间;
        U4 起 DELETE 再叠加租户谓词双保险 (机制强制, 不依赖键口径自觉)。
        返回删除的 episodes 行数。
        """
        pred, tparams = self._tenant_db.predicate()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                f"DELETE FROM episodes WHERE agent_id = ?{pred}", (agent_id, *tparams)
            )
            removed = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
            await db.execute(
                f"DELETE FROM person_profiles WHERE agent_id = ?{pred}", (agent_id, *tparams)
            )
            await db.execute(
                f"DELETE FROM jargon_entries WHERE agent_id = ?{pred}", (agent_id, *tparams)
            )
            await db.commit()
        logger.info("记忆命名空间已清空", agent_id=agent_id, episodes_removed=removed)
        return removed

    async def get_episode_meta_by_ids(self, memory_ids: list[str]) -> list[dict]:
        """U4: 按 ID 批量读 episodes 元数据列 (供 consolidator 替代裸 SQL)。

        经租户作用域 (内层投影含租户列), IN 子句分块 (每批 ≤500, Fix-67:
        SQLite 绑定变量上限)。返回 dict 列表 (id/created_at/importance/frozen/
        protected/user_id/group_id), 顺序不保证 (调用方自行按 id 索引)。
        """
        ordered_ids = [str(mid) for mid in memory_ids if mid]
        if not ordered_ids:
            return []
        out: list[dict] = []
        for i in range(0, len(ordered_ids), 500):
            chunk = ordered_ids[i : i + 500]
            placeholders = ",".join("?" for _ in chunk)
            query, params = self._tenant_scope(
                f"SELECT id, created_at, importance, frozen, protected, user_id, group_id, "
                f"organization_id, tenant_id FROM episodes WHERE id IN ({placeholders})",
                chunk,
            )
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                try:
                    rows = await db.execute_fetchall(query, params)
                except Exception as exc:  # noqa: BLE001 单块失败隔离, 不拖垮整轮
                    logger.warning("episode 元数据分块查询失败, 跳过该块", error=str(exc), chunk_size=len(chunk))
                    continue
            out.extend(
                {
                    "id": str(row["id"]),
                    "created_at": int(row["created_at"] or 0),
                    "importance": float(row["importance"] or 0.5),
                    "frozen": int(row["frozen"] or 0),
                    "protected": int(row["protected"] or 0),
                    "user_id": str(row["user_id"] or ""),
                    "group_id": str(row["group_id"] or ""),
                }
                for row in rows
            )
        return out

    async def get_person_profile(self, agent_id: str, person_id: str) -> dict | None:
        # U4: 读经租户作用域 (SELECT * 投影含租户列供 enforce 外层过滤)。
        query, params = self._tenant_scope(
            "SELECT * FROM person_profiles WHERE agent_id = ? AND person_id = ?",
            [agent_id, person_id],
        )
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()
        return None if row is None else self._profile_row_to_dict(row)

    async def upsert_person_profile(self, agent_id: str, profile: dict) -> None:
        person_id = str(profile.get("person_id", "")).strip()
        if not person_id:
            raise ValueError("person profile 缺少 person_id")
        organization_id, tenant_id = self._tenant_row_values()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO person_profiles (
                    agent_id, person_id, name, profile_text, traits, relationship_depth,
                    interaction_count, first_seen, last_seen, embedding_hash,
                    organization_id, tenant_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    organization_id,
                    tenant_id,
                ),
            )
            await db.commit()

    async def increment_person_interaction(
        self,
        agent_id: str,
        person_id: str,
        *,
        name: str | None = None,
        relationship_depth_step: float = 0.0,
        now: int | None = None,
    ) -> None:
        """R12: 原子增量更新 interaction_count + relationship_depth, 消除
        read-modify-write 竞态 (同一人并发消息导致计数丢失)。

        用 INSERT ... ON CONFLICT DO UPDATE SET interaction_count =
        interaction_count + 1, relationship_depth = MIN(1.0,
        relationship_depth + ?), last_seen = ?. 新行用默认值初始化。

        name 非空时同步覆盖 name 字段 (供 manager.py 兜底 user_name)。
        first_seen 仅在 INSERT 路径生效, 已存在行不修改。
        """
        from isac.utils.helpers import unix_now as _unix_now

        clean_id = str(person_id or "").strip()
        if not clean_id:
            raise ValueError("person_id 不能为空")
        ts = int(now if now is not None else _unix_now())
        depth_step = float(relationship_depth_step or 0.0)
        # U4: INSERT 路径打租户标; ON CONFLICT DO UPDATE 不动租户列 (保留原标)。
        organization_id, tenant_id = self._tenant_row_values()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO person_profiles (
                    agent_id, person_id, name, profile_text, traits, relationship_depth,
                    interaction_count, first_seen, last_seen, embedding_hash,
                    organization_id, tenant_id
                ) VALUES (?, ?, ?, '', '[]', ?, 1, ?, ?, NULL, ?, ?)
                ON CONFLICT(agent_id, person_id) DO UPDATE SET
                    interaction_count = interaction_count + 1,
                    relationship_depth = MIN(1.0, relationship_depth + ?),
                    last_seen = ?
                    """ + (", name = ?" if name is not None else ""),
                (
                    agent_id,
                    clean_id,
                    name if name is not None else clean_id,
                    depth_step,
                    ts,
                    ts,
                    organization_id,
                    tenant_id,
                    depth_step,
                    ts,
                ) + ((name,) if name is not None else ()),
            )
            await db.commit()

    async def upsert_jargon(self, agent_id: str, word: str, meaning: str, context: str = "") -> None:
        clean_word = str(word or "").strip()
        if not clean_word:
            raise ValueError("行话 word 不能为空")
        # U4: INSERT 路径打租户标; ON CONFLICT DO UPDATE 不动租户列 (保留原标)。
        organization_id, tenant_id = self._tenant_row_values()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT INTO jargon_entries (
                    agent_id, word, meaning, context, usage_count, created_at,
                    organization_id, tenant_id
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(agent_id, word) DO UPDATE SET
                    meaning = excluded.meaning,
                    context = excluded.context,
                    usage_count = jargon_entries.usage_count + 1
                """,
                (agent_id, clean_word, str(meaning), str(context or ""), int(time.time()),
                 organization_id, tenant_id),
            )
            await db.commit()

    async def list_jargon(self, agent_id: str) -> list[dict]:
        # U4: 读经租户作用域 (SELECT * 投影含租户列), 返回仍只含业务键。
        query, params = self._tenant_scope(
            """
            SELECT * FROM jargon_entries
            WHERE agent_id = ?
            ORDER BY usage_count DESC, word ASC
            """,
            [agent_id],
        )
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            rows = await db.execute_fetchall(query, params)
        return [
            {
                "word": row["word"],
                "meaning": row["meaning"],
                "context": row["context"],
                "usage_count": row["usage_count"],
            }
            for row in rows
        ]

    async def update_episode_summary(self, agent_id: str, episode_id: str, summary: str) -> bool:
        """更新某 episode 的 summary 列 (R4-② 中期记忆压缩落盘)。

        episodes_fts_au 触发器会自动同步倒排索引; 只更新未软删条目。
        N5b 批次E: 加 organization_id/tenant_id 谓词防跨租户写 (UPDATE 不能经
        _tenant_scope 包子查询, 手动加列; 默认租户时与写入的 default 值一致不误伤)。
        返回是否实际命中并更新了一行。
        """
        clean_id = str(episode_id or "").strip()
        if not clean_id:
            return False
        org_id, tenant_id = self._tenant_row_values()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE episodes SET summary = ? "
                "WHERE agent_id = ? AND id = ? AND deleted = 0 "
                "AND organization_id = ? AND tenant_id = ?",
                (str(summary or ""), agent_id, clean_id, org_id, tenant_id),
            )
            await db.commit()
            return (cursor.rowcount or 0) > 0

    async def get_episode_summary(self, agent_id: str, episode_id: str) -> str:
        """读取某 episode 的 summary 列 (无则返回空串)。

        N5b 批次E: 加租户谓词 (经 _tenant_scope 包裹), 防跨租户读 summary;
        内层 SELECT * 投影含租户列供 enforce 子查询过滤。
        """
        clean_id = str(episode_id or "").strip()
        if not clean_id:
            return ""
        query, params = self._tenant_scope(
            "SELECT * FROM episodes WHERE agent_id = ? AND id = ?",
            [agent_id, clean_id],
        )
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()
        if not row:
            return ""
        return str(row["summary"] or "")

    async def latest_episode_id_for_session(self, agent_id: str, session_id: str) -> str:
        """读取某会话最近一次落盘的 episode id (R4-② 压缩写回定位用)。

        按 created_at 降序取首条未软删; 无则返回空串。
        """
        clean_sid = str(session_id or "").strip()
        if not clean_sid:
            return ""
        # N5b 批次E: 内层 SELECT * 投影含 organization_id/tenant_id 列,
        # 否则 _tenant_scope enforce 包裹子查询后外层 WHERE 找不到租户列报错
        # (R4 压缩链路在租户 enabled 时失效, 已实测复现)。
        query, params = self._tenant_scope(
            "SELECT * FROM episodes WHERE agent_id = ? AND session_id = ? AND deleted = 0 "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            [agent_id, clean_sid],
        )
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, params)
            row = await cursor.fetchone()
        if not row:
            return ""
        return str(row["id"] or "")

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
    def _build_filter_clause(filters: dict | None) -> tuple[str, list]:
        """结构化过滤条件 → (WHERE 片段, params)。filters=None 或空 → ("", [])。

        支持键: ``topics`` (list[str], 含任一 topic, json_each 匹配 episodes.topics
        JSON 数组); ``since`` (int Unix ts, created_at>=); ``until`` (int Unix ts,
        created_at<=)。片段带 ``episodes.`` 前缀 (兼容 JOIN 两表与单表查询)。
        """
        if not filters:
            return "", []
        clauses: list[str] = []
        params: list[Any] = []
        topics = filters.get("topics")
        if topics:
            ph = ",".join("?" for _ in topics)
            clauses.append(f"EXISTS (SELECT 1 FROM json_each(episodes.topics) WHERE value IN ({ph}))")
            params.extend(str(t) for t in topics)
        since = filters.get("since")
        if since is not None:
            clauses.append("episodes.created_at >= ?")
            params.append(int(since))
        until = filters.get("until")
        if until is not None:
            clauses.append("episodes.created_at <= ?")
            params.append(int(until))
        if not clauses:
            return "", []
        return " AND ".join(clauses), params

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
