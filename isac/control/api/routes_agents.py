"""Agent 管理端点 (SPECIFICATION.md 4.4)。

Bearer Token 认证 (依赖注入) + 审计日志 (写操作记录) + AgentConfig 持久化到 data/agents/<id>/config.jsonc。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.control.audit import AuditLog
    from isac.runtime.manager import AgentManager

logger = get_logger(__name__)

# Fix-91: 敏感配置键判定 + 脱敏哨兵。AgentConfig 的 llm/persona/gating/conversation
# 是自由 dict, 部署方可能把 api_key/secret/token 放进 (ProviderManager 明确消费
# llm.api_key)。GET /agents/{id}/config 若原样回显, 持窄 scope agent:read token 的
# 集成方即可读走全部 Agent 的 LLM 凭据明文。序列化前按值替换为哨兵。
_SENSITIVE_KEY_PATTERN = re.compile(
    r"(api[_-]?key|apikey|secret|token|password|passwd|credential|private[_-]?key)",
    re.IGNORECASE,
)
REDACTED_SENTINEL = "__ISAC_REDACTED__"


def _is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY_PATTERN.search(str(key or "")))


def _redact_sensitive(data: Any) -> Any:
    """深拷贝并把敏感键的值替换为哨兵 (只读回显用, 不改原对象)。"""
    if isinstance(data, dict):
        return {
            k: (REDACTED_SENTINEL if _is_sensitive_key(k) and v not in (None, "") else _redact_sensitive(v))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_redact_sensitive(item) for item in data]
    return data


def _restore_redacted(merged: Any, original: Any) -> Any:
    """PATCH 合并后, 把客户端回传的哨兵值还原为原配置的真实值。

    WebUI 编辑流程是 GET (拿到脱敏值) → 改别的字段 → PATCH 回传整个 dict; 若不做
    还原, 哨兵值会覆盖真实 api_key。规则: 敏感键上, 传回的是哨兵 → 用原值;
    传回的是新值 (客户端真要改密钥) → 保留新值。非敏感键原样保留 merged。
    列表按 merged 逐元素递归 (original 按索引对齐, 缺位传 None) —— 不能用
    zip(merged, original): 两者不等长时 (如 trigger_words 由 [] 改 ["hi"]) 会按
    短列表截断, 丢更新。
    """
    if isinstance(merged, dict):
        original_dict = original if isinstance(original, dict) else {}
        restored: dict[Any, Any] = {}
        for k, v in merged.items():
            if _is_sensitive_key(k):
                if v == REDACTED_SENTINEL:
                    restored[k] = original_dict.get(k)
                else:
                    restored[k] = v
            else:
                restored[k] = _restore_redacted(v, original_dict.get(k))
        return restored
    if isinstance(merged, list):
        original_list = original if isinstance(original, list) else []
        return [
            _restore_redacted(item, original_list[i] if i < len(original_list) else None)
            for i, item in enumerate(merged)
        ]
    return merged


def build_router(
    agent_manager: AgentManager,
    auth_dependency: Any = None,
    audit_log: AuditLog | None = None,
    agents_dir: str = "data/agents",
    scope_dependency: Any = None,
) -> Any:
    from fastapi import APIRouter, Depends, Header, HTTPException

    from isac.runtime.config import save_agent_config

    deps = [Depends(auth_dependency)] if auth_dependency else []
    router = APIRouter(prefix="/agents", tags=["agents"], dependencies=deps)
    # #29 审计 actor 归因: handler 经此依赖拿到真实调用方身份写入审计。
    # auth_dependency 为 None (无任何认证) 时回落 anonymous。
    caller_dep = Depends(auth_dependency) if auth_dependency else Depends(lambda: "anonymous")
    # Fix-12: scope_dependency 为 None (未配置 control.tokens[]) 时 read_deps/
    # write_deps 都是空列表, 只受上面的 auth_dependency 约束, 行为不变。
    read_deps = [Depends(scope_dependency("agent:read"))] if scope_dependency else []
    write_deps = [Depends(scope_dependency("agent:write"))] if scope_dependency else []
    # agents_dir 是配置传入的字符串, 统一规范化为 Path 后续拼接都用 / 操作符,
    # 避免字符串拼接绕开 AgentConfig.__post_init__ 对 agent_id 的格式校验
    # (CODE_REVIEW_REPORT.md #19)。
    agents_dir_path = Path(agents_dir)

    @router.post("", dependencies=write_deps)
    async def create_agent(config: dict, caller: str = caller_dep) -> dict:
        instance = await _do_create_agent(agent_manager, config)
        # Path / 操作符自然处理分隔符; agent_id 已由 AgentConfig 校验只含 [A-Za-z0-9_-]
        config_path = agents_dir_path / instance.agent_id / "config.jsonc"
        save_agent_config(config_path, instance.config)
        await _audit(
            audit_log, "POST", "/api/v1/agents", "create_agent", instance.agent_id,
            actor=caller,
        )
        return {"agent_id": instance.agent_id, "status": instance.status}

    @router.get("", dependencies=read_deps)
    async def list_agents() -> list[dict]:
        return [{"agent_id": a.agent_id, "status": a.status} for a in await agent_manager.list()]

    @router.get("/{agent_id}", dependencies=read_deps)
    async def get_agent(agent_id: str) -> dict:
        instance = await agent_manager.get(agent_id)
        if instance is None:
            raise HTTPException(status_code=404, detail={"code": "AGENT_NOT_FOUND", "message": agent_id})
        return {"agent_id": instance.agent_id, "status": instance.status}

    @router.get("/{agent_id}/config", dependencies=read_deps)
    async def get_agent_config(agent_id: str) -> dict:
        """R2: 返回全量 AgentConfig + 真实 revision (供 WebUI loadConfigForEdit 乐观锁)。"""
        return await _get_agent_config(agent_manager, agent_id)

    @router.post("/{agent_id}/start", dependencies=write_deps)
    async def start_agent(agent_id: str, caller: str = caller_dep) -> dict:
        await _require_agent(agent_manager, agent_id, "start")
        await _audit(
            audit_log, "POST", f"/api/v1/agents/{agent_id}/start", "start_agent",
            agent_id, actor=caller,
        )
        return {"agent_id": agent_id, "status": "running"}

    @router.post("/{agent_id}/stop", dependencies=write_deps)
    async def stop_agent(agent_id: str, caller: str = caller_dep) -> dict:
        await _require_agent(agent_manager, agent_id, "stop")
        await _audit(
            audit_log, "POST", f"/api/v1/agents/{agent_id}/stop", "stop_agent",
            agent_id, actor=caller,
        )
        return {"agent_id": agent_id, "status": "stopped"}

    @router.delete("/{agent_id}", dependencies=write_deps)
    async def destroy_agent(agent_id: str, keep_memory: bool = True, caller: str = caller_dep) -> dict:
        # N5b 批次G: DELETE 不存在 agent 经 _require_agent 统一转 404 (此前 destroy
        # 内部 _require 抛 AgentNotFoundError 未捕获 → 500 泄露内部异常)。
        await _require_agent(agent_manager, agent_id, "destroy", keep_memory=keep_memory)
        await _audit(
            audit_log, "DELETE", f"/api/v1/agents/{agent_id}", "destroy_agent",
            agent_id, detail=f"keep_memory={keep_memory}", actor=caller,
        )
        return {"agent_id": agent_id, "status": "destroyed"}

    @router.patch("/{agent_id}", dependencies=write_deps)
    async def patch_agent(
        agent_id: str,
        payload: dict,
        if_match: str | None = None,
        if_match_header: str | None = Header(default=None, alias="If-Match"),
        caller: str = caller_dep,
    ) -> dict:
        """J3-2: 部分更新 AgentConfig; 支持 If-Match revision 乐观锁。

        Fix-11: CONTROL_PLANE_SPEC.md 规定 If-Match 是 HTTP Header, 但此前只绑定
        了 query 参数, 真按规范发 Header 的客户端会被静默忽略、PATCH 无条件覆盖。
        Header 优先; 没有 Header 时回退到 query 参数 (WebUI 当前仍用 ?if_match=)。
        """
        effective_if_match = if_match_header if if_match_header is not None else if_match
        return await _do_patch_agent(
            agent_manager, agent_id, payload, effective_if_match, audit_log, agents_dir_path,
            actor=caller,
        )

    return router


async def _do_patch_agent(
    agent_manager: AgentManager,
    agent_id: str,
    payload: dict,
    if_match: str | None,
    audit_log: AuditLog | None,
    agents_dir_path: Path,
    actor: str = "authenticated",
) -> dict:
    """J3-2: PATCH /agents/{id} 实现细节 (抽出来降 build_router 圈复杂度)。

    Fix-2: 整段"读取当前配置 → 校验 If-Match → 合并 → 持久化 → reload_config"
    包在 agent_manager.acquire_config_lock(agent_id) 内, 避免同一 agent_id 的
    两个并发 PATCH 都读到同一份旧配置、后完成的一个用过期基线覆盖先完成的一个
    (即使两次请求都返回 200, 静默丢失一次更新)。
    """
    from dataclasses import asdict

    from fastapi import HTTPException

    from isac.runtime.config import AgentConfig, save_agent_config

    async with agent_manager.acquire_config_lock(agent_id):
        instance = await agent_manager.get(agent_id)
        if instance is None:
            raise HTTPException(status_code=404, detail={"code": "AGENT_NOT_FOUND", "message": agent_id})
        # 乐观锁: 校验 if_match 与当前 revision
        current_revision = getattr(instance.config, "revision", 1)
        if if_match is not None:
            try:
                expected = int(if_match)
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=400,
                    detail={"code": "INVALID_IF_MATCH", "message": f"If-Match must be int, got: {if_match}"},
                )
            if expected != current_revision:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "CONFIG_CONFLICT",
                        "message": f"revision mismatch: expected {expected}, current {current_revision}",
                        "current_revision": current_revision,
                    },
                )
        # 合并 payload 到现有 config (部分更新; agent_id/revision 不可经 payload 改)
        # Fix-66: revision 必须由服务端单调管理 —— 此前 payload 可携带 revision
        # 覆盖当前值: ① 乐观锁 ABA (攻击者把 revision 改回旧值后, 持有旧 If-Match
        # 的合法编辑者校验通过, 覆盖他人修改, 冲突检测失效); ② 非法值 ("abc")
        # 在 save_agent_config 的 int() 抛出 → 500。与 agent_id 同等对待, 剥离。
        merged = asdict(instance.config)
        for k, v in payload.items():
            if k in merged and k not in ("agent_id", "revision"):
                merged[k] = v
        # Fix-91: 还原哨兵 —— GET 已把敏感键脱敏为哨兵, WebUI 编辑回传时若原样
        # 带回哨兵, 不能让它覆盖真实凭据; 仅当客户端真传了新值才更新敏感键。
        merged = _restore_redacted(merged, asdict(instance.config))
        try:
            new_config = AgentConfig(**merged)
        except (ValueError, TypeError) as exc:
            # R14: 服务端记录完整异常信息, 客户端只返回通用错误码 (不泄露
            # Python 类型/字段路径/磁盘 IO 信息)。
            logger.warning("Agent 配置校验失败", error=str(exc), exc_info=True)
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_CONFIG", "message": "Agent config validation failed"},
            ) from exc
        # 持久化 (save_agent_config 会 revision+1)
        config_path = agents_dir_path / agent_id / "config.jsonc"
        save_agent_config(config_path, new_config)
        # 热更新到 runtime
        await agent_manager.reload_config(agent_id, new_config)
        await _audit(
            audit_log, "PATCH", f"/api/v1/agents/{agent_id}", "patch_agent",
            agent_id, detail=f"revision={new_config.revision}", actor=actor,
        )
        return {
            "agent_id": agent_id,
            "status": instance.status,
            "revision": new_config.revision,
        }


async def _do_create_agent(agent_manager: AgentManager, config: dict) -> Any:
    """构造 AgentConfig 并创建实例, 错误转 HTTPException。

    构造 AgentConfig (格式校验，如 agent_id 非法) 与创建实例 (是否已存在) 分开处理，
    避免 agent_id 格式错误被误报成"已存在" (409)。

    CR3-L1: 经控制面自动化创建的 Agent 一律使用受限默认配置
    (restricted_config_from_payload: bash/task deny + plugins_deny=["*"] +
    仅安全命令), 调用方 payload 里的能力字段被丢弃并告警; 需要放宽能力走
    PATCH /agents/{id} 显式授予。
    """
    from fastapi import HTTPException

    from isac.control.defaults import restricted_config_from_payload

    try:
        agent_config = restricted_config_from_payload(config)
    except (ValueError, TypeError) as exc:
        # R14: 服务端记录完整异常, 客户端只返回通用错误码 (不泄露内部信息)。
        logger.warning("Agent 创建配置校验失败", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_CONFIG", "message": "Agent config validation failed"},
        ) from exc

    try:
        return await agent_manager.create(agent_config)
    except ValueError as exc:
        # R14: 服务端记录完整异常, 客户端只返回通用错误码 (不泄露内部信息)。
        logger.warning("Agent 创建失败 (可能已存在)", error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=409,
            detail={"code": "AGENT_EXISTS", "message": "Agent already exists or creation failed"},
        ) from exc


async def _get_agent_config(agent_manager: AgentManager, agent_id: str) -> dict:
    """R2: 返回全量 AgentConfig (asdict) + 真实 revision; Agent 不存在抛 404。

    Fix-91: 回显前把敏感键 (llm.api_key 等) 替换为哨兵 —— 此前原样返回
    asdict(config), 持窄 scope agent:read token 的集成方可读走全部 Agent 的 LLM
    凭据明文。PATCH 侧经 _restore_redacted 保证哨兵不会覆盖真实值。
    """
    from dataclasses import asdict

    from fastapi import HTTPException

    instance = await agent_manager.get(agent_id)
    if instance is None:
        raise HTTPException(status_code=404, detail={"code": "AGENT_NOT_FOUND", "message": agent_id})
    return _redact_sensitive(asdict(instance.config))


async def _require_agent(
    agent_manager: AgentManager,
    agent_id: str,
    action: str,
    *,
    keep_memory: bool = True,
) -> None:
    """执行需要 Agent 存在的操作 (start/stop/destroy); 不存在抛 404。

    N5b 批次G: destroy 分支此前是 placeholder return (不检查存在性, destroy_agent
    路由自己 try/except 导致 build_router 圈复杂度超限); 现统一在此处执行 destroy
    并捕获 AgentNotFoundError → 404, 路由层零异常处理。
    """
    from fastapi import HTTPException

    from isac.core.exceptions import AgentNotFoundError
    try:
        if action == "start":
            await agent_manager.start(agent_id)
        elif action == "stop":
            await agent_manager.stop(agent_id)
        elif action == "destroy":
            await agent_manager.destroy(agent_id, keep_memory=keep_memory)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code, "message": exc.message}) from exc


async def _audit(
    audit_log: AuditLog | None,
    method: str,
    path: str,
    action: str,
    target: str,
    detail: str = "",
    actor: str = "authenticated",
) -> None:
    """记录审计日志 (如果 audit_log 为 None 则跳过)。

    actor 归因 (#29): 由 handler 经 Depends(auth_dependency) 注入的真实调用方
    身份 (api_token/session/token:<name>/token:<指纹>/anonymous); 未传时兜底
    "authenticated" (向后兼容)。
    """
    if audit_log is None:
        return
    await audit_log.record(
        actor=actor,
        method=method,
        path=path,
        action=action,
        target=target,
        detail=detail,
        status_code=200,
    )
