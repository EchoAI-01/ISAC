"""ProactiveScheduler: 主动任务调度 (L3, HUMANLIKE_RUNTIME.md §5.2)。

L3 实现: 后台循环按 poll_interval_seconds 周期 poll queue → authorize (allowed_sources)
→ may_fire (min_interval_seconds 冷却) → to_forced_turn (更新 _last_fired_at) →
wake_callback (manager 注入, 唤醒对应会话 ConversationRuntime)。默认 enabled=False
不启动后台循环, 主链路零行为变化。
"""

from __future__ import annotations

import asyncio
import hmac
from collections.abc import Awaitable, Callable

from isac.runtime.conversation.models import ForcedTurnState, ProactiveTask, TriggerSource
from isac.runtime.conversation.proactive import ProactiveTaskQueue
from isac.utils.logger import get_logger

logger = get_logger(__name__)

# 默认允许的来源集合 (HUMANLIKE_RUNTIME.md §5.2); 不在此集合的 source 一律拒绝, 防滥用。
DEFAULT_ALLOWED_SOURCES: frozenset[str] = frozenset({"plugin", "memory", "schedule", "agent", "api"})

# 默认后台轮询周期; 实际生效需 enabled=True 显式 start()。1 秒兼顾响应性与低开销。
DEFAULT_POLL_INTERVAL_SECONDS: float = 1.0

WakeCallback = Callable[[ProactiveTask], "Awaitable[None]"]


class ProactiveScheduler:
    """主动任务调度器 (驱动 ProactiveTaskQueue + 后台循环)。

    每个 Agent 一个; 由 L3 的后台循环按冷却/频率驱动; 默认不 start, 不产生主动发言。
    """

    def __init__(
        self,
        queue: ProactiveTaskQueue | None = None,
        *,
        min_interval_seconds: float = 0.0,
        allowed_sources: frozenset[str] | set[str] | None = None,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        source_tokens: dict[str, str] | None = None,
    ) -> None:
        # 用 is None 判定而非 `queue or ...`: 空队列 __len__==0 为 falsy, or 会误建新队列。
        self.queue = queue if queue is not None else ProactiveTaskQueue()
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self.allowed_sources: frozenset[str] = (
            frozenset(allowed_sources) if allowed_sources is not None else DEFAULT_ALLOWED_SOURCES
        )
        self.poll_interval_seconds = max(0.05, float(poll_interval_seconds))
        # CR2-Fix-7: source → 期望 caller_token 的映射。未配置的 source 不参与
        # token 校验 (保持纯字符串白名单的向后兼容行为)。
        self.source_tokens: dict[str, str] = dict(source_tokens) if source_tokens else {}
        # CR2-Fix-6: 按 session_id 隔离冷却状态 (曾是调度器级单一时间戳, 会让
        # 一个高频会话占用整个 Agent 唯一的冷却窗口, 饿死其他会话的合法提醒)。
        # 未传 session_id 时用 "" 作为 key, 等价于旧的单一冷却状态 (向后兼容)。
        self._last_fired_at: dict[str, float] = {}
        self._loop_task: asyncio.Task[None] | None = None
        self._wake_callback: WakeCallback | None = None

    def may_fire(self, now: float, session_id: str = "") -> bool:
        """是否已过冷却窗口、允许再触发一个主动任务。

        L3: min_interval_seconds<=0 恒 True; 否则按该 session 的
        _last_fired_at + min_interval 判定, 不同 session 互不影响。
        effective_frequency (存在感/关系/专注度) 留后续节点接入。
        """
        if self.min_interval_seconds <= 0.0:
            return True
        last_fired = self._last_fired_at.get(session_id, 0.0)
        return (now - last_fired) >= self.min_interval_seconds

    def authorize(self, task: ProactiveTask) -> bool:
        """校验主动任务来源合法 (禁止无来源随机发言)。

        L3: source 在 allowed_sources 中 + source/intent/reason 非空。
        CR2-Fix-7: source_tokens 里配置了该 source 的期望 token 时, 还必须
        task.caller_token 恒定时间比较匹配 —— 单纯字符串白名单不能证明调用方
        真的是它声称的来源, 任何能构造 ProactiveTask(source=...) 的代码都能
        通过纯白名单检查。未配置 token 的 source 保持原白名单行为 (向后兼容)。
        """
        if not (task.source and task.intent and task.reason):
            return False
        if task.source not in self.allowed_sources:
            return False
        expected_token = self.source_tokens.get(task.source)
        if expected_token is not None and not hmac.compare_digest(task.caller_token, expected_token):
            return False
        return True

    def to_forced_turn(self, task: ProactiveTask, *, now: float | None = None) -> ForcedTurnState:
        """把一个主动任务转成强制话轮状态 (供 ConversationRuntime 发起)。

        L3: 触发时按 task.session_id 更新 _last_fired_at (供下次 may_fire 判定)。
        now 参数便于测试。
        """
        import time as _time

        fired_at = now if now is not None else _time.time()
        self._last_fired_at[task.session_id] = fired_at
        return ForcedTurnState(
            source=TriggerSource.PROACTIVE.value,
            reason=task.reason,
            created_at=fired_at,
        )

    async def start(self, wake_callback: WakeCallback | None = None) -> None:
        """启动后台调度循环 (poll → authorize → may_fire → wake_callback)。

        重复 start 不重启 (保留首个循环); wake_callback 可后续替换。
        """
        if self._loop_task is not None and not self._loop_task.done():
            self._wake_callback = wake_callback or self._wake_callback
            return
        self._wake_callback = wake_callback
        self._loop_task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """取消后台调度循环 (重复 stop 安全)。"""
        if self._loop_task is None:
            return
        self._loop_task.cancel()
        try:
            await self._loop_task
        except asyncio.CancelledError:
            pass
        self._loop_task = None

    async def _loop(self) -> None:
        """后台调度循环: poll_interval_seconds 周期 poll queue。

        未通过 authorize 的任务被丢弃 (不阻塞队列, 不调 wake_callback);
        may_fire=False 时任务退回队列头部, 等下次轮询。
        """
        try:
            while True:
                await asyncio.sleep(self.poll_interval_seconds)
                task = self.queue.poll()
                if task is None:
                    continue
                if not self.authorize(task):
                    logger.info("主动任务鉴权失败, 已丢弃", task_id=task.task_id, source=task.source)
                    continue
                import time as _time

                if not self.may_fire(_time.time(), session_id=task.session_id):
                    # 冷却中: 任务退回队列头部, 等下次轮询 (保持 FIFO 顺序, 优先级不变)。
                    self.queue._queue.insert(0, task)  # noqa: SLF001
                    continue
                # 触发: 转 forced turn + 唤醒 callback
                self.to_forced_turn(task)
                if self._wake_callback is not None:
                    try:
                        await self._wake_callback(task)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("主动任务唤醒回调失败, 已吞掉", task_id=task.task_id, error=str(exc))
        except asyncio.CancelledError:
            logger.debug("主动调度循环已取消", queue_len=len(self.queue))
            raise
