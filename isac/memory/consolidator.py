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


@dataclass
class ConsolidationResult:
    """单次整合的产出计数。"""

    merged_episodes: int = 0
    pruned_episodes: int = 0
    updated_profiles: int = 0


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
    ) -> None:
        self._agent_id = agent_id
        self._namespace = namespace
        self._metadata = metadata
        self._interval_seconds = max(1.0, float(interval_seconds))
        self._llm = llm
        self._dedup_similarity = max(0.5, min(0.99, float(dedup_similarity)))
        self._prune_after_seconds = max(0, int(prune_after_days) * 86400)
        self._prune_importance_below = max(0.0, float(prune_importance_below))
        self._loop_task: asyncio.Task[Any] | None = None

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
        logger.info(
            "记忆整合 run_once 完成",
            agent_id=self._agent_id, namespace=self._namespace,
            merged=result.merged_episodes, pruned=result.pruned_episodes,
            profiles=result.updated_profiles,
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
            f"SELECT id, created_at, importance, frozen, protected, user_id "
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

        governor = MemoryGovernor(metadata_store=metadata)
        # 按 created_at 降序: 新的先入桶, 旧的后续命中相似项时被软删
        sorted_eps = sorted(
            episodes, key=lambda e: (e.get("created_at", 0), e.get("id", "")), reverse=True
        )
        seen: list[tuple[str, dict[str, Any]]] = []  # [(normalized_key, episode)]
        merged = 0
        for ep in sorted_eps:
            content = str(ep.get("content", "") or "")
            if not content:
                continue
            norm = _normalize_content(content)
            # 找桶内已有的高相似项 (而非精确匹配, 容许表述微差)
            dup_with = _find_similar_in_bucket(norm, content, seen)
            if dup_with is None:
                seen.append((norm, ep))
                continue
            # 找到重复: 保留 dup_with (列表中已有 = created_at 更晚者), 软删当前 ep
            older_id = str(ep.get("id", ""))
            if not older_id:
                continue
            ok = await governor.delete(
                older_id, self._agent_id, operator="consolidator"
            )
            if ok:
                merged += 1
        return merged

    async def _prune_step(
        self, episodes: list[dict[str, Any]], metadata: MetadataStore
    ) -> int:
        """剪枝: created_at 早于阈值且 importance 低于阈值的条目软删。"""
        from isac.memory.model.governance import MemoryGovernor

        governor = MemoryGovernor(metadata_store=metadata)
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
                older_id, self._agent_id, operator="consolidator"
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
            new_text = await self._llm.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=300,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "画像归纳 LLM 调用失败, 跳过该 person",
                agent_id=self._agent_id, person_id=person_id, error=str(exc),
            )
            return False
        new_text = _clean_llm_output(new_text)
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
    norm: str, content: str, seen: list[tuple[str, dict[str, Any]]]
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
        if ratio >= 0.92:
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


# 避免 json 未使用 import 警告 (保留供后续扩展, 如审计细节序列化)
_ = json
