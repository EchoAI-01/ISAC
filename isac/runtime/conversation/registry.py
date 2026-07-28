"""ConversationRuntimeRegistry: 按 (agent_id, session_id) 管理运行时实例。

复刻 GatingSystem 的 per-session dict 惰性创建模式 (gating/system.py) 与
manager.py 的 FIFO 上限思路 (MAX_PROGRESS_REPORTERS_PER_AGENT),防止长期运行时
实例无界增长。每个 Agent 持有一个独立 registry (会话间隔离)。
"""

from __future__ import annotations

from isac.runtime.conversation.models import ConversationState
from isac.runtime.conversation.runtime import ConversationRuntime
from isac.utils.logger import get_logger

logger = get_logger(__name__)

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
        """惰性取回 / 创建某会话的运行时;超上限时淘汰一个旧会话。"""
        key = (agent_id, session_id)
        runtime = self._runtimes.get(key)
        if runtime is None:
            if len(self._runtimes) >= self._max:
                self._evict_one()
            runtime = ConversationRuntime(
                agent_id, session_id, max_interrupts_per_turn=self._max_interrupts_per_turn
            )
            self._runtimes[key] = runtime
        return runtime

    def _evict_one(self) -> None:
        """淘汰一个会话腾位置 (FIFO,但避开正在 WAITING 的会话)。

        Fix-32: 原逻辑无条件淘汰插入顺序最旧的 key。若那个会话恰好处于 WAITING
        (wait 工具调用正进行中), 其等待本身不会真正挂起 (内部超时定时器仍持有
        该 ConversationRuntime 引用, 到期会自行 resolve), 但淘汰会把
        message_cache/interrupt_state 等其余会话状态一并静默清空——相当于一个
        正在进行中的会话被腰斩, 下次 registry.get() 拿到的是全新空状态。
        改为优先淘汰最旧的**非 WAITING** 会话; 仅当全部会话都在等待中时才退回
        淘汰最旧者 (软上限本身不能被突破, 否则失去防无界增长的意义)。
        """
        for key, runtime in self._runtimes.items():
            if runtime.state is not ConversationState.WAITING:
                del self._runtimes[key]
                return
        oldest_key = next(iter(self._runtimes))
        logger.warning(
            "会话运行时已达上限且全部处于等待中, 仍淘汰最旧者 (软上限保护优先于等待保护)",
            evicted_agent_id=oldest_key[0],
            evicted_session_id=oldest_key[1],
            capacity=self._max,
        )
        del self._runtimes[oldest_key]

    def discard(self, agent_id: str, session_id: str) -> None:
        """移除某会话的运行时 (会话结束回收)。"""
        self._runtimes.pop((agent_id, session_id), None)

    def active_runtimes(self) -> list[tuple[str, ConversationRuntime]]:
        """返回 (session_id, runtime) 列表 (供主动任务生产者按会话活跃度枚举)。

        本 registry 是单个 Agent 私有的, 所有 key 的 agent_id 相同, 故只回 session_id。
        返回快照 list 而非视图, 避免调用方在迭代期间触发惰性创建/淘汰导致 RuntimeError。
        """
        return [(session_id, runtime) for (_agent_id, session_id), runtime in self._runtimes.items()]

    def __len__(self) -> int:
        return len(self._runtimes)
