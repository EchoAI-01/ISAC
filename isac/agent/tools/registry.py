"""ToolRegistry: 工具注册与执行 (ARCHITECTURE.md 3.5)。

[已完成] 权限检查 (deny/restricted/allow) + 异常隔离 + restricted 策略 (未注入对应后端时拒绝) +
启用矩阵接入 (EnableMatrix: Agent ∩ Channel ∩ 全局);
AST 自动发现待落地 (当前手动 register)。

U5 四段权限管线: pre-execute (allow/deny/ask waterfall) → 单调 guard
(拒绝不可翻回) → 执行 → post 审计留痕 (decision + decider + reason, 经 U1
会话事件表 tool.called/tool.outcome)。ask 档经 ApprovalGate 人工审批,
超时 fail-closed。

错误处理: ToolError → 错误信息给 LLM；未知异常 → 内部错误。
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from isac.agent.tools.approval import VERDICT_APPROVED, VERDICT_REJECTED
from isac.agent.tools.base import Tool, ToolContext, ToolPermission
from isac.agent.tools.decision_reasons import (
    DECIDER_HUMAN,
    DECIDER_POLICY,
    DECIDER_SYSTEM,
    DECISION_ALLOW,
    DECISION_ASK_APPROVED,
    DECISION_ASK_REJECTED,
    DECISION_ASK_TIMEOUT,
    DECISION_DENY,
    REASON_ASK_TIMEOUT,
    REASON_ASK_UNAVAILABLE,
    REASON_EXECUTED,
    REASON_HUMAN_APPROVED,
    REASON_HUMAN_REJECTED,
    REASON_POLICY_ALLOW,
    REASON_POLICY_DENY,
    REASON_PRIOR_DENIAL,
    REASON_SERVICE_MISSING,
    REASON_UNKNOWN_TOOL,
)
from isac.agent.tools.guard import OUTCOME_DENIED
from isac.core.exceptions import ToolError
from isac.core.types import AgentContext, ToolCall, ToolResult
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.core.policy import EnableMatrix

logger = get_logger(__name__)


class _NamespacedTool(Tool):
    """U0 Fix-88: 插件工具命名空间包装器 —— 给注册名加 ``<plugin>:`` 前缀。

    委托 description/parameters/execute 给内层原工具, 仅 name 变为
    ``f"{namespace}:{inner.name}"``。让 compat/native 插件工具在机制上不可能与内置
    工具同名冲突或覆盖 (此前同名只有一条覆盖 warning, 非确定性; 恶意/失误的同名
    插件工具可顶替内置工具)。方案对齐 MCPToolBridge 的 ``mcp:{server}:{tool}``
    命名空间。内层工具的 LLM 调用语义不变 (execute 透传)。
    """

    def __init__(self, namespace: str, inner: Tool) -> None:
        self._namespace = namespace
        self._inner = inner

    @property
    def name(self) -> str:
        return f"{self._namespace}:{self._inner.name}"

    @property
    def description(self) -> str:
        return self._inner.description

    @property
    def parameters(self) -> dict:
        return self._inner.parameters

    async def execute(self, context: ToolContext) -> ToolResult:
        return await self._inner.execute(context)


class ToolRegistry:
    """工具注册表。每个 AgentInstance 持有一个独立实例 (权限策略按 Agent 配置)。"""

    def __init__(
        self,
        permission: ToolPermission | None = None,
        enable_matrix: EnableMatrix | None = None,
        agent_id: str = "",
    ):
        self._tools: dict[str, Tool] = {}
        # T6: 工具来源追踪 (tool_name → "builtin" 或插件名), 供热重载按来源 deregister。
        self._source: dict[str, str] = {}
        # T6: on_load 期间设置的默认来源 (激活模块 set_current_source(plugin_name))。
        self._current_source: str | None = None
        self.permission = permission or ToolPermission()
        self.enable_matrix = enable_matrix
        self.agent_id = agent_id

    def register(self, tool: Tool, *, source: str | None = None) -> None:
        """注册工具 (重名覆盖并告警)。

        T6: source 追踪工具来源插件名。source=None 时取 _current_source (on_load
        期间设置) 或 "builtin"。向后兼容: 既有 register(tool) 调用 → source="builtin"。

        U0 Fix-88: 插件来源 (effective_source != "builtin") 的工具自动加
        ``<plugin>:`` 前缀 (包装为 _NamespacedTool), 确定性命名空间隔离, 防同名覆盖
        内置工具。builtin 工具不加。前缀用 effective_source, 与 source 追踪键一致, 故
        tools_policy/EnableMatrix/deregister_by_source 的键统一为 ``<plugin>:<tool>``。

        Fix-128: 跳过条件从"名字含任意 ':'"收紧为"名字已含**本插件自己的**前缀
        ``<effective_source>:``" —— 此前恶意/失误的插件工具把 ':' 写进名字 (如
        ``mcp:fake:tool`` / ``别的插件:tool``) 即可整体绕过命名空间, 冒充 MCP 工具或
        顶替其他插件的已命名工具。现在只有已被同源包装过 (重注册) 才跳过, 其余一律
        加前缀。MCP 桥接工具以 source="builtin" 注册 (assembly 不传 source), 不受影响。
        """
        effective_source = source or self._current_source or "builtin"
        if effective_source != "builtin" and not tool.name.startswith(f"{effective_source}:"):
            tool = _NamespacedTool(effective_source, tool)
        if tool.name in self._tools:
            logger.warning("工具重复注册，已覆盖", tool=tool.name)
        self._tools[tool.name] = tool
        self._source[tool.name] = effective_source

    def deregister(self, name: str) -> bool:
        """移除工具 (T6 热重载)。返回是否移除成功。"""
        if name not in self._tools:
            return False
        del self._tools[name]
        self._source.pop(name, None)
        return True

    def deregister_by_source(self, source: str) -> list[str]:
        """移除指定来源的全部工具, 返回被移除的工具名列表 (T6 热重载同步)。"""
        removed = [n for n, s in self._source.items() if s == source]
        for n in removed:
            self._tools.pop(n, None)
            self._source.pop(n, None)
        return removed

    def deregister_plugin_sourced(self) -> list[str]:
        """移除全部插件来源工具 (source != "builtin"), 返回被移除的工具名列表。

        供热重载全量同步: 先清空 per-Agent 的全部插件工具, 再从共享表重新合并。
        """
        removed = [n for n, s in self._source.items() if s != "builtin"]
        for n in removed:
            self._tools.pop(n, None)
            self._source.pop(n, None)
        return removed

    def get_by_source(self, source: str) -> list[Tool]:
        """返回指定来源的全部工具 (T6 热重载同步)。"""
        return [self._tools[n] for n, s in self._source.items() if s == source and n in self._tools]

    def set_current_source(self, source: str | None) -> None:
        """设置后续 register() 的默认来源 (on_load 期间设为插件名, 结束后置 None)。"""
        self._current_source = source

    def source_of(self, tool_name: str) -> str | None:
        """返回工具的来源插件名 (或 "builtin"), 不存在返回 None。"""
        return self._source.get(tool_name)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def effective_policy(self, tool_name: str, platform: str = "") -> str:
        """返回工具有效策略: allow / restricted / ask / deny。

        合并顺序: ToolPermission (全局默认+Agent tools_policy) → EnableMatrix (Channel 覆盖)。
        U5: 引入 ask 档 (人工审批)。Channel 明确 deny/restricted/ask 覆盖基础策略。
        """
        policy = self.permission.check(tool_name)
        if self.enable_matrix is not None:
            agent_policy_dict = self.permission.policy
            platform_policy = self.enable_matrix.tool_policy(
                tool_name, agent_policy_dict, agent_id=self.agent_id, platform=platform
            )
            # Channel 明确 deny / restricted / ask 优先
            if platform_policy in ("deny", "restricted", "ask"):
                policy = platform_policy
        return policy

    def definitions(self, platform: str = "") -> list[dict]:
        """返回 function calling 定义 (过滤 deny 工具)。"""
        return [
            {"name": t.name, "description": t.description, "parameters": t.parameters}
            for t in self._tools.values()
            if self.effective_policy(t.name, platform) != "deny"
        ]

    async def execute(
        self,
        tool_call: ToolCall,
        agent_context: AgentContext,
        services: dict | None = None,
    ) -> ToolResult:
        """U5 四段权限管线执行工具调用。

        阶段:
        1. **pre-execute waterfall**: effective_policy 判档 —— deny 拒; restricted
           查后端服务门; ask 进入人工审批 (ApprovalGate, 超时 fail-closed)。
        2. **单调 guard**: DenyGuard 记录本会话被拒工具, 后续调用一律拒绝不可翻回。
        3. **执行**: 正常调用 tool.execute (异常隔离)。
        4. **post 审计留痕**: 决策 + 决策者 + 理由经 U1 会话事件表
           (tool.called 执行前 / tool.outcome 执行后, 拒绝也留痕)。
        """
        tool = self._tools.get(tool_call.name)
        session_key = self._session_key_for(agent_context, services)
        if tool is None:
            await self._log_tool_event(
                services, session_key, tool_call.name, "denied",
                decision=DECISION_DENY, decider=DECIDER_SYSTEM, reason=REASON_UNKNOWN_TOOL,
            )
            return ToolResult(content=f"未知工具: {tool_call.name}", is_error=True)

        platform = getattr(agent_context.session, "platform", "") if agent_context.session else ""
        policy = self.effective_policy(tool.name, platform)
        deny_guard = (services or {}).get("deny_guard")

        # ── 阶段 1: pre-execute waterfall (deny / restricted 服务门) ──
        gated = await self._pre_execute_gate(tool.name, policy, session_key, services, deny_guard)
        if gated is not None:
            return gated

        # ── 阶段 2: 单调 guard (拒绝不可翻回) ─────────────────
        # Fix-136: is_denied 改异步 —— 内存缺失的会话可经事件流惰性重建拒绝集,
        # 使 LRU 逐出不会把"曾被拒"翻回放行。
        if deny_guard is not None and await deny_guard.is_denied(session_key, tool.name):
            await self._log_tool_event(
                services, session_key, tool.name, "denied",
                decision=DECISION_DENY, decider=DECIDER_SYSTEM, reason=REASON_PRIOR_DENIAL,
            )
            return ToolResult(
                content=f"工具 {tool.name} 在本会话已被拒绝, 不再重复询问/执行", is_error=True,
            )

        # ── 阶段 1b: ask 档 → 人工审批 ─────────────────────────
        decision, decider, reason = DECISION_ALLOW, DECIDER_POLICY, REASON_POLICY_ALLOW
        if policy == "ask":
            ask_result = await self._run_ask_gate(
                tool.name, tool_call, agent_context, session_key, services, deny_guard
            )
            if isinstance(ask_result, ToolResult):
                return ask_result
            decision, decider, reason = ask_result

        # ── 阶段 3+4: 执行 + post 审计留痕 ─────────────────────
        return await self._execute_with_audit(
            tool, tool_call, agent_context, services, session_key, decision, decider, reason
        )

    async def _pre_execute_gate(
        self,
        tool_name: str,
        policy: str,
        session_key: str,
        services: dict | None,
        deny_guard: Any,
    ) -> ToolResult | None:
        """阶段 1 前置门: deny 拒; restricted 查后端服务门。放行返回 None。"""
        if policy == "deny":
            if deny_guard is not None:
                deny_guard.register_denial(session_key, tool_name)
            await self._log_tool_event(
                services, session_key, tool_name, "denied",
                decision=DECISION_DENY, decider=DECIDER_POLICY, reason=REASON_POLICY_DENY,
            )
            return ToolResult(content=f"工具 {tool_name} 已被配置禁用", is_error=True)
        if policy == "restricted":
            required = self._required_service(tool_name)
            if required:
                # Q0: 支持备选服务键 (tuple) —— 任一后端注入即放行, 如 task 工具
                # 的 subagent_supervisor (生产) / task_runner (旧路径向后兼容)。
                candidates = required if isinstance(required, tuple) else (required,)
                if not services or all(services.get(key) is None for key in candidates):
                    await self._log_tool_event(
                        services, session_key, tool_name, "denied",
                        decision=DECISION_DENY, decider=DECIDER_SYSTEM, reason=REASON_SERVICE_MISSING,
                    )
                    return ToolResult(
                        content=f"工具 {tool_name} 为受限工具, 需注入服务 {' 或 '.join(candidates)} 后方可使用。",
                        is_error=True,
                    )
        return None

    async def _run_ask_gate(
        self,
        tool_name: str,
        tool_call: ToolCall,
        agent_context: AgentContext,
        session_key: str,
        services: dict | None,
        deny_guard: Any,
    ) -> tuple[str, str, str] | ToolResult:
        """阶段 1b: ask 档人工审批。放行返回 (decision, decider, reason), 拒绝返回 ToolResult。"""
        approval_gate = (services or {}).get("approval_gate")
        if approval_gate is None:
            # fail-closed: ask 档但审批门未接线 → 拒绝 (不静默放行)
            if deny_guard is not None:
                deny_guard.register_denial(session_key, tool_name)
            await self._log_tool_event(
                services, session_key, tool_name, "denied",
                decision=DECISION_DENY, decider=DECIDER_SYSTEM, reason=REASON_ASK_UNAVAILABLE,
            )
            return ToolResult(
                content=f"工具 {tool_name} 需人工审批但审批服务未启用, 已拒绝执行。", is_error=True,
            )
        args_summary = self._summarize_args(tool_call.arguments)
        _session = agent_context.session if agent_context is not None else None
        verdict, req = await approval_gate.request(
            session_key, tool_name, args_summary,
            send_card=self._make_card_sender(agent_context, services),
            # Fix-90: 记录发起会话的用户, IM 回流裁决时校验来源身份
            requester_user_id=getattr(_session, "user_id", "") or "",
        )
        if verdict == VERDICT_APPROVED:
            return DECISION_ASK_APPROVED, req.decider or DECIDER_HUMAN, REASON_HUMAN_APPROVED
        if verdict == VERDICT_REJECTED:
            decision, decider, reason = DECISION_ASK_REJECTED, req.decider or DECIDER_HUMAN, REASON_HUMAN_REJECTED
        else:  # timeout → fail-closed
            decision, decider, reason = DECISION_ASK_TIMEOUT, DECIDER_SYSTEM, REASON_ASK_TIMEOUT
        if deny_guard is not None:
            deny_guard.register_denial(session_key, tool_name)
        await self._log_tool_event(
            services, session_key, tool_name, "denied", decision=decision, decider=decider, reason=reason,
        )
        return ToolResult(
            content=f"工具 {tool_name} 的人工审批未通过 ({reason}), 已拒绝执行。", is_error=True,
        )

    async def _execute_with_audit(
        self,
        tool: Tool,
        tool_call: ToolCall,
        agent_context: AgentContext,
        services: dict | None,
        session_key: str,
        decision: str,
        decider: str,
        reason: str,
    ) -> ToolResult:
        """阶段 3+4: 执行工具并留痕 (tool.called 前置 / tool.outcome 后置)。"""
        await self._log_tool_event(
            services, session_key, tool.name, "called", decision=decision, decider=decider, reason=reason,
        )
        context = ToolContext(args=tool_call.arguments, agent_context=agent_context, services=services or {})
        try:
            result = await tool.execute(context)
        except ToolError:
            await self._log_tool_event(
                services, session_key, tool.name, "outcome", outcome="error",
                decision=decision, decider=decider, reason=REASON_EXECUTED,
            )
            raise
        except NotImplementedError as exc:
            await self._log_tool_event(
                services, session_key, tool.name, "outcome", outcome="error",
                decision=decision, decider=decider, reason=REASON_EXECUTED,
            )
            return ToolResult(content=str(exc), is_error=True)
        except Exception as exc:
            await self._log_tool_event(
                services, session_key, tool.name, "outcome", outcome="error",
                decision=decision, decider=decider, reason=REASON_EXECUTED,
            )
            raise ToolError(f"{type(exc).__name__}: {exc}") from exc
        await self._log_tool_event(
            services, session_key, tool.name, "outcome",
            outcome="error" if result.is_error else "ok",
            decision=decision, decider=decider, reason=REASON_EXECUTED,
        )
        return result

    # ── U5 管线辅助 ─────────────────────────────────────────

    @staticmethod
    def _session_key_for(agent_context: AgentContext, services: dict | None) -> str:
        """派生事件分区键 (与 manager._session_key_for 同口径); 不可达返回空串。"""
        session_mgr = (services or {}).get("session_mgr")
        session = agent_context.session if agent_context else None
        if session_mgr is None or session is None:
            return ""
        try:
            return session_mgr.make_session_key(
                getattr(session, "agent_id", "") or "",
                getattr(session, "platform", "") or "",
                getattr(session, "user_id", "") or "",
                getattr(session, "group_id", None),
            )
        except Exception:  # noqa: BLE001 键派生失败不阻塞工具执行 (审计降级)
            return ""

    @staticmethod
    async def _log_tool_event(
        services: dict | None,
        session_key: str,
        tool_name: str,
        stage: str,
        *,
        outcome: str = "",
        decision: str = "",
        decider: str = "",
        reason: str = "",
    ) -> None:
        """U5 post 审计留痕: 决策经 U1 会话事件表 (best-effort, 失败不阻塞执行)。

        stage="called" → tool.called (执行前, 副作用前 flush); stage="outcome"/
        "denied" → tool.outcome (执行结果/拒绝, payload 带 outcome + decision +
        decider + reason)。store/session_key 缺失时静默跳过 (单测/无持久化场景)。
        """
        store = (services or {}).get("session_event_store")
        if store is None or not session_key:
            return
        from isac.session.models import EVENT_TOOL_CALLED, EVENT_TOOL_OUTCOME, SessionEvent

        try:
            payload: dict[str, Any] = {"tool_name": tool_name}
            if decision:
                payload["decision"] = decision
            if decider:
                payload["decider"] = decider
            if reason:
                payload["reason"] = reason
            if stage == "called":
                event_type = EVENT_TOOL_CALLED
            else:
                event_type = EVENT_TOOL_OUTCOME
                payload["outcome"] = outcome or OUTCOME_DENIED
            await store.append(
                SessionEvent(
                    session_key=session_key,
                    event_type=event_type,
                    timestamp=int(time.time()),
                    payload=payload,
                )
            )
            await store.flush()  # 副作用 (工具执行) 前/后强制落盘
        except Exception as exc:  # noqa: BLE001 审计失败不阻塞工具执行
            logger.warning("工具决策留痕失败", tool=tool_name, stage=stage, error=str(exc))

    @staticmethod
    def _summarize_args(arguments: Any, limit: int = 300) -> str:
        """工具参数 → 审批卡片摘要 (JSON 截断, 防超长参数打爆卡片)。"""
        try:
            text = json.dumps(arguments, ensure_ascii=False, default=str) if arguments else ""
        except (TypeError, ValueError):
            text = str(arguments)
        return text[:limit] + ("..." if len(text) > limit else "")

    @staticmethod
    def _make_card_sender(agent_context: AgentContext, services: dict | None) -> Any:
        """构造审批卡片投递器 (经 channel_registry 发回本会话; 不可达返回 None)。

        与 main._make_progress_sender 同构: 按会话 platform 找 adapter, 构造
        metadata.message_kind=approval 的文本消息。找不到 adapter 时返回 None
        (审批等待继续, 可经控制面审批)。
        """
        registry = (services or {}).get("channel_registry")
        session = agent_context.session if agent_context else None
        if registry is None or session is None:
            return None
        platform = getattr(session, "platform", "") or ""
        if not platform:
            return None

        async def send_card(text: str) -> bool:
            from isac.channel.model import ISACMessage

            adapter = registry.get(platform)
            if adapter is None:
                return False
            card_message = ISACMessage(
                msg_id="",
                platform=platform,
                timestamp=0,
                user_id=getattr(session, "user_id", "") or "",
                user_name="",
                group_id=getattr(session, "group_id", None),
                session_id=getattr(session, "platform_session_id", "") or getattr(session, "session_id", ""),
                content=text,
                metadata={"message_kind": "approval"},
            )
            return await adapter.send(card_message)

        return send_card

    @staticmethod
    def _required_service(tool_name: str) -> str | tuple[str, ...] | None:
        """restricted 工具 → 必须注入的 service key (tuple = 任一注入即可)。

        没有列入的 restricted 工具默认只要求 services 非空 (任意后端存在即可)。

        U0 Fix-87: mcp: 桥接工具映射到 "mcp_clients" —— MCP 接线时 assembly 注入
        agent_services["mcp_clients"] (非空列表); 未接线则缺失/为空, restricted 门
        拒绝。此前 mcp: 工具在 ToolPermission.check 默认 restricted 但本映射无对应项
        → restricted 等效 allow (语义矛盾: "受限"却恒放行)。补映射后 restricted 语义
        落实: LLM 直调未接线 Agent 的 mcp 工具被拒。
        """
        if tool_name.startswith("mcp:"):
            return "mcp_clients"
        mapping: dict[str, str | tuple[str, ...]] = {
            "read_file": "workspace_root",
            "write_file": "workspace_root",
            "bash": "bash_allowlist",
            "web_search": "web_search",
            # Q0 修正: task 工具 J4 起优先走 subagent_supervisor (生产恒注入),
            # 旧映射只认 task_runner (全仓无生产注入点), 使已接线的 SubAgent
            # 委派在 restricted 门就被挡死; 现两者任一注入即放行。
            "task": ("subagent_supervisor", "task_runner"),
            "send_emoji": "channel_send",
            "send_image": "channel_send",
            "fetch_history": "channel_history",
            "switch_chat": "session_topic",
            "view_forward_message": "channel_forward",
            # M2: 4 个 A2A 工具需 mesh_action_broker 注入后方可调用
            "notify_agent": "mesh_action_broker",
            "handoff_conversation": "mesh_action_broker",
            "list_available_agents": "mesh_action_broker",
            "memory_query_agent": "mesh_action_broker",
            # Fix-127: J4 的 5 个 SubAgent 工具 DEFAULT_POLICY 为 restricted, 但此前无
            # 映射 → restricted 门 `if required:` 为假直接放行, 等效 allow (与"受限"语义
            # 矛盾, 同 Fix-87 修 mcp:* 前的病灶)。它们统一经 subagent_supervisor 服务键
            # 取后端 (subagent.py _SupervisorToolBase._supervisor), 补映射后未注入
            # Supervisor 的 Agent 调用即被拒。
            "delegate_task": "subagent_supervisor",
            "list_subagents": "subagent_supervisor",
            "subagent_status": "subagent_supervisor",
            "subagent_log": "subagent_supervisor",
            "cancel_subagent": "subagent_supervisor",
        }
        return mapping.get(tool_name)
