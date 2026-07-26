"""O1-O5 企业化骨架测试。

验证 O1 多租户 (TenantContext/TenantIsolationGuard passthrough)、O2 插件隔离
(IPCEnvelope/PluginIsolationHost)、O3 Workflow (契约/WorkflowEngine no-op)、
O4 平台模板 (TemplateAdapter)、O5 视频 Provider (generate NotImplementedError)
的契约与骨架安全行为。真实实现属各自节点, 本文件只覆盖骨架级行为。
"""

from __future__ import annotations

import pytest

from isac.channel.adapters.template import TemplateAdapter
from isac.plugin.isolation import IPCEnvelope, PluginIsolationHost
from isac.provider.video_gen import OpenAICompatVideoGenProvider
from isac.runtime.tenancy import TenantContext, TenantIsolationGuard
from isac.runtime.workflow import (
    Stage,
    Transition,
    TransitionKind,
    Workflow,
    WorkflowEngine,
    WorkflowStatus,
)

# ── O1: 多租户 ───────────────────────────────────────────────────


def test_tenant_context_defaults_to_single_tenant() -> None:
    ctx = TenantContext()
    assert ctx.is_default is True
    assert ctx.organization_id == "default" and ctx.tenant_id == "default"


def test_isolation_guard_passthrough_when_disabled() -> None:
    guard = TenantIsolationGuard()  # enabled=False
    ctx = TenantContext(organization_id="acme", tenant_id="t1")
    assert guard.namespace_for("mem:a1", ctx) == "mem:a1"  # 不加前缀
    assert guard.check_access("other_org", ctx) is True  # 恒放行


def test_isolation_guard_prefixes_when_enabled() -> None:
    guard = TenantIsolationGuard(enabled=True)
    ctx = TenantContext(organization_id="acme", tenant_id="t1")
    assert guard.namespace_for("mem:a1", ctx) == "acme:t1:mem:a1"
    # 默认租户即便启用也不加前缀
    assert guard.namespace_for("mem:a1", TenantContext()) == "mem:a1"


# ── O2: 插件进程隔离 ─────────────────────────────────────────────


def test_ipc_envelope_defaults() -> None:
    env = IPCEnvelope(kind="call", plugin_id="p1")
    assert env.payload == {} and env.correlation_id == ""


async def test_isolation_host_spawn_call_kill_roundtrip() -> None:
    """O2 已实现: spawn → call (echo) → kill 真实子进程生命周期."""
    host = PluginIsolationHost("p1")
    await host.spawn()
    assert host.is_alive is True
    env = IPCEnvelope(kind="call", plugin_id="p1", payload={"text": "hello"})
    result = await host.call(env)
    assert result.kind == "result"
    assert result.payload.get("echo") == "hello"
    await host.kill()
    assert host.is_alive is False


# ── O3: Workflow ────────────────────────────────────────────────


def test_workflow_contracts_and_enums() -> None:
    wf = Workflow(workflow_id="w1", name="demo", stages=[Stage(stage_id="s1", action="tool:x")])
    assert wf.status is WorkflowStatus.PENDING
    assert wf.stages[0].action == "tool:x"
    t = Transition(from_stage="s1", to_stage="s2")
    assert t.kind is TransitionKind.SEQUENTIAL


async def test_workflow_engine_register_and_noop_start() -> None:
    engine = WorkflowEngine()
    wf = Workflow(workflow_id="w1")
    engine.register(wf)
    assert engine.get("w1") is wf
    assert await engine.start("w1") is WorkflowStatus.PENDING  # 骨架不推进
    assert await engine.start("missing") is WorkflowStatus.FAILED


# ── O4: 平台适配器模板 ───────────────────────────────────────────


async def test_template_adapter_instantiable_and_send_false() -> None:
    adapter = TemplateAdapter(platform="feishu")
    assert adapter.platform_name == "feishu"
    await adapter.start()  # no-op, 不抛
    await adapter.stop()
    # send 骨架返回 False (构造一个最小 ISACMessage)
    from isac.channel.model import ISACMessage

    msg = ISACMessage(msg_id="m1", platform="feishu", timestamp=0, user_id="u1", user_name="小明")
    assert await adapter.send(msg) is False


# ── O5: 视频 Provider ────────────────────────────────────────────


async def test_video_provider_generate_not_implemented() -> None:
    provider = OpenAICompatVideoGenProvider(api_base="https://x", api_key="k", model="v")
    with pytest.raises(NotImplementedError):
        await provider.generate("一只猫在弹钢琴")
