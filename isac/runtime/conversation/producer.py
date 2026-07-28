"""主动任务生产者 (R2-2, HUMANLIKE_RUNTIME.md §5.2)。

ProactiveScheduler 只是"消费者"——后台循环从队列取任务并触发。此前生产侧没有
任何代码往队列 enqueue, 队列恒空, 整个主动任务子系统不可达。本模块提供第一个
真实生产者 IdleReengageProducer: 会话静默超过阈值时产出一个"主动关心"任务,
交给调度器 (经 authorize/冷却/唤醒回调) 触发。

S1 激活: DateReminder / TopicFollowup / MemoryAssociation 三个生产者填真实产出
逻辑, 复用既有 memory.search (带 user_id/group_id ACL) 作为信息来源, 不引入新表。
默认关闭 (assembly 仅在 conversation.proactive.*_enabled=True 时接入各生产者),
保持主链路零行为变化。
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from isac.runtime.conversation.models import ProactiveTask
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.runtime.conversation.registry import ConversationRuntimeRegistry

logger = get_logger(__name__)


class IdleReengageProducer:
    """空闲重连生产者: 会话静默超过 idle_seconds 时产出一个主动 re-engage 任务。

    调度器每个 poll 周期调用 ``producer(now)`` 收集待入队任务。去重策略保证一个静默
    窗口只主动打扰一次: 记录上次 re-engage 时该会话的 last_message_received_at,
    只有用户又发了新消息 (该时间戳前进) 才会重新武装, 避免对沉默用户反复轰炸。
    """

    def __init__(
        self,
        *,
        agent_id: str,
        registry: ConversationRuntimeRegistry,
        idle_seconds: float,
        priority: str = "low",
        caller_token: str = "",
    ) -> None:
        self._agent_id = agent_id
        self._registry = registry
        self._idle_seconds = max(1.0, float(idle_seconds))
        self._priority = priority
        self._caller_token = caller_token
        # session_id -> 上次 re-engage 时的 last_message_received_at (去重/重新武装依据)
        self._reengaged_marker: dict[str, float] = {}

    async def __call__(self, now: float) -> list[ProactiveTask]:
        tasks: list[ProactiveTask] = []
        for session_id, runtime in self._registry.active_runtimes():
            last_activity = float(runtime.last_message_received_at or 0.0)
            if last_activity <= 0.0:
                continue  # 从未收到消息: 不主动打扰
            if (now - last_activity) < self._idle_seconds:
                continue  # 尚未静默够久
            if self._reengaged_marker.get(session_id, 0.0) >= last_activity:
                continue  # 本次静默窗口已 re-engage 过 (等新消息重置)
            self._reengaged_marker[session_id] = last_activity
            tasks.append(
                ProactiveTask(
                    task_id=f"reengage-{uuid.uuid4().hex[:12]}",
                    agent_id=self._agent_id,
                    session_id=session_id,
                    source="schedule",
                    intent="reengage",
                    reason="对话已静默一段时间, 主动关心一下",
                    priority=self._priority,
                    created_at=now,
                    caller_token=self._caller_token,
                )
            )
        if tasks:
            logger.debug("空闲重连生产者产出主动任务", agent_id=self._agent_id, count=len(tasks))
        return tasks


# S1: 日期解析正则 —— 匹配 "X月Y日" / "X-Y" / "X/Y" 月份-日期组合
_DATE_PATTERN = re.compile(
    r"(?:(\d{1,2})\s*[月/-]\s*(\d{1,2})\s*日?)"
)
# 日期类关键词, 命中后才视为"重要日期"而非普通数字
_DATE_KEYWORDS = ("生日", "诞辰", "周年", "纪念日", "deadline", "到期", "续费")


def _parse_dates(text: str) -> list[tuple[int, int]]:
    """从文本中抽取 (month, day) 日期, 仅保留合法日期 (1-12 月 / 1-31 日)。"""
    out: list[tuple[int, int]] = []
    for m in _DATE_PATTERN.finditer(text or ""):
        try:
            month = int(m.group(1))
            day = int(m.group(2))
        except (TypeError, ValueError):
            continue
        if 1 <= month <= 12 and 1 <= day <= 31:
            out.append((month, day))
    return out


def _is_date_relevant(text: str) -> bool:
    """判断文本是否含日期关键词 (避免把任意含数字的句子当日期提醒)。"""
    lowered = (text or "").lower()
    return any(kw in lowered for kw in _DATE_KEYWORDS)


class DateReminderProducer:
    """重要日期提醒生产者: 记忆中的重要日期 (生日/纪念日/承诺到期) 临近时产出提醒任务。

    S1 激活: 从活跃会话最近一条消息取 user_id/group_id 作为 ACL 锚点, 调
    ``memory.search`` 查询"生日/纪念日/周年"等关键词, 解析命中内容中的日期, 与
    ``now`` 比对触发窗口 (同日或未来 1-2 天)。同一日期 (session_id, month, day) 在
    同一公历年只提醒一次 (仿 ``IdleReengageProducer._reengaged_marker`` 去重)。
    memory=None 时恒返回 [] (兼容骨架单测, 零行为变化)。
    """

    def __init__(
        self,
        *,
        agent_id: str,
        registry: ConversationRuntimeRegistry,
        memory: Any = None,
        priority: str = "normal",
        caller_token: str = "",
        lead_days: int = 1,
    ) -> None:
        self._agent_id = agent_id
        self._registry = registry
        self._memory = memory
        self._priority = priority
        self._caller_token = caller_token
        # 触发窗口: 当日 (lead_days=0) 或未来 1 天 (lead_days=1, 默认)
        self._lead_days = max(0, int(lead_days))
        # (session_id, month, day) -> 上次提醒的公历年; 同一年同一天只提醒一次
        self._fired_marker: dict[tuple[str, int, int], int] = {}

    async def __call__(self, now: float) -> list[ProactiveTask]:
        if self._memory is None:
            return []
        tasks: list[ProactiveTask] = []
        now_struct = time.localtime(now)
        today = (now_struct.tm_mon, now_struct.tm_mday)
        for session_id, runtime in self._registry.active_runtimes():
            hits = await self._search_user_dates(runtime)
            if not hits:
                continue
            tasks.extend(
                self._build_date_tasks(hits, session_id, today, now_struct, now)
            )
        if tasks:
            logger.debug("日期提醒生产者产出主动任务", agent_id=self._agent_id, count=len(tasks))
        return tasks

    async def _search_user_dates(self, runtime: Any) -> list[Any]:
        """对该会话最近消息的用户做记忆检索 (失败/无消息返回 [])。"""
        ctx = _resolve_session_context(runtime)
        if ctx is None:
            return []
        user_id, group_id = ctx
        try:
            return await self._memory.search(
                "生日 纪念日 周年 到期",
                top_k=5, user_id=user_id, group_id=group_id,
            ) or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("日期提醒检索失败, 跳过该会话", agent_id=self._agent_id, error=str(exc))
            return []

    def _build_date_tasks(
        self, hits: list[Any], session_id: str, today: tuple[int, int],
        now_struct: time.struct_time, now: float,
    ) -> list[ProactiveTask]:
        """从命中内容解析日期, 在触发窗口内的产出 task (本年同日去重)。"""
        tasks: list[ProactiveTask] = []
        for hit in hits:
            content = getattr(hit, "content", "") or ""
            if not _is_date_relevant(content):
                continue
            for month, day in _parse_dates(content):
                if not _in_trigger_window(month, day, today, self._lead_days):
                    continue
                key = (session_id, month, day)
                if self._fired_marker.get(key, 0) >= now_struct.tm_year:
                    continue  # 本年已提醒过
                self._fired_marker[key] = now_struct.tm_year
                tasks.append(
                    ProactiveTask(
                        task_id=f"date-{uuid.uuid4().hex[:12]}",
                        agent_id=self._agent_id,
                        session_id=session_id,
                        source="memory",
                        intent="date_reminder",
                        reason=f"临近重要日期: {month}月{day}日",
                        priority=self._priority,
                        created_at=now,
                        caller_token=self._caller_token,
                    )
                )
                break  # 同一会话同 hit 仅产出一条
        return tasks


# 未闭合话题的"延后型"信号
_FOLLOWUP_KEYWORDS = ("提醒我", "回头", "下次", "等我", "稍后", "回头说", "晚点", "等会儿", "之后再")
_QUESTION_TAIL = ("？", "?")


class TopicFollowupProducer:
    """未完话题跟进生产者: 用户留下的未闭合话题 (待办/未回答的问题) 在合适时机主动跟进。

    S1 激活: 取活跃会话最近一条用户消息内容, 若含"延后型短语" (提醒我/回头/下次…)
    或问号结尾的提问, 且静默已超冷却窗口 (默认 1800s), 产出 intent="topic_followup"。
    去重: (session_id, last_message_received_at) 标记, 同一静默窗口只跟进一次, 用户
    发新消息后重新武装 (仿 IdleReengage 语义)。memory=None 时仍可工作 (不需要检索),
    仅依赖 message_cache。
    """

    def __init__(
        self,
        *,
        agent_id: str,
        registry: ConversationRuntimeRegistry,
        memory: Any = None,
        priority: str = "normal",
        caller_token: str = "",
        followup_idle_seconds: float = 1800.0,
    ) -> None:
        self._agent_id = agent_id
        self._registry = registry
        self._memory = memory  # 当前实现不需要 memory, 保留参数为后续扩展 (不破坏装配)
        self._priority = priority
        self._caller_token = caller_token
        self._followup_idle_seconds = max(60.0, float(followup_idle_seconds))
        # (session_id) -> 上次跟进时的 last_message_received_at (去重/重新武装依据)
        self._fired_marker: dict[str, float] = {}

    async def __call__(self, now: float) -> list[ProactiveTask]:
        tasks: list[ProactiveTask] = []
        for session_id, runtime in self._registry.active_runtimes():
            last_activity = float(runtime.last_message_received_at or 0.0)
            if last_activity <= 0.0:
                continue
            if (now - last_activity) < self._followup_idle_seconds:
                continue  # 未到冷却窗口
            if self._fired_marker.get(session_id, 0.0) >= last_activity:
                continue  # 本窗口已跟进过
            tail = _last_user_message(runtime)
            if not tail:
                continue
            if not _looks_unfinished(tail):
                continue
            self._fired_marker[session_id] = last_activity
            tasks.append(
                ProactiveTask(
                    task_id=f"followup-{uuid.uuid4().hex[:12]}",
                    agent_id=self._agent_id,
                    session_id=session_id,
                    source="memory",
                    intent="topic_followup",
                    reason="用户留下未闭合话题, 主动跟进",
                    priority=self._priority,
                    created_at=now,
                    caller_token=self._caller_token,
                )
            )
        if tasks:
            logger.debug("话题跟进生产者产出主动任务", agent_id=self._agent_id, count=len(tasks))
        return tasks


class MemoryAssociationProducer:
    """记忆联想生产者: 当前上下文与历史记忆强关联时, 主动"想起"并发起相关话题。

    S1 激活: 取活跃会话最近 1-3 条消息内容拼接为 query, 调 ``memory.search`` 取 top-1,
    若 score 超过阈值且该 hit.id 在最近 N 次产出中未出现, 产出
    intent="memory_association", reason 引用 hit.content 前 50 字。memory=None 时
    恒返回 [] (零行为变化)。
    """

    # 单会话最近产出过的 hit.id 去重集合上限 (按会话裁剪, 避免长期增长)
    _DEDUP_PER_SESSION = 50

    def __init__(
        self,
        *,
        agent_id: str,
        registry: ConversationRuntimeRegistry,
        memory: Any = None,
        priority: str = "low",
        caller_token: str = "",
        min_score: float = 0.15,
    ) -> None:
        self._agent_id = agent_id
        self._registry = registry
        self._memory = memory
        self._priority = priority
        self._caller_token = caller_token
        self._min_score = float(min_score)
        # session_id -> set of hit.id (FIFO 截断到 _DEDUP_PER_SESSION)
        self._recent_hits: dict[str, list[str]] = {}

    async def __call__(self, now: float) -> list[ProactiveTask]:
        if self._memory is None:
            return []
        tasks: list[ProactiveTask] = []
        for session_id, runtime in self._registry.active_runtimes():
            best = await self._search_best_match(runtime)
            if best is None:
                continue
            if self._is_recent_hit(session_id, best):
                continue
            self._record_recent_hit(session_id, best)
            tasks.append(self._build_task(session_id, best, now))
        if tasks:
            logger.debug("记忆联想生产者产出主动任务", agent_id=self._agent_id, count=len(tasks))
        return tasks

    async def _search_best_match(self, runtime: Any) -> Any | None:
        """对该会话最近消息拼接 query 检索记忆, 返回 score 超阈值的 top-1 (或 None)。"""
        ctx = _resolve_session_context(runtime)
        if ctx is None:
            return None
        user_id, group_id = ctx
        query = _recent_context_text(runtime, max_messages=3)
        if not query:
            return None
        try:
            hits = await self._memory.search(
                query, top_k=1, user_id=user_id, group_id=group_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("记忆联想检索失败, 跳过该会话", agent_id=self._agent_id, error=str(exc))
            return None
        if not hits:
            return None
        best = hits[0]
        score = float(getattr(best, "score", 0.0) or 0.0)
        if score < self._min_score:
            return None
        return best

    def _is_recent_hit(self, session_id: str, best: Any) -> bool:
        """去重: 该 hit.id 在本会话最近产出集合中出现过则跳过。"""
        hit_id = str(getattr(best, "id", "") or "")
        if not hit_id:
            return False
        recent = self._recent_hits.get(session_id, [])
        return hit_id in recent

    def _record_recent_hit(self, session_id: str, best: Any) -> None:
        """把 hit.id 加入本会话最近产出集合 (FIFO 截断到 _DEDUP_PER_SESSION)。"""
        hit_id = str(getattr(best, "id", "") or "")
        if not hit_id:
            return
        recent = self._recent_hits.setdefault(session_id, [])
        recent.append(hit_id)
        if len(recent) > self._DEDUP_PER_SESSION:
            del recent[: len(recent) - self._DEDUP_PER_SESSION]

    def _build_task(self, session_id: str, best: Any, now: float) -> ProactiveTask:
        content = str(getattr(best, "content", "") or "")
        reason = (content[:50] + "…") if len(content) > 50 else content
        return ProactiveTask(
            task_id=f"assoc-{uuid.uuid4().hex[:12]}",
            agent_id=self._agent_id,
            session_id=session_id,
            source="memory",
            intent="memory_association",
            reason=f"想起相关记忆: {reason}" if reason else "想起相关记忆",
            priority=self._priority,
            created_at=now,
            caller_token=self._caller_token,
        )


class CompositeTaskProducer:
    """组合多个主动任务生产者: 每个 poll 周期依次调用各生产者并汇总产出。

    供 assembly 在启用多个生产者时合并成 ProactiveScheduler 期望的单个
    ``callable(now) -> list[ProactiveTask]``, 不改动 ProactiveScheduler 的既有契约。
    单个生产者异常被隔离, 不影响其他生产者与调度循环。
    """

    def __init__(self, producers: list[Callable[[float], Awaitable[list[ProactiveTask]]]]) -> None:
        self._producers = list(producers)

    async def __call__(self, now: float) -> list[ProactiveTask]:
        tasks: list[ProactiveTask] = []
        for producer in self._producers:
            try:
                tasks.extend(await producer(now))
            except Exception as exc:  # noqa: BLE001
                logger.warning("主动任务生产者执行失败, 已跳过", error=str(exc))
        return tasks


# ── 辅助函数 (模块级, 便于单测) ────────────────────────────────────


def _resolve_session_context(runtime: Any) -> tuple[str, str] | None:
    """从 ConversationRuntime.message_cache 末条消息取 (user_id, group_id_or_empty)。

    ACL 锚点: 必须用消息里真实的 user_id/group_id 调 memory.search, 否则跨用户
    检索会违反 ACL 铁律 (HANDOFF.md §0 第 3 条)。
    """
    cache = getattr(runtime, "message_cache", None)
    if not cache:
        return None
    last = cache[-1]
    user_id = str(getattr(last, "user_id", "") or "")
    if not user_id:
        return None
    group_id = str(getattr(last, "group_id", "") or "")
    return user_id, group_id


def _last_user_message(runtime: Any) -> str:
    """取 ConversationRuntime.message_cache 末条消息内容 (空则返回空串)。"""
    cache = getattr(runtime, "message_cache", None)
    if not cache:
        return ""
    last = cache[-1]
    return str(getattr(last, "content", "") or "")


def _recent_context_text(runtime: Any, *, max_messages: int = 3) -> str:
    """拼接最近 N 条消息的 content 作为联想检索 query。"""
    cache = getattr(runtime, "message_cache", None)
    if not cache:
        return ""
    take = cache[-max(1, int(max_messages)) :]
    parts = [str(getattr(m, "content", "") or "") for m in take]
    return " ".join(p for p in parts if p).strip()


def _looks_unfinished(text: str) -> bool:
    """判断末条消息是否含"未闭合话题"信号 (延后型短语或问号结尾)。"""
    if not text:
        return False
    lowered = text.lower()
    if any(kw in lowered for kw in _FOLLOWUP_KEYWORDS):
        return True
    return text.rstrip().endswith(tuple(_QUESTION_TAIL))


def _in_trigger_window(month: int, day: int, today: tuple[int, int], lead_days: int) -> bool:
    """判断 (month, day) 是否在触发窗口内 (今日或未来 lead_days 天内, 跨年回绕)。"""
    if lead_days <= 0:
        return (month, day) == today
    # 简化: 同月同日 + 未来 lead_days 天 (不跨月); 跨月场景按 month/day 比较的简化逻辑
    if month == today[0]:
        return today[1] <= day <= today[1] + lead_days
    # 跨月 (如 1月31日 vs 2月1日): 用年积日近似, 避免引入 calendar 复杂度
    target_doy = _day_of_year(month, day)
    today_doy = _day_of_year(today[0], today[1])
    if target_doy is None or today_doy is None:
        return (month, day) == today
    return 0 <= (target_doy - today_doy) % 366 <= lead_days


def _day_of_year(month: int, day: int) -> int | None:
    """简化年积日计算 (不考虑闰年, 2 月按 28 天计)。"""
    days_per_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if not (1 <= month <= 12) or not (1 <= day <= days_per_month[month - 1]):
        return None
    return sum(days_per_month[: month - 1]) + day
