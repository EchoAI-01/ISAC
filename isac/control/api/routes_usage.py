"""模型用量查询端点 (SPECIFICATION.md 2.3 / CONTROL_PLANE_SPEC.md 3.5)。

认证沿用与其余控制面路由相同的扁平 Bearer Token (auth_dependency)。Fix-12:
CONTROL_PLANE_SPEC.md §6.1 描述的 usage:read/usage:detail 两档 scope 现已接入
(scope_dependency 由 server.py 按 control.tokens[] 配置构造; 未配置时为 None,
scope 校验整体跳过, 行为与之前完全一致)。聚合数据 (/summary、/timeseries) 需要
usage:read; 逐条物理请求明细 (/events) 需要更高权限的 usage:detail。计量关闭时
create_control_app() 不挂载本路由 (见 server.py), 不会对外暴露一个看起来有效
但永远空的接口。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from isac.observability.usage.storage import UsageStore


def build_router(usage_store: UsageStore, auth_dependency: Any = None, scope_dependency: Any = None) -> Any:
    from fastapi import APIRouter, Depends, Query

    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(prefix="/usage/models", tags=["usage"], dependencies=deps)
    read_deps = [Depends(scope_dependency("usage:read"))] if scope_dependency else []
    detail_deps = [Depends(scope_dependency("usage:detail"))] if scope_dependency else []

    @router.get("/summary", dependencies=read_deps)
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

    @router.get("/events", dependencies=detail_deps)
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

    @router.get("/timeseries", dependencies=read_deps)
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
