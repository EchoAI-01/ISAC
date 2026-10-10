"""R1 多模态出入站闭环测试: ⑤能力字段 + ③record_* + ④pricing + ①get_ref/_send_reply + ②入站下载。"""

from __future__ import annotations

import pytest

from isac.gateway.incoming_media import download_inbound_media
from isac.observability.usage.pricing import PricingCatalog

# ── ⑤ AgentConfig.model_capabilities_allow + assembly 条件注册 ─────────


def test_agent_config_has_model_capabilities_allow_default() -> None:
    """R1-⑤: AgentConfig 默认 model_capabilities_allow=["*"] (向后兼容)。"""
    from isac.runtime.config import AgentConfig

    cfg = AgentConfig(agent_id="a1")
    assert cfg.model_capabilities_allow == ["*"]


def test_assembly_registers_all_media_tools_default() -> None:
    """R1-⑤: 默认 ["*"] 全部媒体工具注册 (直接测 _register_media_tools helper)。"""
    from isac.agent.tools.registry import ToolRegistry
    from isac.runtime.assembly import _register_media_tools
    from isac.runtime.config import AgentConfig

    cfg = AgentConfig(agent_id="caps_all")
    tools = ToolRegistry()
    _register_media_tools(cfg, tools)
    names = set(tools._tools.keys())
    assert "generate_image" in names
    assert "understand_image" in names


def test_assembly_conditional_media_tools() -> None:
    """R1-⑤: model_capabilities_allow 子集只注册授权工具。"""
    from isac.agent.tools.registry import ToolRegistry
    from isac.runtime.assembly import _register_media_tools
    from isac.runtime.config import AgentConfig

    cfg = AgentConfig(agent_id="caps_subset", model_capabilities_allow=["transcribe_audio"])
    tools = ToolRegistry()
    _register_media_tools(cfg, tools)
    names = set(tools._tools.keys())
    assert "transcribe_audio" in names
    assert "generate_image" not in names  # 未授权


# ── ④ PricingCatalog.load ───────────────────────────────


def test_pricing_load_nonexistent_returns_empty(tmp_path: object) -> None:
    """R1-④: 文件不存在返回空 catalog (不 raise)。"""
    cat = PricingCatalog.load(str(tmp_path) + "/nope.jsonc")  # type: ignore[operator]
    assert cat.lookup("x", "y", "text") is None


def test_pricing_load_parses_jsonc(tmp_path: object) -> None:
    """R1-④: jsonc → PriceSnapshot, lookup 命中。"""
    p = tmp_path  # type: ignore[assignment]
    (p / "p.jsonc").write_text(
        '{"version":"v1","snapshots":[{"provider":"openai","model":"gpt-4o-mini",'
        '"modality":"text","input_price_per_unit":"0.00015"}]}',
        encoding="utf-8",
    )
    cat = PricingCatalog.load(p / "p.jsonc")
    snap = cat.lookup("openai", "gpt-4o-mini", "text")
    assert snap is not None
    assert snap.input_price_per_unit == "0.00015"


def test_shipped_pricing_jsonc_loads_non_empty() -> None:
    """2026-08-19 发货面回归: 随包 data/pricing.jsonc 必须存在且可加载出非空目录。

    此前该文件从未提交 (.gitignore data/* 排除), fresh 部署 PricingCatalog 恒空、
    estimated_cost 一律 None。现锁定"入仓 + 可加载 + 至少含 LLM 主链路一条"。
    """
    from pathlib import Path

    shipped = Path(__file__).resolve().parent.parent.parent / "data" / "pricing.jsonc"
    assert shipped.exists(), "data/pricing.jsonc 未随包 (成本计量开箱失效)"
    cat = PricingCatalog.load(shipped)
    # 至少登记了 OpenAI 兼容主链路的一个文本模型 (provider 键为类名口径)
    assert cat.lookup("OpenAICompatProvider", "gpt-4o-mini", "text") is not None


def test_pricing_load_malformed_returns_empty(tmp_path: object) -> None:
    """R1-④: 解析失败返回空 catalog (不 raise)。"""
    p = tmp_path  # type: ignore[assignment]
    (p / "bad.jsonc").write_text("{ not valid json", encoding="utf-8")
    cat = PricingCatalog.load(p / "bad.jsonc")
    assert cat.lookup("a", "b", "c") is None


# ── ① ArtifactStore.get_ref ─────────────────────────────


@pytest.mark.asyncio
async def test_artifact_store_get_ref(tmp_path: object) -> None:
    """R1-①: put 后 get_ref 返回含 kind/mime/uri 的 ArtifactRef。"""
    from isac.artifacts.store import ArtifactStore

    store = ArtifactStore(str(tmp_path) + "/store")  # type: ignore[operator]
    ref = await store.put(b"\x89PNGfake", kind="image", mime_type="image/png")
    got = await store.get_ref(ref.artifact_id)
    assert got is not None
    assert got.kind == "image"
    assert got.mime_type == "image/png"
    assert got.uri  # 非空


@pytest.mark.asyncio
async def test_artifact_store_get_ref_nonexistent(tmp_path: object) -> None:
    """R1-①: 不存在的 artifact_id 返回 None。"""
    from isac.artifacts.store import ArtifactStore

    store = ArtifactStore(str(tmp_path) + "/store")  # type: ignore[operator]
    assert await store.get_ref("0" * 64) is None


# ── ① _format_artifact_refs 完整 id ─────────────────────


def test_format_artifact_refs_full_id() -> None:
    """R1-①: _format_artifact_refs 输出完整 64 位 id (非 [:12] 截断)。"""
    from isac.agent.tools.media import _format_artifact_refs
    from isac.artifacts.models import ArtifactRef

    ref = ArtifactRef(artifact_id="a" * 64, kind="image")
    text = _format_artifact_refs([ref])
    assert "artifact:" + "a" * 64 in text  # 完整 id


# ── ② download_inbound_media ────────────────────────────


@pytest.mark.asyncio
async def test_download_inbound_media(tmp_path: object) -> None:
    """R1-②: 扫 segment url HTTP 下载落 ArtifactStore + 回填 media_uri。"""
    from isac.artifacts.store import ArtifactStore
    from isac.channel.model import ISACMessage, MessageSegment

    store = ArtifactStore(str(tmp_path) + "/up")  # type: ignore[operator]

    class _FakeClient:
        async def get_bytes(self, url: str) -> bytes:
            return b"\x89PNGfake"

    msg = ISACMessage(
        msg_id="m", platform="onebot", timestamp=0, user_id="u", user_name="u",
        group_id=None, content="看这张图",
    )
    msg.segments = [MessageSegment(type="image", data={"url": "http://1.1.1.1/img.png"})]
    n = await download_inbound_media(msg, store, http_client=_FakeClient())
    assert n == 1
    assert msg.segments[0].data["media_uri"]  # 回填


@pytest.mark.asyncio
async def test_download_inbound_media_ssrf_rejected(tmp_path: object) -> None:
    """R1-②: SSRF 内网 URL 跳过 (不下载)。"""
    from isac.artifacts.store import ArtifactStore
    from isac.channel.model import ISACMessage, MessageSegment

    store = ArtifactStore(str(tmp_path) + "/up")  # type: ignore[operator]
    msg = ISACMessage(
        msg_id="m", platform="onebot", timestamp=0, user_id="u", user_name="u",
        group_id=None, content="x",
    )
    msg.segments = [MessageSegment(type="image", data={"url": "http://192.168.1.1/x.png"})]
    n = await download_inbound_media(msg, store, http_client=object())  # http_client 不会被调
    assert n == 0
    assert "media_uri" not in msg.segments[0].data


@pytest.mark.asyncio
async def test_download_inbound_media_no_store() -> None:
    """R1-②: artifact_store 为 None 时直接返回 0 (未启用, 零行为变化)。"""
    from isac.channel.model import ISACMessage, MessageSegment

    msg = ISACMessage(msg_id="m", platform="x", timestamp=0, user_id="u", user_name="u", group_id=None, content="x")
    msg.segments = [MessageSegment(type="image", data={"url": "http://1.1.1.1/x.png"})]
    assert await download_inbound_media(msg, None) == 0


# ── ③ record_* 接线 (media tools) ──────────────────────


@pytest.mark.asyncio
async def test_media_tool_records_usage() -> None:
    """R1-③: _MediaToolBase.execute 成功后调对应 record_* (传 provider/model)。"""
    from isac.agent.tools.base import ToolContext
    from isac.agent.tools.media import GenerateImageTool
    from isac.channel.model import ISACMessage
    from isac.core.types import AgentContext
    from isac.gateway.models import Session

    calls: list[tuple] = []

    class _Rec:
        def record_image_gen(self, **kw):
            calls.append(("image_gen", kw))

    class _Sel:
        class descriptor:
            provider_id = "openai"
            model_id = "dall-e-3"

    class _Router:
        def select(self, **_):
            return _Sel()

    class _PM:
        def multimodal_provider(self, *a):
            return None  # 触发 _NO_PROVIDER, 不计 (前置失败)

    # 用 mock 让 provider 非 None → 调 _call_provider → _NOT_WIRED (is_error) → 不计
    # 改为 provider 返回非 None 但 _call_provider 返回成功 ToolResult
    class _PM2:
        def multimodal_provider(self, *a):
            class _P:
                async def generate(self, *a, **kw):
                    from isac.artifacts.models import ArtifactRef
                    return [ArtifactRef(artifact_id="b" * 64, kind="image")]

            return _P()

    session = Session(session_id="s", user_id="u", agent_id="agent1")
    msg = ISACMessage(msg_id="m", platform="x", timestamp=0, user_id="u", user_name="u", group_id=None, content="")
    ctx = ToolContext(
        args={},
        agent_context=AgentContext(session=session, user_profile=None, current_message=msg),
        services={
            "model_router": _Router(), "provider_manager": _PM2(),
            "artifact_store": None, "usage_recorder": _Rec(),
        },
    )
    # GenerateImageTool._call_provider 调 provider.generate, 返回 ToolResult (artifact refs)
    await GenerateImageTool().execute(ctx)
    # 成功 → 应计 record_image_gen
    assert len(calls) == 1
    assert calls[0][1]["model"] == "dall-e-3"
    # H4: provider 键统一为实例类名 (此处为 _PM2.multimodal_provider 内的 _P),
    # 不再是 descriptor.provider_id "openai"。
    assert calls[0][1]["provider"] == "_P"


# ── helpers ─────────────────────────────────────────────


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)
