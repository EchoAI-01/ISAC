"""S5 Workflow 控制面激活单测: action_handler 分发 + condition_evaluator +
声明式加载。骨架单测 (test_routes_workflows_scaffolding.py) 已覆盖 list/get/start
REST 入口; 本文件覆盖 S5 新增的真实执行链。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from isac.control.api import routes_workflows
from isac.runtime.workflow.actions import (
    build_default_action_handler,
    build_default_condition_evaluator,
)
from isac.runtime.workflow.engine import WorkflowEngine
from isac.runtime.workflow.loader import load_workflows_from_dir
from isac.runtime.workflow.models import Stage, TransitionKind

# ── action_handler ────────────────────────────────────────────────


class _FakeInstance:
    """最小 AgentInstance stub (持有 tools + services)。"""

    def __init__(self, tools: Any, services: dict | None = None) -> None:
        self.tools = tools
        self.services = services or {}


class _FakeTools:
    """记录 execute 调用 + 返回可控 ToolResult。"""

    def __init__(self, *, error: bool = False, content: str = "ok") -> None:
        self._error = error
        self._content = content
        self.calls: list[Any] = []

    async def execute(self, tool_call: Any, ctx: Any, services: Any) -> Any:
        self.calls.append({"tool_call": tool_call, "ctx": ctx, "services": services})

        class _Result:
            is_error = self._error
            content = self._content

        return _Result()


class _FakeAgentManager:
    """按 agent_id 返回预设 AgentInstance。"""

    def __init__(self, instances: dict[str, _FakeInstance]) -> None:
        self._instances = instances

    async def get(self, agent_id: str) -> _FakeInstance | None:
        return self._instances.get(agent_id)


@pytest.mark.asyncio
async def test_action_handler_tool_prefix_invokes_registry() -> None:
    """tool:<name> 前缀 → 经 agent_manager.get 取 ToolRegistry.execute。"""
    tools = _FakeTools()
    instance = _FakeInstance(tools=tools, services={"k": "v"})
    mgr = _FakeAgentManager({"a1": instance})
    handler = build_default_action_handler(mgr)
    stage = Stage(
        stage_id="s1", action="tool:web_search",
        params={"agent_id": "a1", "query": "hello"},
    )
    await handler(stage)
    assert len(tools.calls) == 1
    call = tools.calls[0]
    assert call["tool_call"].name == "web_search"
    assert call["tool_call"].arguments == {"agent_id": "a1", "query": "hello"}
    assert call["services"] == {"k": "v"}


@pytest.mark.asyncio
async def test_action_handler_tool_failure_raises_to_trigger_retry() -> None:
    """tool 调用返回 is_error=True → 抛异常让 Stage 走重试 (非 noop)。"""
    tools = _FakeTools(error=True, content="boom")
    instance = _FakeInstance(tools=tools)
    mgr = _FakeAgentManager({"a1": instance})
    handler = build_default_action_handler(mgr)
    stage = Stage(stage_id="s1", action="tool:web_search", params={"agent_id": "a1"})
    with pytest.raises(RuntimeError, match="boom"):
        await handler(stage)


@pytest.mark.asyncio
async def test_action_handler_tool_missing_agent_id_raises() -> None:
    """tool: 前缀但缺 agent_id → 抛 ValueError (明确失败)。"""
    mgr = _FakeAgentManager({})
    handler = build_default_action_handler(mgr)
    stage = Stage(stage_id="s1", action="tool:foo", params={})
    with pytest.raises(ValueError, match="agent_id"):
        await handler(stage)


@pytest.mark.asyncio
async def test_action_handler_tool_unknown_agent_raises() -> None:
    """tool: 前缀但 agent 不存在 → 抛 ValueError。"""
    mgr = _FakeAgentManager({})
    handler = build_default_action_handler(mgr)
    stage = Stage(stage_id="s1", action="tool:foo", params={"agent_id": "no-such"})
    with pytest.raises(ValueError, match="不存在"):
        await handler(stage)


@pytest.mark.asyncio
async def test_action_handler_unknown_prefix_is_noop() -> None:
    """未知前缀 (非 tool:/agent:) → 记 warning, 不抛异常 (避免重试)。"""
    mgr = _FakeAgentManager({})
    handler = build_default_action_handler(mgr)
    stage = Stage(stage_id="s1", action="weird:foo", params={})
    await handler(stage)  # 不抛异常


@pytest.mark.asyncio
async def test_action_handler_empty_action_is_noop() -> None:
    """空 action → noop。"""
    mgr = _FakeAgentManager({})
    handler = build_default_action_handler(mgr)
    stage = Stage(stage_id="s1", action="", params={})
    await handler(stage)


@pytest.mark.asyncio
async def test_action_handler_agent_prefix_is_noop_p5_decision() -> None:
    """agent: 前缀 → noop (P5 决策项, 有意未实现真实路由)。"""
    mgr = _FakeAgentManager({})
    handler = build_default_action_handler(mgr)
    stage = Stage(stage_id="s1", action="agent:a1:notify", params={})
    await handler(stage)  # 不抛异常


# ── condition_evaluator ──────────────────────────────────────────


def test_condition_evaluator_true_values() -> None:
    ev = build_default_condition_evaluator()
    assert ev("") is True
    assert ev("true") is True
    assert ev("TRUE") is True
    assert ev("1") is True
    assert ev("yes") is True


def test_condition_evaluator_false_values() -> None:
    ev = build_default_condition_evaluator()
    assert ev("false") is False
    assert ev("0") is False
    assert ev("no") is False
    assert ev("anything_else") is False  # 未识别字符串保守为 False


# ── loader ────────────────────────────────────────────────────────


def test_loader_loads_valid_workflow_files(tmp_path: Path) -> None:
    """合法 JSON 文件 → engine.register 成功; 返回加载数。"""
    wf_path = tmp_path / "wf1.json"
    wf_path.write_text(json.dumps({
        "workflow_id": "wf1",
        "name": "示例",
        "stages": [
            {"stage_id": "s1", "action": "tool:foo", "params": {"agent_id": "a1"}},
            {"stage_id": "s2", "action": "noop"},
        ],
        "transitions": [
            {"from_stage": "s1", "to_stage": "s2", "kind": "sequential"}
        ],
    }), encoding="utf-8")
    engine = WorkflowEngine(base_dir=str(tmp_path))
    loaded = load_workflows_from_dir(engine, str(tmp_path))
    assert loaded == 1
    assert [w.workflow_id for w in engine.list_workflows()] == ["wf1"]
    wf = engine.get("wf1")
    assert wf and len(wf.stages) == 2
    assert wf.transitions[0].kind is TransitionKind.SEQUENTIAL


def test_loader_skips_invalid_files(tmp_path: Path) -> None:
    """非法 JSON / 缺 workflow_id → 跳过; 不阻塞其余文件加载。"""
    (tmp_path / "bad.json").write_text("not-json", encoding="utf-8")
    (tmp_path / "no_id.json").write_text(json.dumps({"name": "缺 id"}), encoding="utf-8")
    good_path = tmp_path / "good.json"
    good_path.write_text(json.dumps({
        "workflow_id": "good", "stages": [{"stage_id": "s1", "action": "noop"}],
    }), encoding="utf-8")
    engine = WorkflowEngine(base_dir=str(tmp_path))
    loaded = load_workflows_from_dir(engine, str(tmp_path))
    assert loaded == 1  # 只有 good 被加载
    assert engine.get("good") is not None


def test_loader_nonexistent_dir_returns_zero(tmp_path: Path) -> None:
    """目录不存在 → 返回 0, 不抛异常。"""
    engine = WorkflowEngine(base_dir=str(tmp_path))
    assert load_workflows_from_dir(engine, str(tmp_path / "nope")) == 0


# ── 端到端: 声明式加载 + 控制面 start 真实执行 ─────────────────────


@pytest.mark.asyncio
async def test_declarative_workflow_start_runs_tool(tmp_path: Path) -> None:
    """声明式加载的工作流经控制面 start → 真实执行 tool: action → succeeded。"""
    wf_path = tmp_path / "wf.json"
    wf_path.write_text(json.dumps({
        "workflow_id": "wf_e2e", "name": "端到端",
        "stages": [
            {"stage_id": "s1", "action": "tool:web_search",
             "params": {"agent_id": "a1", "query": "hello"}},
        ],
        "transitions": [],
    }), encoding="utf-8")
    engine = WorkflowEngine(base_dir=str(tmp_path))
    engine.set_action_handler(build_default_action_handler(_FakeAgentManager({
        "a1": _FakeInstance(tools=_FakeTools()),
    })))
    engine.set_condition_evaluator(build_default_condition_evaluator())
    loaded = load_workflows_from_dir(engine, str(tmp_path))
    assert loaded == 1
    # 经控制面路由 start
    app = FastAPI()
    router = routes_workflows.build_router(engine)
    assert router is not None
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)
    resp = client.post("/api/v1/workflows/wf_e2e/start")
    assert resp.status_code == 200
    assert resp.json()["status"] == "succeeded"
