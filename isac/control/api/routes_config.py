"""J3 配置编辑事务 Control API 路由 (CONTROL_PLANE_SPEC.md)。

端点:
- POST /config/validate  Schema 校验 AgentConfig 字段 (不持久化)
- POST /config/diff       两份 AgentConfig 的字段级 diff 预览 (不持久化)
- PATCH /agents/{id}      部分更新 AgentConfig (支持 If-Match revision 乐观锁)

J3-2 配置编辑事务: Schema 校验 + Diff 预览 + If-Match + 409 CONFIG_CONFLICT,
防止多人同时编辑覆盖。Bearer Token 认证。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


def build_router(
    auth_dependency: Any = None,
) -> Any:
    """构造 Config Control API 路由 (validate / diff)。"""
    from fastapi import APIRouter, Depends, HTTPException

    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(tags=["config"], dependencies=deps)

    @router.post("/config/validate")
    async def validate_config(payload: dict) -> dict:
        """Schema 校验 AgentConfig 字段; 不持久化, 只返回 valid + errors。"""
        errors = _validate_agent_config_fields(payload)
        return {"valid": len(errors) == 0, "errors": errors}

    @router.post("/config/diff")
    async def diff_configs(payload: dict) -> dict:
        """两份 AgentConfig 的字段级 diff; 不持久化, 只返回 changes。"""
        before = payload.get("before")
        after = payload.get("after")
        if before is None or after is None:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_INPUT", "message": "before and after required"},
            )
        changes = _compute_diff(before, after)
        return {"changes": changes}

    return router


def _validate_agent_config_fields(payload: dict) -> list[str]:
    """校验 AgentConfig 字段; 返回错误列表 (空列表表示通过)。"""
    errors: list[str] = []
    from isac.runtime.config import AGENT_ID_PATTERN

    agent_id = str(payload.get("agent_id", "") or "").strip()
    if not agent_id:
        errors.append("agent_id is required")
    elif not AGENT_ID_PATTERN.match(agent_id):
        errors.append(f"agent_id illegal: {agent_id!r} (only [A-Za-z0-9_-], 1-64 chars)")

    enabled = payload.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        errors.append("enabled must be bool")

    trigger_words = payload.get("trigger_words")
    if trigger_words is not None and not isinstance(trigger_words, list):
        errors.append("trigger_words must be list")

    plugins_allow = payload.get("plugins_allow")
    if plugins_allow is not None and not isinstance(plugins_allow, list):
        errors.append("plugins_allow must be list")

    revision = payload.get("revision")
    if revision is not None and not isinstance(revision, int):
        errors.append("revision must be int")

    return errors


def _compute_diff(before: dict, after: dict) -> list[dict]:
    """计算两份 AgentConfig 的字段级 diff; 返回 [{field, before, after}, ...]。"""
    all_fields = set(before.keys()) | set(after.keys())
    changes: list[dict] = []
    for field in sorted(all_fields):
        b = before.get(field)
        a = after.get(field)
        if b != a:
            changes.append({"field": field, "before": b, "after": a})
    return changes
