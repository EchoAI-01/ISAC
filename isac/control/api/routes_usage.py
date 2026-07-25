"""模型用量查询端点 (SPECIFICATION.md 2.3 / CONTROL_PLANE_SPEC.md 3.5)。

只读; 认证沿用与其余控制面路由相同的扁平 Bearer Token (auth_dependency)。
CONTROL_PLANE_SPEC.md §6.1 描述了 usage:read/usage:detail 两档 scope, 但控制面
目前没有任何路由实现过按 scope 校验 (全部是单 Token 全权限) —— 细粒度 scope 是
控制面整体的未来工作, 不在本路由单独引入, 避免只有 usage 这一个资源的鉴权模式
与其它资源不一致。计量关闭时 create_control_app() 不挂载本路由 (见 server.py),
不会对外暴露一个看起来有效但永远空的接口。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.observability.usage.storage import UsageStore


def build_router(usage_store: UsageStore, auth_dependency: Any = None) -> Any:
    from fastapi import APIRouter, Depends, Query

    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(prefix="/usage/models", tags=["usage"], dependencies=deps)

    @router.get("/summary")
    async def summary(
        from_: int | None = Query(default=None, alias="from"),
        to: int | None = None,
        provider: str | None = None,
        model: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        modality: str | None = None,
        status: str | None = None,
        group_by: str | None = None,
    ) -> list[dict]:
        filters = _build_filters(
            from_ts=from_,
            to_ts=to,
            provider=provider,
            model=model,
            agent_id=agent_id,
            session_id=session_id,
            modality=modality,
            status=status,
            group_by=group_by,
        )
        return await usage_store.aggregate(filters)

    @router.get("/events")
    async def events(
        from_: int | None = Query(default=None, alias="from"),
        to: int | None = None,
        provider: str | None = None,
        model: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        modality: str | None = None,
        status: str | None = None,
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> list[dict]:
        filters = _build_filters(
            from_ts=from_,
            to_ts=to,
            provider=provider,
            model=model,
            agent_id=agent_id,
            session_id=session_id,
            modality=modality,
            status=status,
        )
        return await usage_store.list_events(filters, limit=limit, offset=offset)

    @router.get("/timeseries")
    async def timeseries(
        from_: int | None = Query(default=None, alias="from"),
        to: int | None = None,
        provider: str | None = None,
        model: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        modality: str | None = None,
        status: str | None = None,
        group_by: str | None = None,
        bucket: str = "hour",
    ) -> list[dict]:
        extra_groups = [g.strip() for g in (group_by or "").split(",") if g.strip()]
        combined_groups = list(dict.fromkeys(["time_bucket", *extra_groups]))
        filters = _build_filters(
            from_ts=from_,
            to_ts=to,
            provider=provider,
            model=model,
            agent_id=agent_id,
            session_id=session_id,
            modality=modality,
            status=status,
            group_by=",".join(combined_groups),
        )
        filters["bucket"] = bucket
        return await usage_store.aggregate(filters)

    return router


def _build_filters(*, group_by: str | None = None, **fields: Any) -> dict[str, Any]:
    """把 REST 查询参数收敛成 UsageStore.aggregate/list_events 期望的 filters dict;
    None 值 (未传参数) 直接丢弃, group_by 逗号拆分成 list。"""
    filters = {key: value for key, value in fields.items() if value is not None}
    if group_by:
        filters["group_by"] = [g.strip() for g in group_by.split(",") if g.strip()]
    return filters
