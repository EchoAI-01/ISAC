"""ConversationRuntimeRegistry: 按 (agent_id, session_id) 管理运行时实例。

复刻 GatingSystem 的 per-session dict 惰性创建模式 (gating/system.py) 与
manager.py 的 FIFO 上限思路 (MAX_PROGRESS_REPORTERS_PER_AGENT),防止长期运行时
实例无界增长。每个 Agent 持有一个独立 registry (会话间隔离)。
"""

from __future__ import annotations

from isac.runtime.conversation.runtime import ConversationRuntime

# per-Agent 的会话运行时软上限;超出时淘汰最旧插入的会话 (FIFO)。
MAX_RUNTIMES_PER_AGENT = 1000


class ConversationRuntimeRegistry:
    """会话运行时注册表 (每 Agent 一个,内部按 session 隔离)。"""

    def __init__(
        self, max_runtimes: int = MAX_RUNTIMES_PER_AGENT, *, max_interrupts_per_turn: int = 1
    ) -> None:
        self._runtimes: dict[tuple[str, str], ConversationRuntime] = {}
        self._max = max_runtimes
        # P1(L4): 新建 runtime 时透传单轮打断上限 (conversation.max_interrupts_per_turn)
        self._max_interrupts_per_turn = max(1, int(max_interrupts_per_turn))

    def get(self, agent_id: str, session_id: str) -> ConversationRuntime:
        """惰性取回 / 创建某会话的运行时;超上限时淘汰最旧插入者。"""
        key = (agent_id, session_id)
        runtime = self._runtimes.get(key)
        if runtime is None:
            if len(self._runtimes) >= self._max:
                oldest_key = next(iter(self._runtimes))
                del self._runtimes[oldest_key]
            runtime = ConversationRuntime(
                agent_id, session_id, max_interrupts_per_turn=self._max_interrupts_per_turn
            )
            self._runtimes[key] = runtime
        return runtime

    def discard(self, agent_id: str, session_id: str) -> None:
        """移除某会话的运行时 (会话结束回收)。"""
        self._runtimes.pop((agent_id, session_id), None)

    def __len__(self) -> int:
        return len(self._runtimes)
