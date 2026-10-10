"""U5 工具权限管线 + HITL 卡片审批专项测试。

验收覆盖 (DEVELOPMENT_PLAN §四 U5):
- 四段管线: pre-execute (allow/deny/ask waterfall) → 单调 guard → 执行 → post 审计留痕;
- ask 档审批三路 (同意/拒绝/超时 fail-closed);
- guard 拒绝不可翻回 (含跨重启从事件流重建);
- 决策留痕可查询 (decision + decider + reason 落 U1 事件表);
- 决策理由词汇表 drift test (管线产出的理由全在规范集内);
- 既有 restricted/EnableMatrix/三态语义回归一致。
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any

import pytest

from isac.agent.tools.approval import (
    VERDICT_APPROVED,
    VERDICT_REJECTED,
    VERDICT_TIMEOUT,
    ApprovalGate,
)
from isac.agent.tools.base import Tool, ToolContext, ToolPermission
from isac.agent.tools.decision_reasons import (
    DECISION_REASONS,
    DECISIONS,
    validate_reason,
)
from isac.agent.tools.guard import OUTCOME_DENIED, DenyGuard
from isac.agent.tools.registry import ToolRegistry
from isac.core.types import AgentContext, ToolCall, ToolResult
from isac.session.event_store import SessionEventStore
from isac.session.models import EVENT_TOOL_CALLED, EVENT_TOOL_OUTCOME


class FlagTool(Tool):
    def __init__(self, name: str = "flag") -> None:
        self._name = name
        self.executed = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "标记是否执行"

    async def execute(self, context: ToolContext) -> ToolResult:
        self.executed = True
        return ToolResult(content="executed")


class _Session:
    """最小 session 替身 (提供 platform/user_id/group_id/agent_id 供键派生)。"""

    platform = "fake"
    user_id = "u1"
    group_id = "g1"
    agent_id = "agent_a"


class _SessionMgr:
    @staticmethod
    def make_session_key(agent_id: str, platform: str, user_id: str, group_id) -> str:
        target = f"group:{group_id}" if group_id else f"user:{user_id}"
        return f"{agent_id}:{platform}:{target}"


def make_agent_context() -> AgentContext:
    return AgentContext(session=_Session(), user_profile=None, current_message=object())


SESSION_KEY = "agent_a:fake:group:g1"


async def _started_store(tmp_path: Path) -> SessionEventStore:
    store = SessionEventStore(str(tmp_path / "session_events.db"))
    await store.start()
    return store


# ── 决策理由词汇表 (drift 防护) ──────────────────────────────


def test_decision_reasons_vocabulary_consistent() -> None:
    """drift test: DECISION_REASONS 无重复语义且 validate_reason 拒绝越表值。"""
    assert len(DECISION_REASONS) == 10
    assert validate_reason("policy_deny") == "policy_deny"
    with pytest.raises(ValueError):
        validate_reason("some_freeform_reason")


def test_pipeline_emitted_reasons_all_in_vocabulary() -> None:
    """drift test: registry 管线源码里产出的每个 reason 常量都在规范词汇表内。

    扫描 registry.py 引用的 decision_reasons 常量, 逐个断言 ∈ DECISION_REASONS
    (DECIDER_/DECISION_ 前缀除外) —— 防止新增理由时绕过词汇表。
    """
    from isac.agent.tools import decision_reasons as dr
    from isac.agent.tools import registry as reg

    src = Path(inspect.getsourcefile(reg)).read_text(encoding="utf-8")
    used = {name for name in dir(dr) if name.startswith("REASON_") and name in src}
    assert used, "registry 应引用 reason 常量"
    for name in used:
        assert getattr(dr, name) in DECISION_REASONS
    # decision 值同样受词汇约束
    for name in (n for n in dir(dr) if n.startswith("DECISION_") and n != "DECISION_REASONS"):
        if name in src:
            assert getattr(dr, name) in DECISIONS


# ── 单调 DenyGuard ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_deny_guard_monotonic_no_flip_back() -> None:
    """guard 拒绝不可翻回: 登记后 is_denied 恒 True, 无任何撤销 API。"""
    guard = DenyGuard()
    assert await guard.is_denied(SESSION_KEY, "bash") is False
    guard.register_denial(SESSION_KEY, "bash")
    assert await guard.is_denied(SESSION_KEY, "bash") is True
    # 重复登记幂等; 无 remove/clear 公共方法 (单调性)
    guard.register_denial(SESSION_KEY, "bash")
    assert await guard.is_denied(SESSION_KEY, "bash") is True
    assert not hasattr(guard, "remove_denial") and not hasattr(guard, "clear")


@pytest.mark.asyncio
async def test_deny_guard_restore_from_events(tmp_path: Path) -> None:
    """跨重启不可翻回: 拒绝经 tool.outcome=DENIED 事件持久化, 启动重建。"""
    from isac.session.models import SessionEvent

    store = await _started_store(tmp_path)
    try:
        await store.append(
            SessionEvent(
                session_key=SESSION_KEY, event_type=EVENT_TOOL_OUTCOME, timestamp=1,
                payload={"tool_name": "write_file", "outcome": OUTCOME_DENIED,
                         "decision": "ask_rejected", "decider": "human", "reason": "human_rejected"},
            )
        )
        await store.flush()
        events = await store.fetch(SESSION_KEY)
        guard = DenyGuard()
        assert guard.restore_from_events(SESSION_KEY, events) == 1
        assert await guard.is_denied(SESSION_KEY, "write_file") is True
    finally:
        await store.stop()


# ── ApprovalGate ─────────────────────────────────────────────


def test_approval_parse_reply() -> None:
    gate = ApprovalGate()
    assert gate.parse_reply("同意 ab12cd34") == ("ab12cd34", VERDICT_APPROVED)
    assert gate.parse_reply("approve AB12CD34") == ("ab12cd34", VERDICT_APPROVED)
    assert gate.parse_reply("拒绝 ab12cd34") == ("ab12cd34", VERDICT_REJECTED)
    assert gate.parse_reply("deny ab12cd34") == ("ab12cd34", VERDICT_REJECTED)
    assert gate.parse_reply("今天天气不错") is None
    assert gate.parse_reply("同意") is None  # 缺审批码


@pytest.mark.asyncio
async def test_approval_approved_path() -> None:
    gate = ApprovalGate(timeout_seconds=5.0)
    cards: list[str] = []

    async def send_card(text: str) -> bool:
        cards.append(text)
        return True

    async def approver() -> None:
        for _ in range(50):
            pending = gate.pending_requests()
            if pending:
                assert gate.decide(pending[0]["approval_id"], VERDICT_APPROVED, decider="human:im") is True
                return
            await asyncio.sleep(0.01)

    task = asyncio.create_task(approver())
    verdict, req = await gate.request(SESSION_KEY, "write_file", "{}", send_card=send_card)
    await task
    assert verdict == VERDICT_APPROVED
    assert req.decider == "human:im"
    assert cards and "write_file" in cards[0] and req.approval_id in cards[0]


@pytest.mark.asyncio
async def test_approval_timeout_fail_closed() -> None:
    gate = ApprovalGate(timeout_seconds=5.0)
    gate._timeout_seconds = 0.2  # 加速测试
    verdict, _req = await gate.request(SESSION_KEY, "write_file", "{}")
    assert verdict == VERDICT_TIMEOUT


@pytest.mark.asyncio
async def test_approval_decide_unknown_returns_false() -> None:
    gate = ApprovalGate()
    assert gate.decide("nonexistent", VERDICT_APPROVED) is False


# ── Fix-90: IM 审批回流来源鉴权 ─────────────────────────────


@pytest.mark.asyncio
async def test_approval_decide_rejects_other_conversation() -> None:
    """Fix-90: 审批卡片 (含审批码) 发回原会话, 群内任何成员可见; 其他会话的
    用户得知审批码后不得裁决 (此前 decide 只按审批码查表 → HITL 门旁路)。"""
    gate = ApprovalGate(timeout_seconds=5.0)

    async def approver() -> None:
        for _ in range(50):
            pending = gate.pending_requests()
            if pending:
                aid = pending[0]["approval_id"]
                # 来源会话不匹配 (另一个会话) → 拒绝裁决
                assert gate.decide(
                    aid, VERDICT_APPROVED, decider="human:fake:evil",
                    conversation="fake:group:g_other", user_id="evil",
                ) is False
                # 同会话但非发起人 (群内其他成员) → 拒绝裁决
                assert gate.decide(
                    aid, VERDICT_APPROVED, decider="human:fake:bystander",
                    conversation="fake:group:g1", user_id="bystander",
                ) is False
                # 同会话 + 发起人 → 放行
                assert gate.decide(
                    aid, VERDICT_APPROVED, decider="human:fake:u1",
                    conversation="fake:group:g1", user_id="u1",
                ) is True
                return
            await asyncio.sleep(0.01)

    task = asyncio.create_task(approver())
    verdict, req = await gate.request(
        SESSION_KEY, "bash", "{}", requester_user_id="u1",
    )
    await task
    assert verdict == VERDICT_APPROVED
    assert req.decider == "human:fake:u1"


@pytest.mark.asyncio
async def test_approval_decide_control_plane_path_unchanged() -> None:
    """Fix-90 回归: 控制面路径不传 conversation/user_id (其鉴权由 token scope
    承担), decide 行为不变。"""
    gate = ApprovalGate(timeout_seconds=5.0)

    async def approver() -> None:
        for _ in range(50):
            pending = gate.pending_requests()
            if pending:
                assert gate.decide(pending[0]["approval_id"], VERDICT_APPROVED) is True
                return
            await asyncio.sleep(0.01)

    task = asyncio.create_task(approver())
    verdict, _req = await gate.request(SESSION_KEY, "bash", "{}", requester_user_id="u1")
    await task
    assert verdict == VERDICT_APPROVED


# ── 四段管线 (ToolRegistry.execute) ──────────────────────────


@pytest.mark.asyncio
async def test_pipeline_allow_executes_and_audits(tmp_path: Path) -> None:
    """allow 档: 执行 + tool.called/tool.outcome 留痕 (decision=allow)。"""
    store = await _started_store(tmp_path)
    try:
        tool = FlagTool()
        registry = ToolRegistry(ToolPermission({"flag": "allow"}))
        registry.register(tool)
        services = {"session_event_store": store, "session_mgr": _SessionMgr()}
        result = await registry.execute(
            ToolCall(id="c1", name="flag", arguments={}), make_agent_context(), services=services
        )
        assert result.is_error is False and tool.executed is True
        events = await store.fetch(SESSION_KEY)
        types = [e.event_type for e in events]
        assert EVENT_TOOL_CALLED in types and EVENT_TOOL_OUTCOME in types
        called = next(e for e in events if e.event_type == EVENT_TOOL_CALLED)
        assert called.payload["decision"] == "allow" and called.payload["reason"] == "policy_allow"
        outcome = next(e for e in events if e.event_type == EVENT_TOOL_OUTCOME)
        assert outcome.payload["outcome"] == "ok" and outcome.payload["tool_name"] == "flag"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_pipeline_deny_audits_policy_deny(tmp_path: Path) -> None:
    store = await _started_store(tmp_path)
    try:
        tool = FlagTool()
        registry = ToolRegistry(ToolPermission({"flag": "deny"}))
        registry.register(tool)
        services = {"session_event_store": store, "session_mgr": _SessionMgr()}
        result = await registry.execute(
            ToolCall(id="c1", name="flag", arguments={}), make_agent_context(), services=services
        )
        assert result.is_error is True and tool.executed is False
        events = await store.fetch(SESSION_KEY)
        outcome = next(e for e in events if e.event_type == EVENT_TOOL_OUTCOME)
        assert outcome.payload["outcome"] == OUTCOME_DENIED
        assert outcome.payload["reason"] == "policy_deny" and outcome.payload["decider"] == "policy"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_pipeline_restricted_service_missing_audits(tmp_path: Path) -> None:
    """restricted 档后端服务未注入 → 拒绝 + 留痕 service_missing。"""
    store = await _started_store(tmp_path)
    try:
        tool = FlagTool(name="read_file")
        registry = ToolRegistry(ToolPermission({"read_file": "restricted"}))
        registry.register(tool)
        # services 无 workspace_root → restricted 门拒绝
        services = {"session_event_store": store, "session_mgr": _SessionMgr()}
        result = await registry.execute(
            ToolCall(id="c1", name="read_file", arguments={}), make_agent_context(), services=services
        )
        assert result.is_error is True and tool.executed is False
        events = await store.fetch(SESSION_KEY)
        outcome = next(e for e in events if e.event_type == EVENT_TOOL_OUTCOME)
        assert outcome.payload["reason"] == "service_missing" and outcome.payload["outcome"] == OUTCOME_DENIED
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_pipeline_ask_approved_executes(tmp_path: Path) -> None:
    """ask 档同意路: 审批通过 → 执行, 留痕 decision=ask_approved/decider=human。"""
    store = await _started_store(tmp_path)
    try:
        gate = ApprovalGate(timeout_seconds=5.0)
        tool = FlagTool()
        registry = ToolRegistry(ToolPermission({"flag": "ask"}))
        registry.register(tool)
        services = {"session_event_store": store, "session_mgr": _SessionMgr(), "approval_gate": gate}

        async def approver() -> None:
            for _ in range(100):
                pending = gate.pending_requests()
                if pending:
                    gate.decide(pending[0]["approval_id"], VERDICT_APPROVED, decider="human:im:u1")
                    return
                await asyncio.sleep(0.01)

        task = asyncio.create_task(approver())
        result = await registry.execute(
            ToolCall(id="c1", name="flag", arguments={}), make_agent_context(), services=services
        )
        await task
        assert result.is_error is False and tool.executed is True
        events = await store.fetch(SESSION_KEY)
        called = next(e for e in events if e.event_type == EVENT_TOOL_CALLED)
        assert called.payload["decision"] == "ask_approved"
        assert called.payload["decider"] == "human:im:u1"
        assert called.payload["reason"] == "human_approved"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_pipeline_ask_rejected_denies_and_guards(tmp_path: Path) -> None:
    """ask 档拒绝路: 审批拒绝 → 不执行 + 单调 guard 登记 + 留痕。"""
    store = await _started_store(tmp_path)
    try:
        gate = ApprovalGate(timeout_seconds=5.0)
        guard = DenyGuard()
        tool = FlagTool()
        registry = ToolRegistry(ToolPermission({"flag": "ask"}))
        registry.register(tool)
        services = {
            "session_event_store": store, "session_mgr": _SessionMgr(),
            "approval_gate": gate, "deny_guard": guard,
        }

        async def rejecter() -> None:
            for _ in range(100):
                pending = gate.pending_requests()
                if pending:
                    gate.decide(pending[0]["approval_id"], VERDICT_REJECTED, decider="human:im:u1")
                    return
                await asyncio.sleep(0.01)

        task = asyncio.create_task(rejecter())
        result = await registry.execute(
            ToolCall(id="c1", name="flag", arguments={}), make_agent_context(), services=services
        )
        await task
        assert result.is_error is True and tool.executed is False
        assert await guard.is_denied(SESSION_KEY, "flag") is True
        events = await store.fetch(SESSION_KEY)
        outcome = next(e for e in events if e.event_type == EVENT_TOOL_OUTCOME)
        assert outcome.payload["decision"] == "ask_rejected" and outcome.payload["outcome"] == OUTCOME_DENIED
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_pipeline_ask_timeout_fail_closed(tmp_path: Path) -> None:
    """ask 档超时路: fail-closed 拒绝 + guard 登记 + 留痕 ask_timeout。"""
    store = await _started_store(tmp_path)
    try:
        gate = ApprovalGate(timeout_seconds=5.0)
        gate._timeout_seconds = 0.2
        guard = DenyGuard()
        tool = FlagTool()
        registry = ToolRegistry(ToolPermission({"flag": "ask"}))
        registry.register(tool)
        services = {
            "session_event_store": store, "session_mgr": _SessionMgr(),
            "approval_gate": gate, "deny_guard": guard,
        }
        result = await registry.execute(
            ToolCall(id="c1", name="flag", arguments={}), make_agent_context(), services=services
        )
        assert result.is_error is True and tool.executed is False
        assert await guard.is_denied(SESSION_KEY, "flag") is True
        events = await store.fetch(SESSION_KEY)
        outcome = next(e for e in events if e.event_type == EVENT_TOOL_OUTCOME)
        assert outcome.payload["decision"] == "ask_timeout" and outcome.payload["reason"] == "ask_timeout"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_pipeline_ask_gate_unwired_fail_closed() -> None:
    """ask 档但审批门未接线 → fail-closed 拒绝 (不静默放行)。"""
    tool = FlagTool()
    registry = ToolRegistry(ToolPermission({"flag": "ask"}))
    registry.register(tool)
    result = await registry.execute(
        ToolCall(id="c1", name="flag", arguments={}), make_agent_context(), services={}
    )
    assert result.is_error is True and tool.executed is False
    assert "审批服务未启用" in result.content


@pytest.mark.asyncio
async def test_pipeline_prior_denial_blocks_without_reask(tmp_path: Path) -> None:
    """guard 拒绝不可翻回: 已拒工具再次调用直接被拒, 不再触发审批询问。"""
    store = await _started_store(tmp_path)
    try:
        gate = ApprovalGate(timeout_seconds=5.0)
        guard = DenyGuard()
        guard.register_denial(SESSION_KEY, "flag")
        tool = FlagTool()
        registry = ToolRegistry(ToolPermission({"flag": "ask"}))
        registry.register(tool)
        services = {
            "session_event_store": store, "session_mgr": _SessionMgr(),
            "approval_gate": gate, "deny_guard": guard,
        }
        result = await registry.execute(
            ToolCall(id="c1", name="flag", arguments={}), make_agent_context(), services=services
        )
        assert result.is_error is True and tool.executed is False
        assert "已被拒绝" in result.content
        assert gate.pending_requests() == []  # 未发起新审批
        events = await store.fetch(SESSION_KEY)
        outcome = next(e for e in events if e.event_type == EVENT_TOOL_OUTCOME)
        assert outcome.payload["reason"] == "prior_denial"
    finally:
        await store.stop()


@pytest.mark.asyncio
async def test_pipeline_unknown_tool_audits() -> None:
    registry = ToolRegistry()
    result = await registry.execute(
        ToolCall(id="c1", name="no_such_tool", arguments={}), make_agent_context(), services={}
    )
    assert result.is_error is True and "未知工具" in result.content


# ── ToolPermission ask 档语义 ────────────────────────────────


def test_permission_ask_level_and_unknown_fail_closed() -> None:
    perm = ToolPermission({"tool_a": "ask", "tool_b": "weird_level"})
    assert perm.check("tool_a") == "ask"
    assert perm.check("tool_b") == "deny"  # 未知档位 fail-closed
    assert perm.check("undeclared") == "allow"
    assert perm.check("mcp:server:tool") == "restricted"


# ── mcp:/compat/native 统一命名空间注册管线 (Fix-88 机制化) ──


class _PluginTool(Tool):
    def __init__(self, name: str) -> None:
        self._n = name

    @property
    def name(self) -> str:
        return self._n

    @property
    def description(self) -> str:
        return "插件工具"

    async def execute(self, context: ToolContext) -> ToolResult:
        return ToolResult(content="ok")


def test_namespace_pipeline_invariant_non_builtin_prefixed() -> None:
    """机制化不变量: 非 builtin 来源工具注册名必含 ':' 命名空间前缀, 机制上
    不可能与内置工具同名冲突 (同名插件工具被前缀化, 不覆盖内置)。"""
    registry = ToolRegistry()
    registry.register(FlagTool(), source="builtin")  # 内置 flag
    registry.register(_PluginTool("flag"), source="evil_plugin")  # 同名插件工具
    assert registry.get("flag") is not None
    assert registry.source_of("flag") == "builtin"  # 内置未被覆盖
    assert registry.get("evil_plugin:flag") is not None  # 插件工具被前缀化
    assert registry.source_of("evil_plugin:flag") == "evil_plugin"


def test_namespace_pipeline_mcp_already_namespaced_not_double_prefixed() -> None:
    """名字已含**自身来源**前缀时不二次前缀; 含 ':' 但非本源前缀仍被隔离 (Fix-128)。

    生产 MCP 桥接以 source=builtin 注册 (assembly 不传 source), 名字原样保留; 插件来源
    注册 ``mcp:server:tool`` 这类含 ':' 的名字不再整体绕过命名空间 (防冒充), 收进本源。
    """
    registry = ToolRegistry()
    # 自身前缀 (重注册幂等): 不二次前缀
    registry.register(_PluginTool("mcp_bridge:tool"), source="mcp_bridge")
    assert registry.get("mcp_bridge:tool") is not None
    assert registry.get("mcp_bridge:mcp_bridge:tool") is None

    # Fix-128: 含 ':' 但非本源前缀 (冒充 mcp:) → 仍被加前缀隔离
    registry2 = ToolRegistry()
    registry2.register(_PluginTool("mcp:server:tool"), source="mcp_bridge")
    assert registry2.get("mcp:server:tool") is None  # 不原样保留 (防冒充)
    assert registry2.get("mcp_bridge:mcp:server:tool") is not None


# ── 控制面审批路由 ───────────────────────────────────────────


def _make_approvals_app(gate: Any, store: Any = None) -> Any:
    from isac.control.api.server import create_control_app
    from isac.observability import get_default_metrics

    return create_control_app(
        type("A", (), {"list": lambda self: [], "get": lambda self, x: None})(),
        type("R", (), {})(), type("B", (), {})(), type("P", (), {})(),
        {"api_token": "t"}, metrics=get_default_metrics(),
        services={"approval_gate": gate, "session_event_store": store},
    )


def test_routes_approvals_not_mounted_without_gate() -> None:
    """无 approval_gate 时审批路由不挂载 (404)。"""
    from fastapi.testclient import TestClient

    from isac.control.api.server import create_control_app
    from isac.observability import get_default_metrics

    app = create_control_app(
        type("A", (), {"list": lambda self: [], "get": lambda self, x: None})(),
        type("R", (), {})(), type("B", (), {})(), type("P", (), {})(),
        {"api_token": "t"}, metrics=get_default_metrics(), services={},
    )
    resp = TestClient(app).get("/api/v1/approvals", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 404


def test_routes_approvals_list_and_decide() -> None:
    """控制面审批回流: GET /approvals 列 pending, POST decide 批准/拒绝。"""
    import asyncio as _aio

    from fastapi.testclient import TestClient

    from isac.agent.tools.approval import ApprovalRequest

    gate = ApprovalGate(timeout_seconds=30.0)
    client = TestClient(_make_approvals_app(gate))
    h = {"Authorization": "Bearer t", "Content-Type": "application/json"}

    # 无 pending
    assert client.get("/api/v1/approvals", headers=h).json()["approvals"] == []

    # 直接向 _pending 注入模拟 pending 审批 (TestClient 同步上下文不便起协程)
    loop = _aio.new_event_loop()
    req_future = loop.create_future()
    gate._pending["testid1"] = ApprovalRequest(
        approval_id="testid1", session_key="sess", tool_name="bash",
        args_summary="{}", created_at=0.0, future=req_future,
    )
    resp = client.get("/api/v1/approvals", headers=h)
    assert [a["approval_id"] for a in resp.json()["approvals"]] == ["testid1"]

    # decide 批准
    resp = client.post("/api/v1/approvals/testid1/decide", json={"decision": "approved"}, headers=h)
    assert resp.status_code == 200 and resp.json()["decision"] == "approved"
    assert req_future.result() == VERDICT_APPROVED

    # 未知审批码 → 404
    resp = client.post("/api/v1/approvals/nonexist/decide", json={"decision": "approved"}, headers=h)
    assert resp.status_code == 404
    # 非法 decision → 400
    gate._pending["testid2"] = ApprovalRequest(
        approval_id="testid2", session_key="sess", tool_name="bash",
        args_summary="{}", created_at=0.0, future=loop.create_future(),
    )
    resp = client.post("/api/v1/approvals/testid2/decide", json={"decision": "maybe"}, headers=h)
    assert resp.status_code == 400
    loop.close()


def test_routes_approvals_read_requires_tools_read_scope() -> None:
    """2026-08-19 scope 门禁回归: tokens[] 模式下审批读端点按 tools:read 收窄。

    此前 GET /approvals 与 /approvals/history 只有路由级认证、无 scope —— 任何窄
    权限 token (如仅 usage:read) 都能读全部待审上下文与决策历史。现窄 scope 读被
    403 拒绝, 持 tools:read / "*" 的 token 可读。
    """
    from fastapi.testclient import TestClient

    from isac.control.api.server import create_control_app
    from isac.observability import get_default_metrics

    gate = ApprovalGate(timeout_seconds=30.0)
    app = create_control_app(
        type("A", (), {"list": lambda self: [], "get": lambda self, x: None})(),
        type("R", (), {})(), type("B", (), {})(), type("P", (), {})(),
        {"tokens": [
            {"token": "narrow", "scopes": ["usage:read"]},
            {"token": "reader", "scopes": ["tools:read"]},
        ]},
        metrics=get_default_metrics(),
        services={"approval_gate": gate, "session_event_store": None},
    )
    client = TestClient(app)

    for path in ("/api/v1/approvals", "/api/v1/approvals/history"):
        assert client.get(path, headers={"Authorization": "Bearer narrow"}).status_code == 403
        assert client.get(path, headers={"Authorization": "Bearer reader"}).status_code == 200


# ── 2026-08-19 Medium 批清回归 (M1/M2) ────────────────────────


@pytest.mark.asyncio
async def test_m1_denyguard_restore_merges_concurrent_denial() -> None:
    """M1: 惰性重建收尾用合并 (setdefault().update()) 而非整体赋值。

    分页扫描期间存在 await(store.fetch), 若同会话另一工具并发被拒并 register_denial
    先写入 _denials[session_key], 收尾整体赋值会覆盖该并发写入 → 已登记拒绝丢失、
    被拒工具可再执行 (单调性在并发下被破坏)。合并写法必须保留并发写入。
    """

    class _Event:
        def __init__(self, tool_name: str, seq: int) -> None:
            self.event_type = "tool.outcome"
            self.payload = {"outcome": OUTCOME_DENIED, "tool_name": tool_name}
            self.seq = seq

    class _RaceStore:
        """首次 fetch 的 await 窗口内模拟并发 register_denial (另一工具)。"""

        def __init__(self, guard_ref: dict) -> None:
            self._guard_ref = guard_ref
            self._injected = False

        async def fetch(self, session_key: str, after_seq: int = 0, limit: int = 1000):
            if after_seq == 0:
                if not self._injected:
                    self._injected = True
                    self._guard_ref["guard"].register_denial(session_key, "concurrent_tool")
                return [_Event("event_tool", 1)]
            return []

    guard = DenyGuard()
    guard_ref = {"guard": guard}
    guard.bind_store(_RaceStore(guard_ref))
    # "sk" 不在内存 → is_denied 触发 _restore_session; 扫描窗口注入 concurrent_tool
    assert await guard.is_denied("sk", "event_tool") is True
    # 并发登记的拒绝不能被收尾整体赋值覆盖 (旧 bug 下此处为 False)
    assert await guard.is_denied("sk", "concurrent_tool") is True


@pytest.mark.asyncio
async def test_m2_restricted_without_mapping_fail_closed(tmp_path: Path) -> None:
    """M2: restricted 工具未登记 _required_service 映射时拒绝 (fail-closed)。

    此前 `if required:` 为假直接跳过服务检查 → 等效 allow (任何经 tools_policy 设为
    restricted 的插件工具都落入此洞)。受限工具必须声明依赖服务方可校验。
    """
    store = await _started_store(tmp_path)
    try:
        tool = FlagTool(name="custom_plugin_tool")  # 不在 _required_service 映射内
        registry = ToolRegistry(ToolPermission({"custom_plugin_tool": "restricted"}))
        registry.register(tool)
        services = {"session_event_store": store, "session_mgr": _SessionMgr()}
        result = await registry.execute(
            ToolCall(id="c1", name="custom_plugin_tool", arguments={}),
            make_agent_context(), services=services,
        )
        # fail-closed: 拒绝且不执行
        assert result.is_error is True and tool.executed is False
        assert "未登记依赖服务映射" in result.content
        events = await store.fetch(SESSION_KEY)
        outcome = next(e for e in events if e.event_type == EVENT_TOOL_OUTCOME)
        assert outcome.payload["outcome"] == OUTCOME_DENIED
        assert outcome.payload["reason"] == "service_missing"
    finally:
        await store.stop()
