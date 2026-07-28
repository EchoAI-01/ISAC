"""Workflow 控制面路由骨架单测 (S5, O3/P5)。

验证 routes_workflows.build_router: workflow_engine=None 时返回 None (不挂载);
注入 engine 时 list/get/start 三个 REST 入口按 WorkflowEngine 真实 API 工作
(未知 id → 404; start 真实调用 engine.start 并回传状态)。无 auth/scope 依赖时
路由开放 (与其他控制面路由的无认证回归一致)。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from isac.control.api import routes_workflows
from isac.runtime.workflow.engine import WorkflowEngine
from isac.runtime.workflow.models import Stage, Workflow


def test_build_router_none_engine_returns_none() -> None:
    assert routes_workflows.build_router(None) is None


def _engine_with_workflow(tmp_path: Any) -> WorkflowEngine:
    engine = WorkflowEngine(base_dir=str(tmp_path))

    async def _noop_action(stage: Stage) -> None:
        return None

    engine.set_action_handler(_noop_action)
    engine.register(Workflow(workflow_id="wf1", name="示例", stages=[Stage(stage_id="s1", action="noop")]))
    return engine


def _client(engine: WorkflowEngine) -> TestClient:
    app = FastAPI()
    router = routes_workflows.build_router(engine)
    assert router is not None
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_list_workflows(tmp_path: Any) -> None:
    client = _client(_engine_with_workflow(tmp_path))
    resp = client.get("/api/v1/workflows")
    assert resp.status_code == 200
    body = resp.json()
    assert [w["workflow_id"] for w in body] == ["wf1"]
    assert body[0]["stages"] == 1


def test_get_workflow_found_and_not_found(tmp_path: Any) -> None:
    client = _client(_engine_with_workflow(tmp_path))
    assert client.get("/api/v1/workflows/wf1").status_code == 200
    assert client.get("/api/v1/workflows/nope").status_code == 404


def test_start_workflow(tmp_path: Any) -> None:
    client = _client(_engine_with_workflow(tmp_path))
    resp = client.post("/api/v1/workflows/wf1/start")
    assert resp.status_code == 200
    assert resp.json()["status"] == "succeeded"


def test_start_unknown_workflow_404(tmp_path: Any) -> None:
    client = _client(_engine_with_workflow(tmp_path))
    assert client.post("/api/v1/workflows/nope/start").status_code == 404


def test_failed_start_returns_error_and_audits_failure(tmp_path: Any) -> None:
    from isac.control.audit import AuditLog

    engine = WorkflowEngine(base_dir=str(tmp_path))

    async def _fail_action(stage: Stage) -> None:
        raise RuntimeError("boom")

    engine.set_action_handler(_fail_action)
    engine.register(Workflow(workflow_id="wf1", stages=[Stage(stage_id="s1", action="fail")]))
    audit = AuditLog()
    app = FastAPI()
    router = routes_workflows.build_router(engine, audit_log=audit)
    assert router is not None
    app.include_router(router, prefix="/api/v1")

    response = TestClient(app).post("/api/v1/workflows/wf1/start")

    assert response.status_code == 500
    entries = audit.query(action="start_workflow")
    assert len(entries) == 1
    assert entries[0]["status_code"] == 500


def test_engine_list_workflows_accessor(tmp_path: Any) -> None:
    """S5 为控制面新增的公开访问器返回全部已登记工作流。"""
    engine = _engine_with_workflow(tmp_path)
    assert [w.workflow_id for w in engine.list_workflows()] == ["wf1"]
