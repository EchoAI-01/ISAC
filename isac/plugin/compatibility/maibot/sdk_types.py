"""L2 (2026-10-13 review): maibot_sdk.types 兼容 shim。

真实 MaiBot 插件 SDK (pip 包 maibot-plugin-sdk, manifest_version 2) 的类型面:
``from maibot_sdk.types import ToolParameterInfo, ToolParamType``。本 shim 提供同形
声明, 并把参数声明映射为 ISAC Tool 的 JSON Schema (LLM function calling 面) ——
@Tool(parameters=[...]) 声明的参数在 ISAC 侧不再丢失 (空 schema = LLM 瞎猜参数)。

来源取证 (2026-10-13, docs.mai-mai.org/plugin): SDK 顶层导出
MaiBotPlugin/Tool/Command/Action/CONFIG_RELOAD_SCOPE_SELF; types 导出
ToolParameterInfo(name, param_type, description, required) 与 ToolParamType。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any


class ToolParamType(enum.StrEnum):
    """参数类型枚举 (str 枚举: 序列化/日志输出保持 SDK 字面值)。"""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    FLOAT = "float"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"
    ANY = "any"


@dataclass
class ToolParameterInfo:
    """单个工具参数声明 (与 maibot-plugin-sdk 同形)。"""

    name: str
    param_type: ToolParamType | str = ToolParamType.STRING
    description: str = ""
    required: bool = False


# ToolParamType → JSON Schema type 的映射 (宽松: 未知值退化为 string)。
_JSON_SCHEMA_TYPE: dict[str, str] = {
    ToolParamType.STRING.value: "string",
    ToolParamType.INTEGER.value: "integer",
    ToolParamType.NUMBER.value: "number",
    ToolParamType.FLOAT.value: "number",
    ToolParamType.BOOLEAN.value: "boolean",
    ToolParamType.ARRAY.value: "array",
    ToolParamType.OBJECT.value: "object",
    ToolParamType.ANY.value: "string",
}


def tool_parameters_to_schema(parameters: list[Any] | None) -> dict[str, Any]:
    """[ToolParameterInfo] → ISAC Tool parameters JSON Schema。

    非法/空声明退化为空对象 schema (与既有 MaiBotActionAdapter 默认一致)。
    """
    properties: dict[str, Any] = {}
    required: list[str] = []
    for p in parameters or []:
        name = str(getattr(p, "name", "") or "").strip()
        if not name:
            continue
        raw_type = getattr(p, "param_type", ToolParamType.STRING)
        # str 枚举: 兼容直接传字符串 ("string") 与枚举成员两种写法。
        type_value = getattr(raw_type, "value", raw_type)
        properties[name] = {
            "type": _JSON_SCHEMA_TYPE.get(str(type_value), "string"),
            "description": str(getattr(p, "description", "") or ""),
        }
        if bool(getattr(p, "required", False)):
            required.append(name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema
