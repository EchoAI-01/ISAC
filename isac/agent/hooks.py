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
        # N5b 批次C C2: 与 _hooks[point] 同索引的来源列表, 供按来源 deregister。
        self._hook_sources: dict[AgentHookPoint, list[str]] = {}
        # on_load 期间设置的默认来源 (激活模块 set_current_source(plugin_name))。
        self._current_source: str | None = None
        self._seq = 0  # 同优先级按注册顺序执行

    def register(self, point: AgentHookPoint, fn: Callable, priority: int = 0, *, source: str | None = None) -> None:
        """注册钩子。priority 越大越先执行。"""
        self._hooks.setdefault(point, []).append((priority, self._seq, fn))
        self._hook_sources.setdefault(point, []).append(source or self._current_source or "builtin")
        self._seq += 1

    def set_current_source(self, source: str | None) -> None:
        """设置后续 register() 的默认来源 (on_load 期间设为插件名, 结束后置 None)。"""
        self._current_source = source

    def deregister_by_source(self, source: str) -> int:
        """移除指定来源的全部钩子 (各 point), 返回被移除数量 (C2 热重载同步)。"""
        removed = 0
        for point in list(self._hooks.keys()):
            hooks = self._hooks[point]
            srcs = self._hook_sources.get(point, [])
            keep = [(h, s) for h, s in zip(hooks, srcs) if s != source]
            removed += len(hooks) - len(keep)
            self._hooks[point] = [h for h, _ in keep]
            self._hook_sources[point] = [s for _, s in keep]
        return removed

    def _sorted_hooks(self, point: AgentHookPoint) -> list[tuple[int, int, Callable]]:
        """返回按优先级排序后的钩子列表。"""
        return sorted(self._hooks.get(point, []), key=lambda t: (-t[0], t[1]))

    def get_hooks(self, point: AgentHookPoint) -> list[Callable]:
        """返回按优先级排序后的钩子函数列表（供调用方自行控制参数传递）。"""
        return [fn for _, _, fn in self._sorted_hooks(point)]

    async def fire(self, point: AgentHookPoint, *args: Any, **kwargs: Any) -> list[Any]:
        """按优先级执行钩子，返回各钩子结果列表 (异常钩子返回 None 并跳过)。"""
        results: list[Any] = []
        for _, _, fn in self._sorted_hooks(point):
            try:
                results.append(await fn(*args, **kwargs))
            except Exception as exc:
                logger.error("Agent Hook 执行失败，已跳过", point=point.value, error=str(exc), exc_info=True)
                results.append(None)
        return results
