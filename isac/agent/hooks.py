"""AgentHooks: Agent Loop 内部钩子注册表 (ARCHITECTURE.md 3.5)。

Hook 开发规范 (DEVELOP.md 4.2):
- 每个 Hook 必须有明确的 priority，同优先级按注册顺序执行
- Hook 中禁止直接调用 LLM (避免无限递归)
- Hook 执行失败必须不影响主流程 (try-except 包裹)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from isac.core.events import AgentHookPoint
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class AgentHooks:
    """钩子注册表。"""

    def __init__(self) -> None:
        self._hooks: dict[AgentHookPoint, list[tuple[int, int, Callable]]] = {}
        self._seq = 0  # 同优先级按注册顺序执行

    def register(self, point: AgentHookPoint, fn: Callable, priority: int = 0) -> None:
        """注册钩子。priority 越大越先执行。"""
        self._hooks.setdefault(point, []).append((priority, self._seq, fn))
        self._seq += 1

    async def fire(self, point: AgentHookPoint, *args: Any, **kwargs: Any) -> list[Any]:
        """按优先级执行钩子，返回各钩子结果列表 (异常钩子返回 None 并跳过)。"""
        hooks = sorted(self._hooks.get(point, []), key=lambda t: (-t[0], t[1]))
        results: list[Any] = []
        for _, _, fn in hooks:
            try:
                results.append(await fn(*args, **kwargs))
            except Exception as exc:
                logger.error("Agent Hook 执行失败，已跳过", point=point.value, error=str(exc), exc_info=True)
                results.append(None)
        return results
