"""Q5 SubAgent usage/evidence 保留 + 并发上限 + WebUI 真实数据测试。

验证:
- SubAgentRun.usage / evidence_refs 此前被 _run_task 丢弃, 现在保留 (succeeded
  时落到 run 上, 控制面可读)
- SubAgentSupervisor.max_concurrent 信号量限制并发子任务数 (submit 超上限时
  新任务排队等待, 不是无界并发)
- routes_subagent list_subagent_runs 响应含 usage / evidence_refs 字段
- routes_plugins GET /plugins/loaded 返回 PluginManager.list_loaded() 真实数据
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from isac.core.types import TokenUsage
from isac.runtime.subagent.models import SubAgentPolicy, SubAgentResult, SubAgentTask
from isac.runtime.subagent.supervisor import SubAgentSupervisor


def _make_task(task_id: str = "t1", parent_agent_id: str = "a1") -> SubAgentTask:
    return SubAgentTask(
        task_id=task_id,
        parent_agent_id=parent_agent_id,
        session_id="s1",
        trace_id="t1",
        objective="test",
        context={"task_depth": 0},
        policy=SubAgentPolicy(max_tokens=1000, timeout_seconds=5, max_tool_calls=3, max_depth=3),
        created_at=0,
    )


# ── usage / evidence 保留 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_subagent_run_preserves_usage_and_evidence_refs_on_success() -> None:
    """Q5: SubAgentResult.usage 与 evidence_refs 此前被 _run_task 丢弃;
    现在保留到 SubAgentRun 上, 控制面 get_status / list_subagent_runs 能读到。"""
    expected_usage = TokenUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    expected_evidence = ["ref1", "ref2"]

    async def _runner(task: SubAgentTask) -> SubAgentResult:
        return SubAgentResult(
            task_id=task.task_id,
            status="succeeded",
            summary="完成",
            usage=expected_usage,
            evidence_refs=expected_evidence,
            completed_at=0,
        )

    supervisor = SubAgentSupervisor()
    supervisor.set_runner_factory(_runner)
    task = _make_task("q5_usage")
    await supervisor.submit(task)
    # 等后台 task 执行完
    bg_task = supervisor._tasks.get(task.task_id)  # type: ignore[attr-defined]
    if bg_task is not None:
        await asyncio.wait_for(bg_task, timeout=2.0)
    run = await supervisor.get_status(task.task_id)
    assert run is not None
    assert run.status == "succeeded"
    assert run.result_summary == "完成"
    assert run.usage == expected_usage  # Q5: 此前会被丢弃
    assert run.evidence_refs == expected_evidence  # Q5: 此前会被丢弃
    assert run.tokens_used == 150  # usage.total_tokens 自动落到 tokens_used


@pytest.mark.asyncio
async def test_subagent_run_without_usage_stays_default() -> None:
    """runner 返回的 SubAgentResult.usage 默认 TokenUsage(), 不影响 run 默认状态。"""
    async def _runner(task: SubAgentTask) -> SubAgentResult:
        return SubAgentResult(task_id=task.task_id, status="succeeded", summary="ok", completed_at=0)

    supervisor = SubAgentSupervisor()
    supervisor.set_runner_factory(_runner)
    task = _make_task("q5_default")
    await supervisor.submit(task)
    bg_task = supervisor._tasks.get(task.task_id)  # type: ignore[attr-defined]
    if bg_task is not None:
        await asyncio.wait_for(bg_task, timeout=2.0)
    run = await supervisor.get_status(task.task_id)
    assert run is not None
    assert run.usage is not None
    assert run.tokens_used == 0  # 默认 TokenUsage().total_tokens


# ── 并发上限 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subagent_supervisor_concurrency_limit_blocks_excess() -> None:
    """Q5: max_concurrent=2 时, 同时 submit 3 个任务, 第 3 个在信号量释放前
    不能进入 running 状态 (信号量 acquire 阻塞)。"""
    started: list[str] = []
    release = asyncio.Event()

    async def _runner(task: SubAgentTask) -> SubAgentResult:
        started.append(task.task_id)
        await release.wait()  # 持有信号量直到 release 被 set
        return SubAgentResult(task_id=task.task_id, status="succeeded", summary="ok", completed_at=0)

    # max_concurrent=2: 最多 2 个任务同时持有信号量
    supervisor = SubAgentSupervisor(max_concurrent=2)
    supervisor.set_runner_factory(_runner)
    tasks = [_make_task(f"q5_conc_{i}") for i in range(3)]
    for t in tasks:
        await supervisor.submit(t)
    # 等一小段时间让前两个 acquire + started
    await asyncio.sleep(0.1)
    assert len(started) == 2  # 第 3 个被信号量阻塞, 未启动
    # 释放信号量, 第 3 个开始
    release.set()
    for t in tasks:
        bg = supervisor._tasks.get(t.task_id)  # type: ignore[attr-defined]
        if bg is not None:
            await asyncio.wait_for(bg, timeout=2.0)
    assert len(started) == 3
    # 全部 succeeded
    for t in tasks:
        run = await supervisor.get_status(t.task_id)
        assert run is not None and run.status == "succeeded"


@pytest.mark.asyncio
async def test_subagent_supervisor_max_concurrent_zero_means_unlimited() -> None:
    """max_concurrent=0 表示不限制 (向后兼容默认行为)。"""
    started_count = 0

    async def _runner(task: SubAgentTask) -> SubAgentResult:
        nonlocal started_count
        started_count += 1
        return SubAgentResult(task_id=task.task_id, status="succeeded", summary="ok", completed_at=0)

    supervisor = SubAgentSupervisor(max_concurrent=0)
    supervisor.set_runner_factory(_runner)
    # 5 个任务同时 submit, 不应被信号量阻塞
    tasks = [_make_task(f"q5_unlim_{i}") for i in range(5)]
    for t in tasks:
        await supervisor.submit(t)
    for t in tasks:
        bg = supervisor._tasks.get(t.task_id)  # type: ignore[attr-defined]
        if bg is not None:
            await asyncio.wait_for(bg, timeout=2.0)
    assert started_count == 5
    assert supervisor._concurrency_sem is None  # type: ignore[attr-defined]


# ── routes_subagent list_subagent_runs 含 usage/evidence ──────────


@pytest.mark.asyncio
async def test_routes_subagent_list_returns_usage_and_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """Q5: GET /agents/{id}/subagent-runs 响应含 usage + evidence_refs 字段
    (此前只返回 tokens_used + result_summary, usage/evidence 被丢弃)。"""
    from isac.control.api import routes_subagent

    # 构造一个 fake supervisor 返回含 usage/evidence 的 SubAgentRun
    from isac.runtime.subagent.models import SubAgentRun

    fake_run = SubAgentRun(
        task_id="t_usage",
        status="succeeded",
        result_summary="done",
        tokens_used=200,
        usage=TokenUsage(prompt_tokens=120, completion_tokens=80, total_tokens=200),
        evidence_refs=["ref_a", "ref_b"],
    )

    class _FakeSupervisor:
        async def list_runs(self, agent_id: str = "", filters: dict | None = None) -> list[SubAgentRun]:
            return [fake_run]

        async def get_status(self, task_id: str, requester: Any = None) -> SubAgentRun | None:
            return fake_run if task_id == fake_run.task_id else None

    router = routes_subagent.build_router(_FakeSupervisor())  # type: ignore[arg-type]
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)
    resp = client.get("/api/v1/agents/a1/subagent-runs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list) and len(data) == 1
    item = data[0]
    assert item["result_summary"] == "done"
    assert item["tokens_used"] == 200
    assert item["evidence_refs"] == ["ref_a", "ref_b"]  # Q5 新增
    assert item["usage"]["total_tokens"] == 200  # Q5 新增
    assert item["usage"]["prompt_tokens"] == 120
    assert item["usage"]["completion_tokens"] == 80


# ── routes_plugins GET /plugins/loaded 真实数据 ──────────────────


def test_routes_plugins_loaded_returns_real_plugin_list() -> None:
    """Q5: GET /plugins/loaded 返回 PluginManager.list_loaded() 的真实数据
    (此前 WebUI 插件页是占位假数据)。"""
    from isac.control.api import routes_plugins

    class _FakePluginManager:
        def list_loaded(self) -> list[str]:
            return ["plugin_a", "plugin_b"]

        def is_isolated(self, name: str) -> bool:
            return name == "plugin_b"

    router = routes_plugins.build_loaded_plugins_router(_FakePluginManager())  # type: ignore[arg-type]
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app)
    resp = client.get("/api/v1/plugins/loaded")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    names = [p["name"] for p in data["plugins"]]
    assert names == ["plugin_a", "plugin_b"]
    isolated_flags = {p["name"]: p["isolated"] for p in data["plugins"]}
    assert isolated_flags["plugin_a"] is False
    assert isolated_flags["plugin_b"] is True
