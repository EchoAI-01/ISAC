"""J3 配置编辑事务 Control API 路由 (CONTROL_PLANE_SPEC.md)。

端点:
- POST /config/validate        Schema 校验 AgentConfig 字段 (不持久化)
- POST /config/diff            两份 AgentConfig 的字段级 diff 预览 (不持久化)
- GET  /config/global          N1e: 全局配置 (敏感键脱敏) + override revision
- PATCH /config/global         N1e: 全局配置部分更新 → 校验 → 持久化 override → 热重载
- POST /config/global/reload   N1e: 从磁盘重读 (config.jsonc + override) 并热应用

J3-2 配置编辑事务: Schema 校验 + Diff 预览 + If-Match + 409 CONFIG_CONFLICT,
防止多人同时编辑覆盖。Bearer Token 认证。

N1e 全局配置持久化 + 热重载 (第三轮审查留档项):
- data/config.jsonc 带注释, 整体回写会丢注释, 故控制面写入独立 override 文件
  (data/config.override.json, 机器所有, 原子写); 加载序: 默认 ← config.jsonc ←
  override ← 环境变量 (见 isac/utils/config.py)。
- PATCH 语义: 深合并部分更新; 叶值 null = 撤销该覆盖项 (回落到 config.jsonc/默认);
  GET 回传的脱敏哨兵 = 未修改, 剥离不落盘 (绝不把哨兵/解析后明文写回磁盘)。
- 热重载: 原地更新 services 持有的 global_config dict + 同步重建运行中 Agent;
  control/channels/logging 各节在 bootstrap 构造服务端点, 运行中不可重建 →
  持久化但列入 restart_required (CONTROL_PLANE_SPEC §8.2 规则 6, 不假装热更成功)。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

# N1e: 热重载边界。这些节在 bootstrap 阶段构造服务端点 (uvicorn 绑定 host/port、
# 通道适配器 start_all、setup_logger 一次性配置), 运行中原地重建不安全或不可行,
# 只能持久化后下次重启生效; 其余各节经 _hot_apply_global_config 热生效。
RESTART_REQUIRED_SECTIONS = frozenset({"control", "channels", "logging", "debug", "log_level"})


def build_router(
    auth_dependency: Any = None,
    agent_manager: Any = None,
    global_config: dict[str, Any] | None = None,
    config_path: str | Path | None = None,
    override_path: str | Path | None = None,
    audit_log: Any = None,
    scope_dependency: Any = None,
) -> Any:
    """构造 Config Control API 路由 (validate / diff / global)。

    N1e: agent_manager/global_config/config_path/override_path 任一缺失时仅挂载
    validate/diff (保持引入本特性前的行为, 测试桩与最小部署不受影响)。override_path
    必备是因为 PATCH 必须可持久化 —— 无落盘路径的"纯内存修改"重启即丢, 违反
    §8.2 "持久化 + reload/restart plan" 语义, 宁可不挂载。
    """
    from fastapi import APIRouter, Depends, Header, HTTPException

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

    if (
        agent_manager is None or global_config is None
        or config_path is None or override_path is None
    ):
        return router

    # N1e 依赖齐备: 挂载全局配置端点。read_deps/write_deps 与 routes_agents 同构
    # (Fix-12: 未配置 tokens[] 时 scope_dependency=None, 仅基线认证)。
    read_deps = [Depends(scope_dependency("config:read"))] if scope_dependency else []
    write_deps = [Depends(scope_dependency("config:write"))] if scope_dependency else []
    resolved_override = Path(override_path)
    # 全局配置单对象, 一把锁串行 PATCH/reload 即可 (J3-2 per-agent 锁的同构简化):
    # 包住"读 override → 校验 If-Match → 校验候选 → 持久化 → 热应用"整段,
    # 并发 PATCH 不会用过期基线互相覆盖。
    config_lock = asyncio.Lock()

    @router.get("/config/global", dependencies=read_deps)
    async def get_global_config() -> dict:
        """N1e: 回显有效全局配置 (敏感键脱敏为哨兵) + override revision。

        脱敏口径与 GET /agents/{id}/config 一致 (Fix-91): api_key/token/secret/
        password 类键替换为哨兵, 永不回显明文 (CONTROL_PLANE_SPEC §8.2 规则 4)。
        """
        from isac.control.api.routes_agents import _redact_sensitive
        from isac.utils.config import load_config_overrides

        try:
            _, revision = load_config_overrides(resolved_override)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_CONFIG", "message": str(exc)},
            ) from exc
        return {"config": _redact_sensitive(global_config), "revision": revision}

    @router.patch("/config/global", dependencies=write_deps)
    async def patch_global_config(
        payload: dict,
        if_match: str | None = None,
        if_match_header: str | None = Header(default=None, alias="If-Match"),
    ) -> dict:
        """N1e: 全局配置部分更新 (深合并) → 校验 → 持久化 override → 热重载。

        - If-Match (Header 优先, 回退 query; Fix-11 同构): 与当前 override revision
          不符 → 409 CONFIG_CONFLICT, 不静默覆盖。
        - 候选配置经 load_config 全链校验 (schema 硬失败 → 400, 不落盘)。
        - 热应用结果按 §8.2 规则 6 区分 applied / reload_required / restart_required。
        """
        return await _do_patch_global_config(
            agent_manager, global_config, Path(config_path), resolved_override,
            payload, if_match_header if if_match_header is not None else if_match,
            audit_log, config_lock,
        )

    @router.post("/config/global/reload", dependencies=write_deps)
    async def reload_global_config() -> dict:
        """N1e: 从磁盘重读 config.jsonc + override 并热应用 (不写盘)。

        供手工编辑 config.jsonc 后免重启生效 (等价于"重启加载"但只重建可热更部分)。
        """
        from isac.utils.config import load_config

        async with config_lock:
            try:
                candidate = load_config(config_path, override_path=resolved_override)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "INVALID_CONFIG", "message": str(exc)},
                ) from exc
            candidate = await _resolve_candidate_secrets(candidate)
            applied = await _hot_apply_global_config(agent_manager, global_config, candidate)
            await _audit_global(audit_log, "POST", "/api/v1/config/global/reload",
                                "reload_global_config", applied)
            return applied

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


# ── N1e: 全局配置持久化 + 热重载实现 ─────────────────────────────


def _strip_redacted(patch: Any) -> Any:
    """剥离客户端回传的脱敏哨兵 (GET 拿脱敏值 → 原样回传 = 未修改, 不落盘)。

    哨兵绝不能写进 override 文件: 既不是有效配置值, 也会让后续加载把哨兵当成
    真实凭据透传给 Provider/MCPClient。dict 内哨兵叶删除; 列表内裸哨兵过滤;
    剥完哨兵后变空的 dict 一并剪掉 —— 空 dict 深合并本就是 no-op, 留下会让
    "整段全是哨兵"的 patch 绕过"无有效变更"检查静默落盘一次空转 revision。
    """
    from isac.control.api.routes_agents import REDACTED_SENTINEL

    if isinstance(patch, dict):
        out: dict[Any, Any] = {}
        for key, value in patch.items():
            if value == REDACTED_SENTINEL:
                continue
            cleaned = _strip_redacted(value)
            if isinstance(cleaned, dict) and not cleaned:
                continue
            out[key] = cleaned
        return out
    if isinstance(patch, list):
        return [_strip_redacted(item) for item in patch if item != REDACTED_SENTINEL]
    return patch


async def _resolve_candidate_secrets(candidate: dict[str, Any]) -> dict[str, Any]:
    """候选配置落盘前经 SecretStore 解析 secret: 前缀 (与 bootstrap 同口径)。

    override 文件保存的是用户写的原值 (如 secret:xxx), 解析只发生在内存候选上;
    ISAC_SECRET_KEY 未配置时 _build_secret_store 返回 None, secret: 值原样保留
    (与启动路径一致的降级)。
    """
    from isac.utils.security import resolve_secrets_in_config
    from isac.wiring import _build_secret_store

    await resolve_secrets_in_config(candidate, _build_secret_store())
    return candidate


async def _hot_apply_global_config(
    agent_manager: Any,
    config: dict[str, Any],
    new_effective: dict[str, Any],
) -> dict[str, Any]:
    """原地更新 global_config dict + 同步重建运行中 Agent, 返回应用结果。

    §8.2 规则 6: applied/reload_required/restart_required 严格区分 ——
    - applied: 已热生效的顶层节 (原地更新 + 运行中 Agent 重建完成);
    - reload_required: 恒空 (Agent 重建在本请求内同步做完, 不留待办);
    - restart_required: control/channels/logging 等运行中不可重建的节。
    单个 Agent 重建失败不阻断其余: 失败收集进 reload_errors (通用消息, 明细落日志)。
    """
    from isac.utils.logger import get_logger

    logger = get_logger(__name__)
    changed = sorted(
        k for k in set(config) | set(new_effective) if config.get(k) != new_effective.get(k)
    )
    restart_required = [k for k in changed if k in RESTART_REQUIRED_SECTIONS]
    applied = [k for k in changed if k not in RESTART_REQUIRED_SECTIONS]

    # 原地更新: services 里所有持有者引用同一 dict 对象, clear+update 让全部
    # 在途组件立即看到新值 (换绑新 dict 会让旧引用停在旧配置上)。
    config.clear()
    config.update(new_effective)

    reloaded: list[str] = []
    reload_errors: dict[str, str] = {}
    if applied:
        for instance in await agent_manager.list():
            if getattr(instance, "status", "") != "running":
                continue
            agent_id = getattr(getattr(instance, "config", None), "agent_id", "") or str(instance)
            try:
                await agent_manager.reload_config(agent_id, instance.config)
                reloaded.append(agent_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("全局配置热重载: Agent 重建失败, 保留旧实例",
                               agent_id=agent_id, error=str(exc), exc_info=True)
                reload_errors[agent_id] = "reload failed; previous instance kept"
    return {
        "applied": applied,
        "reload_required": [],
        "restart_required": restart_required,
        "reloaded_agents": reloaded,
        "reload_errors": reload_errors,
    }


async def _do_patch_global_config(
    agent_manager: Any,
    global_config: dict[str, Any],
    config_path: Path,
    override_path: Path,
    payload: dict[str, Any],
    if_match: str | None,
    audit_log: Any,
    config_lock: asyncio.Lock,
) -> dict[str, Any]:
    """PATCH /config/global 实现 (抽出降 build_router 圈复杂度, 同 _do_patch_agent)。"""
    from fastapi import HTTPException

    from isac.utils.config import deep_merge_config, load_config, load_config_overrides, save_config_overrides

    async with config_lock:
        try:
            current_overrides, revision = load_config_overrides(override_path)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_CONFIG", "message": str(exc)},
            ) from exc
        # 乐观锁 (J3-2 同构): If-Match 与当前 override revision 不符 → 409。
        if if_match is not None:
            try:
                expected = int(if_match)
            except (ValueError, TypeError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "INVALID_IF_MATCH",
                            "message": f"If-Match must be int, got: {if_match}"},
                ) from exc
            if expected != revision:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "CONFIG_CONFLICT",
                            "message": f"revision mismatch: expected {expected}, current {revision}",
                            "current_revision": revision},
                )
        patch = _strip_redacted(payload)
        if not patch:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_INPUT", "message": "no effective changes"},
            )
        # 先校验后落盘: 候选 = config.jsonc + 合并后 override 全链 load (schema 硬失败
        # 抛 ConfigValidationError/ValueError → 400, override 文件保持原样)。
        candidate_overrides = deep_merge_config(current_overrides, patch)
        try:
            candidate = load_config(config_path, overrides=candidate_overrides)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_CONFIG", "message": str(exc)},
            ) from exc
        new_revision = save_config_overrides(override_path, patch)
        candidate = await _resolve_candidate_secrets(candidate)
        applied = await _hot_apply_global_config(agent_manager, global_config, candidate)
        # 审计只记变更的顶层节名, 绝不记值 (值可能含凭据)。
        await _audit_global(audit_log, "PATCH", "/api/v1/config/global",
                            "patch_global_config", applied)
        return {**applied, "revision": new_revision}


async def _audit_global(
    audit_log: Any, method: str, path: str, action: str, applied: dict[str, Any]
) -> None:
    """全局配置写操作审计 (audit_log 为 None 跳过; detail 只含节名不含值)。"""
    if audit_log is None:
        return
    detail = (
        f"applied={','.join(applied.get('applied', [])) or '-'} "
        f"restart_required={','.join(applied.get('restart_required', [])) or '-'}"
    )
    await audit_log.record(
        actor="authenticated", method=method, path=path, action=action,
        target="global_config", detail=detail, status_code=200,
    )
