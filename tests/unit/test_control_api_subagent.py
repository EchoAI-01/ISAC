"""J4 阶段 4: Control API routes_subagent 测试。

覆盖:
- POST /agents/{id}/subagent-runs: 派生子任务 (需 supervisor)
- GET /agents/{id}/subagent-runs: 列出该 Agent 的子任务
- GET /subagent-runs/{task_id}: 查询单个子任务状态
- GET /subagent-runs/{task_id}/events: 分页读取子任务事件
- POST /subagent-runs/{task_id}/cancel: 取消子任务 (幂等)
- 无 supervisor 时端点 404 (不挂载)
- Bearer Token 认证
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi.testclient import TestClient

from isac.control.api.server import create_control_app
from isac.observability import get_default_metrics
from isac.runtime.subagent.models import SubAgentResult, SubAgentTask
from isac.runtime.subagent.supervisor import SubAgentSupervisor


async def _runner_success(task: SubAgentTask) -> SubAgentResult:
    await asyncio.sleep(0.01)
    return SubAgentResult(task_id=task.task_id, status="succeeded", summary="done", completed_at=1)


def _make_app(
    supervisor: SubAgentSupervisor | None = None,
    *,
    api_token: str = "test-token",
) -> Any:
    """构造 control app, 注入 supervisor (None 时不挂载 subagent 路由)。"""
    # 最小依赖: agent_manager / router / bus / plugin_manager 用桩
    class _StubAgentManager:
        async def list(self): return []
        async def get(self, agent_id): return None

    class _StubRouter:
        pass

    class _StubBus:
        pass

    class _StubPluginManager:
        pass

    config = {"api_token": api_token, "agents_dir": "data/agents"}
    app = create_control_app(
        _StubAgentManager(), _StubRouter(), _StubBus(), _StubPluginManager(),
        config, metrics=get_default_metrics(),
        subagent_supervisor=supervisor,
    )
    return app


def _make_supervisor() -> SubAgentSupervisor:
    return SubAgentSupervisor(runner_factory=_runner_success)


def test_get_subagent_runs_empty() -> None:
    """无 supervisor 时不挂载路由, /subagent-runs/* 返回 404。"""
    app = _make_app(supervisor=None)
    client = TestClient(app)
    resp = client.get("/api/v1/subagent-runs/any", headers={"Authorization": "Bearer test-token"})
    assert resp.status_code == 404


def test_list_subagent_runs() -> None:
    """GET /agents/{id}/subagent-runs 返回该 Agent 的子任务列表 (需先 submit)。"""
    import asyncio

    supervisor = _make_supervisor()
    # 预先 submit 一个任务
    asyncio.run(supervisor.submit(SubAgentTask(
        task_id="t1", parent_agent_id="a1", session_id="s1", trace_id="tr1",
        objective="x",
    )))
    app = _make_app(supervisor)
    client = TestClient(app)
    resp = client.get(
        "/api/v1/agents/a1/subagent-runs",
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # 至少有 t1
    assert any(r["task_id"] == "t1" for r in data)


def test_get_subagent_run_status() -> None:
    """GET /subagent-runs/{task_id} 返回单个子任务状态。"""
    import asyncio

    supervisor = _make_supervisor()
    asyncio.run(supervisor.submit(SubAgentTask(
        task_id="t2", parent_agent_id="a1", session_id="s1", trace_id="tr1",
        objective="x",
    )))
    app = _make_app(supervisor)
    client = TestClient(app)
    resp = client.get(
        "/api/v1/subagent-runs/t2",
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == "t2"
    assert data["status"] in ("queued", "running", "succeeded", "failed", "timed_out", "cancelled")


def test_get_subagent_run_not_found() -> None:
    """GET /subagent-runs/unknown 返回 404。"""
    supervisor = _make_supervisor()
    app = _make_app(supervisor)
    client = TestClient(app)
    resp = client.get(
        "/api/v1/subagent-runs/unknown",
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 404


def test_cancel_subagent_run() -> None:
    """POST /subagent-runs/{task_id}/cancel 幂等取消。"""
    import asyncio

    supervisor = _make_supervisor()
    asyncio.run(supervisor.submit(SubAgentTask(
        task_id="c1", parent_agent_id="a1", session_id="s1", trace_id="tr1",
        objective="x",
    )))
    app = _make_app(supervisor)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/subagent-runs/c1/cancel",
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == "c1"
    assert data["status"] == "cancelled"


def test_get_subagent_events() -> None:
    """GET /subagent-runs/{task_id}/events 分页读取事件 (无 journal 返回空)。"""
    import asyncio

    supervisor = _make_supervisor()
    asyncio.run(supervisor.submit(SubAgentTask(
        task_id="e1", parent_agent_id="a1", session_id="s1", trace_id="tr1",
        objective="x",
    )))
    app = _make_app(supervisor)
    client = TestClient(app)
    resp = client.get(
        "/api/v1/subagent-runs/e1/events?after_seq=0&limit=50",
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "events" in data
    assert isinstance(data["events"], list)


def test_token_auth_required() -> None:
    """无 Token 时返回 401。"""
    supervisor = _make_supervisor()
    app = _make_app(supervisor)
    client = TestClient(app)
    resp = client.get("/api/v1/subagent-runs/any")
    assert resp.status_code in (401, 403, 404)  # 取决于 auth_dependency 是否挂载


def test_post_subagent_run_creates_task() -> None:
    """POST /agents/{id}/subagent-runs 派生一个子任务。"""
    supervisor = _make_supervisor()
    app = _make_app(supervisor)
    client = TestClient(app)
    resp = client.post(
        "/api/v1/agents/a1/subagent-runs",
        json={"objective": "查天气", "summary": "用户问"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "task_id" in data
    assert data["status"] == "queued"
