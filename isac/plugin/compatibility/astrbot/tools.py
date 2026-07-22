"""AstrBot FunctionTool 桥接 (P0 兼容策略, ARCHITECTURE.md 3.8)。

将 AstrBot @filter.llm_tool 装饰的函数 → ISAC Tool。
AstrBot 的 FunctionTool 通常带 name/description/parameters 描述,
本桥接保留原描述, execute 时调用原函数。
"""

from __future__ import annotations

import inspect
import json
from typing import Any

from isac.agent.tools.base import Tool, ToolContext
from isac.core.types import ToolResult


class FunctionToolAdapter(Tool):
    """把 AstrBot 的 llm_tool 函数包装成 ISAC Tool。

    原 AstrBot 函数签名:
        def my_tool(ctx: ContextAdapter, args: dict) -> str: ...
    或同步/异步, 返回字符串/对象。本适配器做兼容。
    """

    def __init__(self, name: str, description: str, func: Any, parameters: dict | None = None):
        self._name = name
        self._description = description
        self._func = func
        self._parameters = parameters or _infer_parameters(func)
        self._is_async = inspect.iscoroutinefunction(func)

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict:
        return self._parameters

    async def execute(self, context: ToolContext) -> ToolResult:
        """调用原 AstrBot 函数, 把结果转成 ToolResult。

        AstrBot 调用约定: (ctx, args) 两参, ctx 是 ContextAdapter;
        ISAC 调用约定: ToolContext 含 args 与 services。
        """
        # 构造 ContextAdapter 兼容对象 (注入 services)
        from isac.plugin.compatibility.astrbot.context import ContextAdapter

        ctx = ContextAdapter(context.services)
        try:
            args_json = json.dumps(context.args, ensure_ascii=False)
            args_obj = json.loads(args_json) if args_json else {}
            if self._is_async:
                raw = await self._func(ctx, args_obj)
            else:
                raw = self._func(ctx, args_obj)
        except Exception as exc:
            return ToolResult(content=f"工具 {self._name} 执行失败: {exc}", is_error=True)
        if isinstance(raw, ToolResult):
            return raw
        text = str(raw) if raw is not None else ""
        return ToolResult(content=text)


def bridge_function_tool(name: str, description: str, func: Any, parameters: dict | None = None) -> Tool:
    """将 AstrBot FunctionTool 桥接为 ISAC Tool 实例。"""
    return FunctionToolAdapter(name, description, func, parameters=parameters)


def _infer_parameters(func: Any) -> dict:
    """从函数签名粗略推断 JSON Schema (AstrBot 插件常用方式)。

    AstrBot 的 @filter.llm_tool 装饰器通常让用户手动声明 schema;
    本函数作为兜底: 取第二个位置参数 (第一个是 ctx), 标注 dict → object schema。
    """
    signature = inspect.signature(func)
    parameters = list(signature.parameters.values())
    if len(parameters) < 2:
        return {"type": "object", "properties": {}}
    return {"type": "object", "properties": {}, "description": f"参数来自 {parameters[1].name}"}
