"""R2 控制面与 SubAgent 收尾测试。

覆盖六子项: ① GET /agents/{id}/config + ② GET /subagent-runs list-all + ③ routes_webhooks
+ ⑤ ContextEnvelopeBuilder 真传 + ⑥ evidence_refs 生成。④ mcp 5 工具在 test_mcp_server.py。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from isac.control.webhooks import WebhookManager

# ── ① GET /agents/{id}/config ───────────────────────────────


@dataclass
class _FakeInstance:
    agent_id: str
    status: str = "running"
    config: Any = None


class _FakeAgentManager:
    def __init__(self, instances: dict[str, _FakeInstance]):
        self._instances = instances

    async def get(self, agent_id: str) -> _FakeInstance | None:
        return self._instances.get(agent_id)

    async def list(self) -> list[_FakeInstance]:
        return list(self._instances.values())


def _make_agents_app(agent_manager: Any) -> Any:
    from isac.control.api.server import create_control_app
    from isac.observability import get_default_metrics

    config = {"api_token": "t", "agents_dir": "data/agents"}
    return create_control_app(
        agent_manager, type("R", (), {})(), type("B", (), {})(), type("P", (), {})(),
        config, metrics=get_default_metrics(),
    )


def test_get_agent_config_returns_full_config_with_revision() -> None:
    """R2-①: GET /agents/{id}/config 返回 asdict(config) 含真实 revision。"""
    from isac.runtime.config import AgentConfig

    cfg = AgentConfig(agent_id="a1", display_name="A1", revision=7)
    am = _FakeAgentManager({"a1": _FakeInstance("a1", config=cfg)})
    from fastapi.testclient import TestClient

    client = TestClient(_make_agents_app(am))
    resp = client.get("/api/v1/agents/a1/config", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_id"] == "a1"
    assert data["revision"] == 7  # 真实 revision (非硬编码 1)
    assert data["display_name"] == "A1"


def test_get_agent_config_not_found() -> None:
    """R2-①: Agent 不存在返回 404。"""
    am = _FakeAgentManager({})
    from fastapi.testclient import TestClient

    client = TestClient(_make_agents_app(am))
    resp = client.get("/api/v1/agents/nope/config", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 404


# ── ② GET /subagent-runs list-all ──────────────────────────


def test_list_all_subagent_runs() -> None:
    """R2-②: GET /subagent-runs 返回全部子任务 (无 parent_agent_id 过滤)。"""
    import asyncio

    from isac.control.api.server import create_control_app
    from isac.observability import get_default_metrics
    from isac.runtime.subagent.models import SubAgentTask
    from isac.runtime.subagent.supervisor import SubAgentSupervisor

    async def _runner(task: Any) -> Any:
        from isac.runtime.subagent.models import SubAgentResult

        return SubAgentResult(task_id=task.task_id, status="succeeded", summary="ok", completed_at=1)

    supervisor = SubAgentSupervisor(runner_factory=_runner)
    asyncio.run(supervisor.submit(SubAgentTask(
        task_id="t1", parent_agent_id="a1", session_id="s", trace_id="tr", objective="x",
    )))

    class _StubAM:
        async def list(self): return []
        async def get(self, x): return None

    app = create_control_app(
        _StubAM(), type("R", (), {})(), type("B", (), {})(), type("P", (), {})(),
        {"api_token": "t"}, metrics=get_default_metrics(), subagent_supervisor=supervisor,
    )
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/api/v1/subagent-runs", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["task_id"] == "t1"


# ── ③ routes_webhooks ───────────────────────────────────────


def _make_webhook_app(wm: WebhookManager) -> Any:
    from isac.control.api.server import create_control_app
    from isac.observability import get_default_metrics

    return create_control_app(
        type("A", (), {"list": lambda self: [], "get": lambda self, x: None})(),
        type("R", (), {})(), type("B", (), {})(), type("P", (), {})(),
        {"api_token": "t"}, metrics=get_default_metrics(), webhook_manager=wm,
    )


def test_webhook_subscribe_and_list() -> None:
    """R2-③: POST /webhooks 订阅 (带 SSRF 校验, 测试用 mock http_client 跳过 DNS)。

    Fix-80: 旧事件名订阅按 CONTROL_PLANE_SPEC §5.1 目录归一 (post_message →
    message.responded), 清单以规范名呈现。
    """
    import httpx

    # 注入 mock http_client 跳过 DNS 解析 (允许测试域名)
    wm = WebhookManager(http_client=httpx.AsyncClient())
    from fastapi.testclient import TestClient

    client = TestClient(_make_webhook_app(wm))
    resp = client.post("/api/v1/webhooks", json={"event": "post_message", "url": "https://example.com/hook"},
                       headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "subscribed"
    # list (规范名呈现)
    resp = client.get("/api/v1/webhooks", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    assert resp.json()["message.responded"] == ["https://example.com/hook"]


def test_webhook_subscribe_invalid_url_rejected() -> None:
    """R2-③: 非 http(s) scheme 被 SSRF 校验拒绝 (400)。"""
    wm = WebhookManager()  # 无 http_client → 严格 SSRF 校验
    from fastapi.testclient import TestClient

    client = TestClient(_make_webhook_app(wm))
    resp = client.post("/api/v1/webhooks", json={"event": "x", "url": "ftp://bad"},
                       headers={"Authorization": "Bearer t"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "WEBHOOK_REJECTED"


def test_webhook_trigger() -> None:
    """R2-③: POST /automation/trigger 手动触发事件推送。"""
    import httpx

    wm = WebhookManager(http_client=httpx.AsyncClient())
    wm.subscribe("test_event", "https://example.com/hook")
    from fastapi.testclient import TestClient

    client = TestClient(_make_webhook_app(wm))
    resp = client.post("/api/v1/automation/trigger", json={"event": "test_event", "data": {"k": "v"}},
                       headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    assert "delivered" in resp.json()


# ── ⑤ ContextEnvelopeBuilder 真传 + ⑥ evidence_refs ────────


@pytest.mark.asyncio
async def test_runner_passes_summary_envelope() -> None:
    """R2-⑤: runner 经 ContextEnvelopeBuilder 把 task.context.summary 拼进 LLM user message。"""
    from isac.runtime.subagent.context import ContextEnvelopeBuilder
    from isac.runtime.subagent.models import SubAgentPolicy, SubAgentTask

    task = SubAgentTask(
        task_id="t", parent_agent_id="a", session_id="s", trace_id="tr",
        objective="完成报告", context={"summary": "前情提要", "task_depth": 1},
        policy=SubAgentPolicy(),
    )
    envelope = ContextEnvelopeBuilder().build(task)
    assert envelope.summary == "前情提要"
    assert envelope.objective == "完成报告"
    # runner 用此构造 user_content: 有 summary 时拼 [背景]...[目标]...
    if envelope.summary:
        user_content = f"[背景] {envelope.summary}\n\n[目标] {envelope.objective}"
    else:
        user_content = envelope.objective
    assert "[背景] 前情提要" in user_content
    assert "[目标] 完成报告" in user_content


def test_collect_evidence_refs_extracts_artifact() -> None:
    """R2-⑥: _collect_evidence_refs 从结果 content 扫 artifact:<id> 引用。"""
    from isac.runtime.subagent.runner import _collect_evidence_refs

    class _R:
        content = "已生成图 artifact:art_abc123 与 artifact:art_def456"

    refs = _collect_evidence_refs(_R())
    assert refs == ["art_abc123", "art_def456"]


def test_collect_evidence_refs_empty_when_no_artifact() -> None:
    """R2-⑥: content 无 artifact 引用时返回空 list。"""
    from isac.runtime.subagent.runner import _collect_evidence_refs

    class _R:
        content = "纯文本结果, 无 artifact"

    assert _collect_evidence_refs(_R()) == []
