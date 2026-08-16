"""MemoryConsolidator: 后台记忆整合 (去重/合并/剪枝, ARCHITECTURE.md 3.6)。

S2 激活: ``run_once`` 实现三步真实整合 (各步独立隔离异常, 一步失败不影响其余):
1. 去重合并: ``iter_episodes_by_namespace`` 取 (memory_id, content) 全量对, 按规范化
   内容分桶 (trim+折叠空白+小写), 桶内 ``difflib.SequenceMatcher`` 判定高相似 (≥0.92)
   视为重复, 保留 created_at 更晚者, 经 ``MemoryGovernor.delete`` 软删旧的 (governor
   拒绝 protected/frozen 条目, 自带审计 + BM25 同步)。
2. 重要性+时间衰减剪枝: ``created_at`` 早于阈值且 ``importance`` 低于阈值的条目
   经 governor 软删 (同样不硬删, 与 N2 治理审计/恢复语义一致)。
3. 画像归纳 (仅 llm 注入时): 对本命名空间近期活跃 person 的 traits + 最近若干条
   episode 内容, 让 ``llm.chat`` 生成 2-3 句 profile_text 写回 ``upsert_person_profile``;
   LLM 调用失败只记 warning、跳过该 person, 不影响整合主流程。

默认关闭: assembly 仅在 memory.consolidation.enabled=true 时构造并交给 AgentManager
随生命周期 start/stop; 未构造时 instance.services 无 "memory_consolidator" 键,
后台循环不启动, 主链路零行为变化。
"""

from __future__ import annotations

import asyncio
import difflib
import json
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.memory.storage.metadata import MetadataStore

logger = get_logger(__name__)

# 默认整合周期 (秒); 实际生效需 enabled=true 且由 AgentManager 显式 start()。
DEFAULT_INTERVAL_SECONDS: float = 3600.0

# 去重相似度阈值; ≥ 此值视为重复, 软删较旧条目 (governor 拒 protected/frozen)。
DEFAULT_DEDUP_SIMILARITY: float = 0.92
# 剪枝默认阈值: created_at 早于 now-30 天 且 importance<0.2 视为可剪枝。
DEFAULT_PRUNE_AFTER_DAYS: int = 30
DEFAULT_PRUNE_IMPORTANCE_BELOW: float = 0.2
# 画像归纳每 person 取最近若干条 episode 作素材 (避免 prompt 过长)。
DEFAULT_PROFILE_SAMPLE_EPISODES: int = 8
# 画像归纳 prompt 最大输入字符数 (episode 内容截断, 防止 LLM 输入爆炸)。
DEFAULT_PROFILE_INPUT_MAX_CHARS: int = 4000
# R4-①: 每个群聊每次行话学习处理的最大候选词数 (防止单次整合过久)。
DEFAULT_JARGON_CANDIDATES_PER_GROUP: int = 5
# R4-①: 高频候选词最低出现次数 (低于此不计入候选, 过滤噪声)。
DEFAULT_JARGON_MIN_FREQ: int = 3
# R4-①: 候选词最大长度 (过长的连续片段不像行话, 排除)。
DEFAULT_JARGON_MAX_LEN: int = 12
# R4-②: 单次会话摘要 prompt 最大输入字符数 (transcript 截断)。
DEFAULT_COMPRESS_INPUT_MAX_CHARS: int = 4000


@dataclass
class ConsolidationResult:
    """单次整合的产出计数。"""

    merged_episodes: int = 0
    pruned_episodes: int = 0
    updated_profiles: int = 0
    # R4-①: 行话学习写入数 (高频词经 LLM 释义后 upsert_jargon)
    jargon_extracted: int = 0
    # R4-②: 中期记忆压缩摘要数 (COMPRESS 入队的会话经 LLM 摘要落盘)
    compressed_summaries: int = 0


class MemoryConsolidator:
    """后台记忆整合任务 (每个 Agent 一个, 绑定其记忆命名空间)。

    默认不构造 → 不启动 → 零行为变化; 启用后由 AgentManager 随 Agent start/stop
    驱动。step 异常隔离 (单次失败不拖垮循环); llm=None 时画像归纳步骤跳过。
    """

    def __init__(
        self,
        *,
        agent_id: str,
        namespace: str,
        metadata: MetadataStore | None = None,
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        llm: Any = None,
        dedup_similarity: float = DEFAULT_DEDUP_SIMILARITY,
        prune_after_days: int = DEFAULT_PRUNE_AFTER_DAYS,
        prune_importance_below: float = DEFAULT_PRUNE_IMPORTANCE_BELOW,
        sparse_resolver: Any = None,
        vector_resolver: Any = None,
    ) -> None:
        self._agent_id = agent_id
        self._namespace = namespace
        self._metadata = metadata
        self._interval_seconds = max(1.0, float(interval_seconds))
        self._llm = llm
        self._dedup_similarity = max(0.5, min(0.99, float(dedup_similarity)))
        self._prune_after_seconds = max(0, int(prune_after_days) * 86400)
        self._prune_importance_below = max(0.0, float(prune_importance_below))
        # N5b 批次E 项2: 注入 sparse/vector resolver, 让去重/剪枝软删时同步 BM25/向量
        # (与控制面治理口径一致), 避免墓碑残留污染 IDF/长度归一与 KNN 槽位。
        self._sparse_resolver = sparse_resolver
        self._vector_resolver = vector_resolver
        self._loop_task: asyncio.Task[Any] | None = None
        # R4-②: 待压缩会话队列 (COMPRESS hook 回调入队, _compress_step 后台消费)。
        # 入队元素: {"episode_id": str, "messages": list[str], "context": str}
        self._compress_queue: list[dict[str, Any]] = []
        self._compress_lock = asyncio.Lock()

    async def run_once(self) -> ConsolidationResult:
        """执行一次整合并返回产出计数。各步骤独立隔离异常。"""
        if self._metadata is None:
            return ConsolidationResult()
        metadata: MetadataStore = self._metadata
        result = ConsolidationResult()
        episodes = await self._load_episodes(metadata)
        if not episodes:
            return result
        # Step 1: 去重合并 (失败不阻塞剪枝/归纳)
        try:
            result.merged_episodes = await self._dedup_step(episodes, metadata)
        except Exception as exc:  # noqa: BLE001
            logger.warning("记忆整合: 去重步骤失败, 已跳过", agent_id=self._agent_id, error=str(exc))
        # Step 2: 剪枝 (失败不阻塞归纳)
        try:
            result.pruned_episodes = await self._prune_step(episodes, metadata)
        except Exception as exc:  # noqa: BLE001
            logger.warning("记忆整合: 剪枝步骤失败, 已跳过", agent_id=self._agent_id, error=str(exc))
        # Step 3: 画像归纳 (仅 llm 注入时)
        if self._llm is not None:
            try:
                result.updated_profiles = await self._summarize_profiles_step(episodes, metadata)
            except Exception as exc:  # noqa: BLE001
                logger.warning("记忆整合: 画像归纳步骤失败, 已跳过", agent_id=self._agent_id, error=str(exc))
            # Step 4: 行话学习 (画像归纳同级, 复用 self._llm 释义)
            try:
                result.jargon_extracted = await self._extract_jargon_step(episodes, metadata)
            except Exception as exc:  # noqa: BLE001
                logger.warning("记忆整合: 行话学习步骤失败, 已跳过", agent_id=self._agent_id, error=str(exc))
            # Step 5: 中期记忆压缩 (R4-②, 处理待压缩队列)
            try:
                result.compressed_summaries = await self._compress_step(metadata)
            except Exception as exc:  # noqa: BLE001
                logger.warning("记忆整合: 中期记忆压缩步骤失败, 已跳过", agent_id=self._agent_id, error=str(exc))
        logger.info(
            "记忆整合 run_once 完成",
            agent_id=self._agent_id, namespace=self._namespace,
            merged=result.merged_episodes, pruned=result.pruned_episodes,
            profiles=result.updated_profiles,
            jargon=result.jargon_extracted, compressed=result.compressed_summaries,
        )
        return result

    async def _load_episodes(self, metadata: MetadataStore) -> list[dict[str, Any]]:
        """加载本命名空间全部非软删 episode (id/content/created_at/importance/frozen/protected)。"""
        try:
            pairs = await metadata.iter_episodes_by_namespace(self._namespace)
        except Exception as exc:  # noqa: BLE001
            logger.warning("记忆整合: 加载 episodes 失败", agent_id=self._agent_id, error=str(exc))
            return []
        if not pairs:
            return []
        # iter_episodes_by_namespace 只返回 (id, content), 补齐治理/时间/重要性列
        ids = [mid for mid, _ in pairs if mid]
        if not ids:
            return []
        rows = await self._fetch_episode_meta(metadata, ids)
        by_id = {r["id"]: r for r in rows if r.get("id")}
        # 合并 content (来自 iter) + 元数据 (来自 fetch); iter 已过滤 deleted=1
        out: list[dict[str, Any]] = []
        for mid, content in pairs:
            meta = by_id.get(mid, {})
            out.append({
                "id": mid,
                "content": content,
                "created_at": int(meta.get("created_at", 0) or 0),
                "importance": float(meta.get("importance", 0.5) or 0.5),
                "frozen": int(meta.get("frozen", 0) or 0),
                "protected": int(meta.get("protected", 0) or 0),
                "user_id": str(meta.get("user_id", "") or ""),
                "group_id": str(meta.get("group_id", "") or ""),
            })
        return out

    async def _fetch_episode_meta(
        self, metadata: MetadataStore, ids: list[str]
    ) -> list[dict[str, Any]]:
        """补齐 episodes 表的 created_at/importance/frozen/protected/user_id 列。"""
        import aiosqlite

        db_path = getattr(metadata, "db_path", None)
        if not db_path:
            return []
        placeholders = ",".join(["?"] * len(ids))
        query = (
            f"SELECT id, created_at, importance, frozen, protected, user_id, group_id "
            f"FROM episodes WHERE id IN ({placeholders})"
        )
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, ids)
            rows = await cursor.fetchall()
        return [
            {
                "id": str(r["id"]),
                "created_at": int(r["created_at"] or 0),
                "importance": float(r["importance"] or 0.5),
                "frozen": int(r["frozen"] or 0),
                "protected": int(r["protected"] or 0),
                "user_id": str(r["user_id"] or ""),
                "group_id": str(r["group_id"] or ""),
            }
            for r in rows
        ]

    async def _dedup_step(
        self, episodes: list[dict[str, Any]], metadata: MetadataStore
    ) -> int:
        """去重合并: 同规范化内容桶内 ≥ dedup_similarity 视为重复, 软删较旧者。

        按 created_at 降序遍历: 已加入 seen 的项 created_at 更晚 (更"新"),
        当后续较旧项找到相似匹配时, 保留 seen 中较新者, 软删当前较旧项。
        """
        from isac.memory.model.governance import MemoryGovernor

        governor = MemoryGovernor(
            metadata_store=metadata,
            sparse_resolver=self._sparse_resolver,
            vector_resolver=self._vector_resolver,
        )
        # 按 created_at 降序: 新的先入桶, 旧的后续命中相似项时被软删
        sorted_eps = sorted(
            episodes, key=lambda e: (e.get("created_at", 0), e.get("id", "")), reverse=True
        )
        seen_by_scope: dict[tuple[str, ...], list[tuple[str, dict[str, Any]]]] = {}
        merged = 0
        for ep in sorted_eps:
            content = str(ep.get("content", "") or "")
            if not content:
                continue
            norm = _normalize_content(content)
            group_id = str(ep.get("group_id", "") or "")
            user_id = str(ep.get("user_id", "") or "")
            # N5b 批次E 项4: 群聊桶加入 user_id, 避免同群不同用户相似短消息被误判重复
            # (如 A/B 各发"收到" → 规范化后相似度可 ≥ 阈值, 跨用户误删)。私聊桶按 user_id。
            scope: tuple[str, ...] = ("group", group_id, user_id) if group_id else ("user", user_id)
            seen = seen_by_scope.setdefault(scope, [])
            # 找同一访问边界内已有的高相似项 (而非精确匹配, 容许表述微差)
            dup_with = _find_similar_in_bucket(
                norm, content, seen, similarity=self._dedup_similarity
            )
            if dup_with is None:
                seen.append((norm, ep))
                continue
            # 找到重复: 保留 dup_with (列表中已有 = created_at 更晚者), 软删当前 ep
            older_id = str(ep.get("id", ""))
            if not older_id:
                continue
            ok = await governor.delete(
                older_id, self._namespace, operator="consolidator"
            )
            if ok:
                merged += 1
        return merged

    async def _prune_step(
        self, episodes: list[dict[str, Any]], metadata: MetadataStore
    ) -> int:
        """剪枝: created_at 早于阈值且 importance 低于阈值的条目软删。"""
        from isac.memory.model.governance import MemoryGovernor

        governor = MemoryGovernor(
            metadata_store=metadata,
            sparse_resolver=self._sparse_resolver,
            vector_resolver=self._vector_resolver,
        )
        now = int(time.time())
        cutoff = now - self._prune_after_seconds
        pruned = 0
        for ep in episodes:
            if int(ep.get("frozen", 0)) or int(ep.get("protected", 0)):
                continue  # frozen/protected 永不剪枝 (governor 自身也会拒绝, 但提前跳过省审计)
            created = int(ep.get("created_at", 0) or 0)
            importance = float(ep.get("importance", 0.5) or 0.5)
            if created == 0 or created >= cutoff:
                continue  # 未超期
            if importance >= self._prune_importance_below:
                continue  # 重要性足够
            older_id = str(ep.get("id", ""))
            if not older_id:
                continue
            ok = await governor.delete(
                older_id, self._namespace, operator="consolidator"
            )
            if ok:
                pruned += 1
        return pruned

    async def _summarize_profiles_step(
        self, episodes: list[dict[str, Any]], metadata: MetadataStore
    ) -> int:
        """画像归纳: 对本命名空间近期活跃 person 用 LLM 生成 profile_text 写回。"""
        # 按 user_id 分组 (取最近 N 条 episode 作素材)
        by_user: dict[str, list[dict[str, Any]]] = {}
        for ep in episodes:
            uid = str(ep.get("user_id", "") or "")
            if not uid:
                continue
            by_user.setdefault(uid, []).append(ep)
        if not by_user:
            return 0
        updated = 0
        # 限制每轮处理的 person 数量, 防止单次整合过久
        for uid in list(by_user.keys())[:20]:
            eps_for_user = sorted(
                by_user[uid], key=lambda e: e.get("created_at", 0), reverse=True
            )[:DEFAULT_PROFILE_SAMPLE_EPISODES]
            try:
                ok = await self._update_one_profile(uid, eps_for_user, metadata)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "画像归纳失败, 跳过该 person",
                    agent_id=self._agent_id, person_id=uid, error=str(exc),
                )
                continue
            if ok:
                updated += 1
        return updated

    async def _update_one_profile(
        self, person_id: str, eps: list[dict[str, Any]], metadata: MetadataStore
    ) -> bool:
        """对单 person 取既有 profile + 拼 prompt → LLM 归纳 → 写回 upsert_person_profile。"""
        # 取既有 profile (name/traits/relationship_depth 等保留)
        existing = await metadata.get_person_profile(self._namespace, person_id) or {}
        # 拼 episode 素材 (限制总字符数)
        material_parts: list[str] = []
        total = 0
        for ep in eps:
            content = str(ep.get("content", "") or "").strip()
            if not content:
                continue
            if total + len(content) > DEFAULT_PROFILE_INPUT_MAX_CHARS:
                content = content[: DEFAULT_PROFILE_INPUT_MAX_CHARS - total]
            material_parts.append(f"- {content}")
            total += len(content)
            if total >= DEFAULT_PROFILE_INPUT_MAX_CHARS:
                break
        if not material_parts:
            return False
        material = "\n".join(material_parts)
        old_text = str(existing.get("profile_text", "") or "")
        prompt = (
            "请基于以下用户的近期对话内容, 用 2-3 句中文归纳一份简洁的人物画像"
            "(兴趣爱好/性格特点/近期关注点), 不要新增未经素材支撑的猜测。"
            f"\n\n既有画像:\n{old_text or '(无)'}"
            f"\n\n近期对话素材:\n{material}"
            "\n\n请直接输出新的画像文本 (无需解释, 不要 markdown 标记):"
        )
        try:
            response = await self._llm.chat(
                system="",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=300,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "画像归纳 LLM 调用失败, 跳过该 person",
                agent_id=self._agent_id, person_id=person_id, error=str(exc),
            )
            return False
        new_text = _sanitize_llm_induction(_clean_llm_output(response.content))
        if not new_text or new_text == old_text:
            return False  # 空响应或与既有相同, 不写回
        merged_profile = dict(existing)
        merged_profile["person_id"] = person_id
        merged_profile["profile_text"] = new_text
        merged_profile["name"] = str(existing.get("name", "") or person_id)
        merged_profile.setdefault("first_seen", int(time.time()))
        merged_profile["last_seen"] = int(time.time())
        await metadata.upsert_person_profile(self._namespace, merged_profile)
        return True

    async def _extract_jargon_step(
        self, episodes: list[dict[str, Any]], metadata: MetadataStore
    ) -> int:
        """行话学习: 群聊 episode 高频词经 LLM 释义后写入 jargon 表 (R4-①)。

        仅取有 group_id 的群聊会话语料 (行话通常在群体语境涌现); 高频候选词经
        停用词/单字/既有 jargon 过滤后, 限 N 个逐个让 LLM 生成 meaning+context
        写回 ``upsert_jargon``; LLM 调用失败仅跳过该词, 不影响其余。
        """
        # 按群聚合 content (非群聊跳过, 行话需群体语境)
        texts_by_group: dict[str, list[str]] = {}
        for ep in episodes:
            gid = str(ep.get("group_id", "") or "")
            if not gid:
                continue
            content = str(ep.get("content", "") or "").strip()
            if content:
                texts_by_group.setdefault(gid, []).append(content)
        if not texts_by_group:
            return 0
        # 取既存 jargon 词集 (避免重复释义)
        try:
            existing = await metadata.list_jargon(self._namespace)
        except Exception as exc:  # noqa: BLE001
            logger.debug("行话学习: 读取既存词表失败, 以空集继续", agent_id=self._agent_id, error=str(exc))
            existing = []
        existing_words = {str(r.get("word", "")) for r in existing if r.get("word")}
        extracted = 0
        # 每群限处理一批候选词, 防止单次整合过久
        for gid in list(texts_by_group.keys())[:5]:
            candidates = _top_candidate_words(texts_by_group[gid], existing_words)
            for word in candidates[:DEFAULT_JARGON_CANDIDATES_PER_GROUP]:
                ok = await self._define_one_jargon(word, gid, metadata, existing_words)
                if ok:
                    extracted += 1
        return extracted

    async def _define_one_jargon(
        self, word: str, group_id: str, metadata: MetadataStore, existing: set[str]
    ) -> bool:
        """对单个候选词调 LLM 生成 meaning + context, 写回 upsert_jargon。"""
        prompt = (
            f"术语「{word}」出现在某个群聊中, 可能是该群体的行话/缩写/专有名词。"
            "请用一句中文给出它的含义释义, 并用一句中文给出一个典型使用语境。"
            "若无法判断真实含义, 直接回复「未知」。\n"
            "输出格式 (严格两行, 不要 markdown):\n"
            "MEANING: <释义>\n"
            "CONTEXT: <使用语境>"
        )
        try:
            response = await self._llm.chat(
                system="",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=200,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("行话学习: LLM 释义失败, 跳过该词", agent_id=self._agent_id, word=word, error=str(exc))
            return False
        meaning, context = _parse_jargon_response(response.content)
        meaning = _sanitize_llm_induction(meaning)
        if not meaning or meaning == "未知":
            return False
        try:
            await metadata.upsert_jargon(self._namespace, word, meaning, context or group_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("行话学习: 写入 jargon 失败, 跳过该词", agent_id=self._agent_id, word=word, error=str(exc))
            return False
        existing.add(word)
        return True

    async def _compress_step(self, metadata: MetadataStore) -> int:
        """中期记忆压缩 (R4-②): 消费待压缩队列, LLM 摘要落 episodes.summary。

        COMPRESS hook 回调仅入队 session_id+messages 快照 (不调 LLM, 守护 hook
        规范); 本 step 在后台低频消费队列, 对每个待压缩会话解析其最近 episode
        → 生成摘要写回其 summary 列。摘要素材为入队快照 messages。
        """
        async with self._compress_lock:
            if not self._compress_queue:
                return 0
            batch = self._compress_queue[:]
            self._compress_queue.clear()
        compressed = 0
        for item in batch:
            session_id = str(item.get("session_id", "") or "")
            messages = item.get("messages") or []
            if not session_id or not messages:
                continue
            summary = await self._summarize_one_session(messages, item.get("context", ""))
            if not summary:
                continue
            try:
                episode_id = await metadata.latest_episode_id_for_session(
                    self._namespace, session_id
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "中期记忆压缩: 解析 episode 失败, 跳过",
                    agent_id=self._agent_id, session_id=session_id, error=str(exc),
                )
                continue
            if not episode_id:
                continue  # 本会话尚无落盘 episode, 无处写回
            try:
                await metadata.update_episode_summary(self._namespace, episode_id, summary)
                compressed += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "中期记忆压缩: 写回 summary 失败, 跳过",
                    agent_id=self._agent_id, episode_id=episode_id, error=str(exc),
                )
        return compressed

    async def _summarize_one_session(self, messages: list[Any], context: str) -> str:
        """对单次会话 messages 用 LLM 生成中文摘要 (失败返回空串)。"""
        transcript = _format_session_transcript(messages, DEFAULT_COMPRESS_INPUT_MAX_CHARS)
        if not transcript:
            return ""
        prompt = (
            "请将以下会话片段压缩为一段简洁中文摘要 (保留关键事实/结论/待办, 省略寒暄), "
            "不超过 3 句话, 不要 markdown 标记:"
            f"\n\n语境: {context or '(无)'}"
            f"\n\n会话片段:\n{transcript}"
        )
        try:
            response = await self._llm.chat(
                system="",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=300,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("中期记忆压缩: LLM 摘要失败, 跳过", agent_id=self._agent_id, error=str(exc))
            return ""
        return _clean_llm_output(response.content)

    async def enqueue_compression(
        self, session_id: str, messages: list[Any], context: str = ""
    ) -> None:
        """COMPRESS hook 回调入口: 仅入队待压缩会话, 不调 LLM (守护 hook 规范)。

        由 assembly 注册的 COMPRESS listener 调用, 把会话快照存入后台队列,
        实际摘要在下一个 ``run_once`` 的 _compress_step 中低频完成。入队键为
        session_id (COMPRESS 回调拿不到 episode_id, 由 _compress_step 解析)。
        """
        if not session_id or not messages:
            return
        async with self._compress_lock:
            # 防重复入队同一会话 (未消费时覆盖其最新快照)
            self._compress_queue = [
                x for x in self._compress_queue if x.get("session_id") != session_id
            ]
            self._compress_queue.append({
                "session_id": session_id,
                "messages": list(messages),
                "context": str(context or ""),
            })

    async def latest_summary_for_session(self, metadata: MetadataStore, session_id: str) -> str:
        """读取本会话最近 episode 的已落盘 summary (供 MidTermMemoryInjector 注入)。

        无 summary 或无 episode 时返回空串 (注入器据此降级为不注入)。
        """
        if not session_id:
            return ""
        try:
            episode_id = await metadata.latest_episode_id_for_session(
                self._namespace, session_id
            )
        except Exception:  # noqa: BLE001
            return ""
        if not episode_id:
            return ""
        try:
            return await metadata.get_episode_summary(self._namespace, episode_id)
        except Exception:  # noqa: BLE001
            return ""

    async def start(self) -> None:
        """启动后台整合循环 (重复 start 不重启, 保留首个循环)。"""
        if self._loop_task is not None and not self._loop_task.done():
            return
        self._loop_task = asyncio.create_task(self._loop(), name=f"memory-consolidator-{self._agent_id}")

    async def stop(self) -> None:
        """取消后台整合循环 (重复 stop 安全)。"""
        if self._loop_task is None:
            return
        self._loop_task.cancel()
        try:
            await self._loop_task
        except asyncio.CancelledError:
            pass
        self._loop_task = None

    async def _loop(self) -> None:
        """后台循环: 按 interval 周期调用 run_once, 单次异常被隔离不拖垮循环。"""
        try:
            while True:
                await asyncio.sleep(self._interval_seconds)
                try:
                    await self.run_once()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("记忆整合单次执行失败, 已跳过", agent_id=self._agent_id, error=str(exc))
        except asyncio.CancelledError:
            logger.debug("记忆整合循环已取消", agent_id=self._agent_id)
            raise


# ── 模块级辅助函数 (供单测直接 import) ────────────────────────────


def _normalize_content(text: str) -> str:
    """规范化内容 (去所有空白 + 小写) 用于去重分桶 (空白差异视为同一条)。"""
    return "".join((text or "").lower().split())


def _find_similar_in_bucket(
    norm: str,
    content: str,
    seen: list[tuple[str, dict[str, Any]]],
    *,
    similarity: float = DEFAULT_DEDUP_SIMILARITY,
) -> dict[str, Any] | None:
    """在已见桶中找与 content 相似度 ≥ dedup_similarity 的项, 返回该项的 episode 或 None。

    实现先用规范化字符串精确匹配 (快速判定完全相同), 再对桶内项做 SequenceMatcher
    (慢但只在桶小时运行)。返回 None 表示无重复。
    """
    for seen_norm, seen_ep in seen:
        if seen_norm == norm:
            return seen_ep  # 完全相同 → 视为重复
    # 桶内非精确匹配项再做相似度比对 (SequenceMatcher 是 O(n*m), 桶小可接受)
    for seen_norm, seen_ep in seen:
        ratio = difflib.SequenceMatcher(None, norm, seen_norm).ratio()
        if ratio >= similarity:
            return seen_ep
    _ = content  # 占位 (norm 已是规范化的 content)
    return None


def _clean_llm_output(text: Any) -> str:
    """清洗 LLM 返回 (去首尾空白 / 去多余引号包裹)。"""
    if not text:
        return ""
    out = str(text).strip()
    if len(out) >= 2 and out[0] in "\"'" and out[-1] == out[0]:
        out = out[1:-1].strip()
    # 去除可能的 markdown 代码块标记
    if out.startswith("```"):
        lines = out.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        out = "\n".join(lines).strip()
    return out


# N5b 批次E 项5: 归纳产物 (profile_text/jargon meaning) 经 _clean_llm_output 后再过
# 注入防护层 —— 剥离指令前缀行 (防间接 prompt injection: 攻击者在对话埋诱导内容,
# LLM 归纳出含指令的 profile_text, 落盘后被注入器拼入系统 prompt)。未覆盖全部注入
# 变体, 但消除最常见的指令前缀式注入; 注入器侧仍应做边界标记与长度上限 (后续)。
_INJECTION_PREFIX_RE = re.compile(
    r"^[ \t]*(?:System|SYSTEM|Assistant|IMPORTANT|CRITICAL|忽略[^\n:：]*|disregard\w*)\s*[:：].*$\n?",
    re.MULTILINE,
)


def _sanitize_llm_induction(text: str) -> str:
    """剥离归纳产物中的指令前缀行 (防间接 prompt injection)。"""
    if not text:
        return ""
    out = _INJECTION_PREFIX_RE.sub("", text)
    return "\n".join(line for line in out.splitlines() if line.strip()).strip()


# R4-①: 内置中文停用词小表 (常见虚词/语气词, 不引入 jieba 依赖)。
_JARGON_STOPWORDS: frozenset[str] = frozenset({
    "的", "了", "是", "在", "我", "你", "他", "她", "它", "们", "和", "与", "或",
    "这", "那", "这个", "那个", "什么", "怎么", "为什么", "哪里", "一个", "一些",
    "不", "没", "没有", "也", "都", "就", "还", "又", "把", "被", "让", "给",
    "可以", "可能", "应该", "需要", "现在", "今天", "明天", "昨天", "觉得",
    "知道", "觉得", "然后", "因为", "所以", "但是", "如果", "虽然", "不过",
    "请问", "谢谢", "好的", "好吧", "嗯", "啊", "吧", "呢", "哦", "哈", "诶",
})


def _tokenize_cjk(text: str) -> list[str]:
    """简易中文分词: 取连续 CJK 汉字片段 + 2-gram 滑窗 (无 jieba 依赖)。

    对每个连续汉字片段, 用 2 字滑窗产生 bigram 作为候选行话单元 (中文行话多为
    2-4 字); 英文/数字片段按空白与标点切分为整词。长度 1 的单字排除 (噪声大)。
    """
    out: list[str] = []
    buf: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if "一" <= ch <= "鿿":
            buf.append(ch)
            i += 1
            continue
        if buf:
            _flush_cjk_buf(buf, out)
            buf = []
        # 非汉字: 收集连续字母数字下划线作英文整词
        if ch.isalnum() or ch == "_":
            wbuf = ch
            while i + 1 < len(text) and (text[i + 1].isalnum() or text[i + 1] == "_"):
                i += 1
                wbuf += text[i]
            if len(wbuf) >= 2:
                out.append(wbuf.lower())
        i += 1
    if buf:
        _flush_cjk_buf(buf, out)
    return out


def _flush_cjk_buf(buf: list[str], out: list[str]) -> None:
    """把连续汉字缓冲区切成 2-gram 滑窗候选词。"""
    n = len(buf)
    if n == 1:
        return  # 单字噪声大, 排除
    for start in range(n - 1):
        out.append("".join(buf[start : start + 2]))


def _top_candidate_words(texts: list[str], existing: set[str]) -> list[str]:
    """从一批群聊文本统计高频候选行话词 (去停用词/单字/既有 jargon)。

    无外部分词依赖, 用 2-gram bigram 粗统计; 过滤停用词、过长片段、既存词;
    返回按频次降序、≥ DEFAULT_JARGON_MIN_FREQ 的候选词列表。
    """
    from collections import Counter

    counter: Counter[str] = Counter()
    for raw in texts:
        text = str(raw or "")
        for tok in _tokenize_cjk(text):
            if len(tok) < 2 or len(tok) > DEFAULT_JARGON_MAX_LEN:
                continue
            if tok in _JARGON_STOPWORDS:
                continue
            if tok in existing:
                continue
            counter[tok] += 1
    return [
        w for w, c in counter.most_common(50)
        if c >= DEFAULT_JARGON_MIN_FREQ
    ]


def _parse_jargon_response(text: Any) -> tuple[str, str]:
    """解析行话释义 LLM 输出 (MEANING: / CONTEXT: 两行), 返回 (meaning, context)。"""
    raw = _clean_llm_output(text)
    if not raw:
        return "", ""
    meaning = ""
    context = ""
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("meaning:") or low.startswith("含义") or low.startswith("释义"):
            meaning = line.split(":", 1)[-1].strip() if ":" in line else line
        elif low.startswith("context:") or low.startswith("语境") or low.startswith("使用"):
            context = line.split(":", 1)[-1].strip() if ":" in line else line
    return meaning, context


def _format_session_transcript(messages: list[Any], max_chars: int) -> str:
    """把会话 messages 列表格式化为截断的 transcript 文本 (供摘要 prompt)。"""
    parts: list[str] = []
    total = 0
    for msg in messages:
        if isinstance(msg, str):
            text = msg
        elif isinstance(msg, dict):
            role = str(msg.get("role", "") or "").strip()
            content = str(msg.get("content", "") or "").strip()
            text = f"[{role}] {content}" if role else content
        else:
            text = str(msg or "")
        text = text.strip()
        if not text:
            continue
        if total + len(text) > max_chars:
            text = text[: max(0, max_chars - total)]
        parts.append(text)
        total += len(text)
        if total >= max_chars:
            break
    return "\n".join(parts)


# 避免 json 未使用 import 警告 (保留供后续扩展, 如审计细节序列化)
_ = json
