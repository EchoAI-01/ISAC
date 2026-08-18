"""MaiBot Action 映射 (ARCHITECTURE.md 3.8 兼容表)。

将 MaiBot Action (动作) 桥接为 ISAC Tool。MaiBot Action 签名:
    async def my_action(self, args: dict) -> str: ...
ISAC Tool 调用约定: ToolContext 含 args 与 services。
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult

# Fix-129: host 插件 Action 执行超时默认值 (秒) —— 与 astrbot/tools.py 同口径。
DEFAULT_HOST_TOOL_TIMEOUT_SECONDS = 60.0


class MaiBotActionAdapter(Tool):
    """MaiBot Action → ISAC Tool 桥接器。"""

    def __init__(
        self, name: str, description: str, func: Any,
        timeout_seconds: float = DEFAULT_HOST_TOOL_TIMEOUT_SECONDS,
    ):
        self._name = name
        self._description = description
        self._func = func
        self._is_async = inspect.iscoroutinefunction(func)
        # Fix-129: 执行超时可注入 (非正值回落默认)。
        self._timeout = max(0.01, float(timeout_seconds))

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, context: ToolContext) -> ToolResult:
        """调用原 Action (bound method 时自动传 self)。

        Fix-129: 执行受 timeout 约束 —— 异步直接 wait_for; 同步经 to_thread 移出事件
        循环再限时, 挂死的 Action 不再无限阻塞 Agent Loop。
        """
        try:
            args_obj = dict(context.args) if context.args else {}
            if self._is_async:
                pending = self._func(args_obj)
            else:
                pending = asyncio.to_thread(self._func, args_obj)
            raw = await asyncio.wait_for(pending, timeout=self._timeout)
        except TimeoutError:
            return ToolResult(
                content=f"Action {self._name} 执行超时 (> {self._timeout}s), 已放弃等待。",
                is_error=True,
            )
        except Exception as exc:
            return ToolResult(
                content=f"Action {self._name} 执行失败: {exc}",
                is_error=True,
            )
        if isinstance(raw, ToolResult):
            return raw
        text = str(raw) if raw is not None else ""
        return ToolResult(content=text)


def bridge_action(action: Any, description: str = "", func: Any = None) -> Tool:
    """将 MaiBot Action 桥接为 ISAC Tool。

    两种用法:
    - bridge_action(name, description, func) 直接传函数
    - bridge_action(bound_method) 从装饰器标记读取 name/description
    """
    if callable(action) and func is None:
        # 直接传入函数
        func = action
        name = getattr(action, "_maibot_action", (action.__name__, ""))[0]
        desc = getattr(action, "_maibot_action", ("", ""))[1]
    elif isinstance(action, str) and func is not None:
        name = action
        desc = description
    else:
        name = str(action)
        desc = description
        if func is None:
            raise ValueError("bridge_action 需要 func 参数")
    return MaiBotActionAdapter(name, desc, func)
