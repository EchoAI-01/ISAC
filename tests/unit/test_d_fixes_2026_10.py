"""2026-10-11 审计批次 D1-D5 修复回归测试。

- D1 入站去重键缺会话维度: 跨会话同 msg_id 误吞;
- D2 tools_policy 非法档位 fail-open: 配置层覆盖值透传 execute 瀑布直接放行;
- D3 压缩 GC 与摘要输入不一致: 截断点后内容未进摘要却被物理删除;
- D4 压缩摘要排序错位: 摘要在自身 seq (末尾) 输出而非替代区间起始位置;
- D5 插件 reload 绕过 plugins_allow/deny: 运行中同步不查启用矩阵。
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from isac.agent.tools.base import ToolPermission, normalize_tool_level
from isac.agent.tools.registry import ToolRegistry
from isac.channel.model import ISACMessage
from isac.core.types import LLMResponse
from isac.gateway.inbound_dedup import InboundDeduplicator
from isac.session.compressor import SessionCompressor
from isac.session.event_store import SessionEventStore
from isac.session.history import SessionHistoryDeriver
from isac.session.models import (
    EVENT_TURN_COMPLETED,
    EVENT_TURN_COMPRESSED,
    EVENT_USER_MESSAGE,
    SessionEvent,
)

SESSION_KEY = "agent_a:fake:user:u1"


# ── D1: 去重键会话维度 ──────────────────────────────────────


def test_d1_same_msg_id_across_sessions_not_deduped() -> None:
    """Telegram/Discord msg_id 是 per-chat 独立序列: 跨会话同号必须是两条不同消息。"""
    dedup = InboundDeduplicator()
    assert dedup.is_duplicate("telegram", "12345", "chat_a") is False
    # B 会话同号消息不被 A 会话误吞 (修复前: 同 (platform, msg_id) 键 → 误判重复)。
    assert dedup.is_duplicate("telegram", "12345", "chat_b") is False


def test_d1_same_session_same_msg_id_still_deduped() -> None:
    """同会话内重复投递 (WS 重连/webhook 重试) 仍去重 —— 修复不破坏原有语义。"""
    dedup = InboundDeduplicator()
    assert dedup.is_duplicate("qq", "m1", "g1") is False
    assert dedup.is_duplicate("qq", "m1", "g1") is True


def test_d1_session_default_keeps_legacy_behavior() -> None:
    """session 缺省 "" 退化为旧行为 (同 platform+msg_id 判重), 兼容既有调用。"""
    dedup = InboundDeduplicator()
    assert dedup.is_duplicate("qq", "m1") is False
    assert dedup.is_duplicate("qq", "m1") is True


# ── D2: 配置层档位校验 fail-closed ───────────────────────────


def test_d2_normalize_tool_level() -> None:
    """档位归一: 合法四值原样; 未知值归 deny。"""
    for level in ("allow", "restricted", "ask", "deny"):
        assert normalize_tool_level(level) == level
    assert normalize_tool_level("alow") == "deny"  # 笔误
    assert normalize_tool_level("") == "deny"
    assert normalize_tool_level("ALLOW") == "deny"  # 大小写敏感


def test_d2_invalid_global_policy_level_fail_closed() -> None:
    """全局运维 tools_policy 写非法档位 → effective_policy 归 deny (修复前: 透传
    到 execute 瀑布不命中 ask/deny/restricted 任何分支 = 直接放行)。"""
    from isac.core.policy import EnableMatrix

    matrix = EnableMatrix(global_policy={"tools_policy": {"send_emoji": "alow"}})
    registry = ToolRegistry(ToolPermission(), enable_matrix=matrix)
    assert registry.effective_policy("send_emoji") == "deny"


def test_d2_invalid_agent_policy_level_fail_closed() -> None:
    """Agent 配置层非法档位同样归 deny (三层覆盖每层都过校验)。"""
    from isac.core.policy import EnableMatrix

    matrix = EnableMatrix(global_policy={})
    registry = ToolRegistry(ToolPermission({"send_emoji": "allow-all"}), enable_matrix=matrix)
    assert registry.effective_policy("send_emoji") == "deny"


def test_d2_valid_levels_still_pass_through() -> None:
    """合法档位正常覆盖 (修复不改变合法配置行为)。"""
    from isac.core.policy import EnableMatrix

    matrix = EnableMatrix(global_policy={"tools_policy": {"bash": "allow", "send_emoji": "ask"}})
    registry = ToolRegistry(ToolPermission(), enable_matrix=matrix)
    assert registry.effective_policy("bash") == "allow"
    assert registry.effective_policy("send_emoji") == "ask"


# ── D3: 压缩 GC 与摘要输入对齐 ───────────────────────────────


class _FixedLLM:
    """返回固定短摘要的 fake LLM。"""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def chat(self, system: str, messages: list[dict], tools: Any = None, **kw: Any) -> LLMResponse:
        self.prompts.append(str(messages[0]["content"]))
        return LLMResponse(content="双方敲定了方案。")


@pytest.fixture
async def store(tmp_path: Path) -> SessionEventStore:
    s = SessionEventStore(str(tmp_path / "session_events.db"))
    await s.start()
    yield s
    await s.stop()


@pytest.mark.asyncio
async def test_d3_gc_only_deletes_summarized_events(store: SessionEventStore) -> None:
    """输入超限时: 只 GC 实际进入摘要的事件, 截断点之后的事件保留 (修复前: 全量
    prefix 被 GC, 截断点后内容既不在摘要也被删 = 永久丢失)。"""
    ts = 1_700_000_000
    # 6 条内容事件 (keep_recent=2, min_compress=2 → prefix=4); input_max_chars 压到
    # 只容得下前 2 条 → 后 2 条 prefix 事件必须保留。
    for i in range(6):
        await store.append(SessionEvent(
            session_key=SESSION_KEY,
            event_type=EVENT_USER_MESSAGE if i % 2 == 0 else EVENT_TURN_COMPLETED,
            timestamp=ts + i,
            payload={"content": f"第{i}条内容, " + "很长" * 40},
        ))
    llm = _FixedLLM()
    comp = SessionCompressor(
        store, llm=llm, keep_recent_messages=2, min_compress_messages=2,
        input_max_chars=200,  # 每条 ~85 字符: 第 0/1 条加入后 ~170, 第 2 条将超限 → 只纳入 2 条。
    )
    result = await comp.compress_session(SESSION_KEY)
    assert result.skipped == ""
    assert result.compressed_events == 2  # 只有进入摘要的 2 条被替代
    # 截断点之后的 prefix 事件仍在事件流里 (未进摘要 → 不许删)。
    events = await store.fetch(SESSION_KEY, after_seq=0, limit=100)
    content_events = [e for e in events if e.event_type in (EVENT_USER_MESSAGE, EVENT_TURN_COMPLETED)]
    assert len(content_events) == 6 - 2  # 剩 4 条: 截断后保留 2 + 活跃窗口 2
    # LLM 收到的素材确实只有纳入的事件 (不含被截断者)。
    assert "第0条" in llm.prompts[0] and "第1条" in llm.prompts[0]
    assert "第2条" not in llm.prompts[0] and "第3条" not in llm.prompts[0]


@pytest.mark.asyncio
async def test_d3_single_oversize_event_skips_not_truncates(store: SessionEventStore) -> None:
    """首事件即超输入上限: 不截断提交 (半个事件都不截), 整轮跳过留待下轮。"""
    ts = 1_700_000_000
    for i in range(4):
        await store.append(SessionEvent(
            session_key=SESSION_KEY, event_type=EVENT_USER_MESSAGE, timestamp=ts + i,
            payload={"content": "超长" * 2000},
        ))
    comp = SessionCompressor(
        store, llm=_FixedLLM(), keep_recent_messages=2, min_compress_messages=2,
        input_max_chars=500,
    )
    result = await comp.compress_session(SESSION_KEY)
    # 纳入数 0 < min_compress → input_overflow 跳过, 事件一个不删。
    assert result.skipped == "input_overflow"
    events = await store.fetch(SESSION_KEY, after_seq=0, limit=100)
    assert len([e for e in events if e.event_type == EVENT_USER_MESSAGE]) == 4


# ── D4: 压缩摘要排序 ────────────────────────────────────────


def _ev(seq: int, event_type: str, payload: dict) -> SessionEvent:
    return SessionEvent(session_key=SESSION_KEY, event_type=event_type, timestamp=seq, seq=seq, payload=payload)


def test_d4_summary_inserted_at_replaced_range_start() -> None:
    """压缩摘要按替代区间起始位置输出 (修复前: 在 turn.compressed 自身 seq =
    分区末尾输出, LLM 把"很久以前的总结"当成最新发言)。"""
    events = [
        _ev(1, EVENT_USER_MESSAGE, {"content": "旧问题1"}),
        _ev(2, EVENT_TURN_COMPLETED, {"content": "旧回答1"}),
        _ev(3, EVENT_USER_MESSAGE, {"content": "新问题"}),
        _ev(4, EVENT_TURN_COMPLETED, {"content": "新回答"}),
        _ev(5, EVENT_TURN_COMPRESSED, {"summary": "旧对话摘要", "source_seqs": [1, 2]}),
    ]
    messages = SessionHistoryDeriver().fold(events)
    assert [m["content"] for m in messages] == ["旧对话摘要", "新问题", "新回答"]
    assert messages[0]["role"] == "assistant"


def test_d4_summary_after_gc_anchor_event_missing() -> None:
    """GC 已删被替代事件 (锚点 seq 无存活事件) —— 摘要仍按锚点位置输出在最前。"""
    # 模拟 GC 后存储: seq 1/2 已删, 存活 seq 3/4/5。
    events = [
        _ev(3, EVENT_USER_MESSAGE, {"content": "新问题"}),
        _ev(4, EVENT_TURN_COMPLETED, {"content": "新回答"}),
        _ev(5, EVENT_TURN_COMPRESSED, {"summary": "早期摘要", "source_seqs": [1, 2]}),
    ]
    messages = SessionHistoryDeriver().fold(events)
    assert [m["content"] for m in messages] == ["早期摘要", "新问题", "新回答"]


def test_d4_no_double_output_for_live_compressed_event() -> None:
    """未被新一轮替代的 compressed 事件只在锚点位置输出一次 (不在自身 seq 再输出)。"""
    events = [
        _ev(1, EVENT_USER_MESSAGE, {"content": "q1"}),
        _ev(2, EVENT_TURN_COMPRESSED, {"summary": "摘要A", "source_seqs": [1]}),
        _ev(3, EVENT_USER_MESSAGE, {"content": "q2"}),
    ]
    messages = SessionHistoryDeriver().fold(events)
    contents = [m["content"] for m in messages]
    assert contents.count("摘要A") == 1
    assert contents == ["摘要A", "q2"]


def test_d4_multiple_summaries_ordered_by_anchor() -> None:
    """多条摘要按锚点升序 (时序正确), 不按事件自身 seq。"""
    events = [
        _ev(1, EVENT_USER_MESSAGE, {"content": "q0"}),
        _ev(2, EVENT_USER_MESSAGE, {"content": "q1"}),
        _ev(5, EVENT_TURN_COMPRESSED, {"summary": "早期摘要", "source_seqs": [1]}),
        _ev(6, EVENT_TURN_COMPRESSED, {"summary": "后期摘要", "source_seqs": [2]}),
    ]
    messages = SessionHistoryDeriver().fold(events)
    assert [m["content"] for m in messages] == ["早期摘要", "后期摘要"]


# ── D5: 插件同步过启用矩阵 ──────────────────────────────────


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = "t"
        self.parameters: dict = {"type": "object", "properties": {}}

    async def execute(self, context: Any) -> Any:
        return None


class _Instance:
    agent_id = "a1"
    status = "running"

    def __init__(self, allow: list[str], deny: list[str]) -> None:
        self.tools = ToolRegistry()
        self.config = SimpleNamespace(plugins_allow=allow, plugins_deny=deny)
        self.commands = None
        self.prompt_builder = None


class _AgentManager:
    def __init__(self, instances: list) -> None:
        self._instances = instances

    async def list(self) -> list:
        return self._instances


@pytest.mark.asyncio
async def test_d5_denied_plugin_not_synced_back() -> None:
    """plugins_deny 的插件 reload 后不被灌回运行中 Agent (修复前: sync 绕过矩阵)。"""
    from isac.plugin.runtime.activation import sync_plugin_tools_to_agents

    shared = ToolRegistry()
    shared.register(_Tool("evil"), source="plug_evil")
    instance = _Instance(allow=["*"], deny=["plug_evil"])
    await sync_plugin_tools_to_agents(
        _AgentManager([instance]), {"plugin_tools": shared}, "plug_evil"
    )
    assert instance.tools.get("plug_evil:evil") is None


@pytest.mark.asyncio
async def test_d5_empty_allow_blocks_all_plugins() -> None:
    """受限默认 plugins_allow=[] (全禁) 的 Agent reload 后仍全禁。"""
    from isac.plugin.runtime.activation import sync_plugin_tools_to_agents

    shared = ToolRegistry()
    shared.register(_Tool("any"), source="plug_x")
    instance = _Instance(allow=[], deny=[])
    await sync_plugin_tools_to_agents(_AgentManager([instance]), {"plugin_tools": shared}, "plug_x")
    assert instance.tools.get("plug_x:any") is None


@pytest.mark.asyncio
async def test_d5_allowed_plugin_still_synced() -> None:
    """白名单内插件 reload 后正常同步 (修复不破坏正常热重载)。"""
    from isac.plugin.runtime.activation import sync_plugin_tools_to_agents

    shared = ToolRegistry()
    shared.register(_Tool("good"), source="plug_good")
    instance = _Instance(allow=["plug_good"], deny=[])
    await sync_plugin_tools_to_agents(
        _AgentManager([instance]), {"plugin_tools": shared}, "plug_good"
    )
    assert instance.tools.get("plug_good:good") is not None


@pytest.mark.asyncio
async def test_d5_full_sync_mode_respects_matrix() -> None:
    """全量同步模式 (plugin_name=None) 同样按来源逐插件过矩阵。"""
    from isac.plugin.runtime.activation import sync_plugin_tools_to_agents

    shared = ToolRegistry()
    shared.register(_Tool("a"), source="plug_a")
    shared.register(_Tool("b"), source="plug_b")
    instance = _Instance(allow=["plug_a"], deny=[])
    await sync_plugin_tools_to_agents(_AgentManager([instance]), {"plugin_tools": shared}, None)
    assert instance.tools.get("plug_a:a") is not None
    assert instance.tools.get("plug_b:b") is None


@pytest.mark.asyncio
async def test_d5_reload_denied_plugin_removes_stale_entries() -> None:
    """禁用插件的 reload: 先移除旧条目且不灌回 —— 从"残留旧版"收敛到"无条目"。"""
    from isac.plugin.runtime.activation import sync_plugin_tools_to_agents

    shared = ToolRegistry()
    shared.register(_Tool("stale"), source="plug_evil")
    instance = _Instance(allow=["*"], deny=["plug_evil"])
    # 预置历史遗留条目 (模拟修复前已被错误同步进去的旧版工具)。
    instance.tools.register(_Tool("stale"), source="plug_evil")
    assert instance.tools.get("plug_evil:stale") is not None
    await sync_plugin_tools_to_agents(
        _AgentManager([instance]), {"plugin_tools": shared}, "plug_evil"
    )
    assert instance.tools.get("plug_evil:stale") is None


# ── D6 (复审新增): 压缩触发阈值口径 ──────────────────────────


@pytest.mark.asyncio
async def test_d6_count_events_filters_by_type(store: SessionEventStore) -> None:
    """count_events(event_types=...) 只统计内容事件 —— 与 compressor 可压缩判定
    同口径 (修复前: 工具密集会话反复触发却恒 too_few 空转, 每次空转全量 fetch)。"""
    from isac.session.models import EVENT_TOOL_CALLED, EVENT_TOOL_OUTCOME

    ts = 1_700_000_000
    await store.append(SessionEvent(
        session_key=SESSION_KEY, event_type=EVENT_USER_MESSAGE, timestamp=ts,
        payload={"content": "q"},
    ))
    await store.append(SessionEvent(
        session_key=SESSION_KEY, event_type=EVENT_TURN_COMPLETED, timestamp=ts + 1,
        payload={"content": "a"},
    ))
    for i in range(5):
        await store.append(SessionEvent(
            session_key=SESSION_KEY, event_type=EVENT_TOOL_CALLED, timestamp=ts + 2 + i,
            payload={"tool": f"t{i}"},
        ))
        await store.append(SessionEvent(
            session_key=SESSION_KEY, event_type=EVENT_TOOL_OUTCOME, timestamp=ts + 3 + i,
            payload={"ok": True},
        ))
    total = await store.count_events(SESSION_KEY)
    content = await store.count_events(
        SESSION_KEY, event_types=[EVENT_USER_MESSAGE, EVENT_TURN_COMPLETED, "turn.compressed"]
    )
    assert total == 12  # 2 内容 + 10 工具
    assert content == 2  # 只数内容事件
    # 向后兼容: 不传 event_types 行为不变
    assert await store.count_events(SESSION_KEY, event_types=None) == 12


# ── D2 配置期 fail-fast (PATCH / validate 端点) ───────────────


def test_d2_validate_tool_policy_values() -> None:
    """值域校验单源函数: 合法通过 / 非法逐键报错 / 空值通过。"""
    from isac.agent.tools.base import validate_tool_policy_values

    assert validate_tool_policy_values(None) == []
    assert validate_tool_policy_values({}) == []
    assert validate_tool_policy_values({"bash": "allow", "send_emoji": "ask"}) == []
    errors = validate_tool_policy_values({"bash": "alow", "web_search": "maybe"})
    assert len(errors) == 2
    assert "bash" in errors[0] and "alow" in errors[0]


def test_d2_config_validate_endpoint_rejects_bad_policy() -> None:
    """POST /config/validate 对非法 tools_policy 档位报错 (配置期 fail-fast)。"""
    from isac.control.api.routes_config import _validate_agent_config_fields

    errors = _validate_agent_config_fields({
        "agent_id": "a1", "tools_policy": {"bash": "alow"},
    })
    assert any("tools_policy" in e for e in errors)
    ok = _validate_agent_config_fields({
        "agent_id": "a1", "tools_policy": {"bash": "allow"},
    })
    assert ok == []


# ── N5: reload_config MCP 连接差量复用 ──────────────────────


class _FakeMCPClient:
    """复用语义 fake: list_tools 可注入失败; connect/disconnect 计数。"""

    def __init__(self, name: str, fail: bool = False) -> None:
        self.server_name = name
        self._fail = fail
        self.disconnected = 0

    async def list_tools(self) -> list[Any]:
        if self._fail:
            raise RuntimeError("list_tools boom")

        class _B:
            def __init__(self, name: str) -> None:
                self.name = f"mcp:{name}:t1"
                self.description = "d"
                self.parameters: dict = {"type": "object", "properties": {}}

            async def execute(self, ctx: Any) -> Any:
                return None

        return [_B(self.server_name)]

    async def disconnect(self) -> None:
        self.disconnected += 1


@pytest.mark.asyncio
async def test_n5_mcp_reuse_success() -> None:
    """mcp_servers 未变 → 复用连接 (不 disconnect, bridge 重注册进新 registry)。"""
    from isac.runtime.assembly import _reuse_mcp_clients
    from isac.runtime.config import AgentConfig

    client = _FakeMCPClient("srv1")
    tools = ToolRegistry()
    reused = await _reuse_mcp_clients(AgentConfig(agent_id="a1"), tools, [client])
    assert reused is not None and reused[0] is client
    assert client.disconnected == 0  # 未重连未断开
    assert tools.get("mcp:srv1:t1") is not None  # bridge 注册进新 registry


@pytest.mark.asyncio
async def test_n5_mcp_reuse_failure_falls_back() -> None:
    """复用失败 → 全部断开返回 None (调用方回落全量重连)。"""
    from isac.runtime.assembly import _reuse_mcp_clients
    from isac.runtime.config import AgentConfig

    ok = _FakeMCPClient("srv1")
    bad = _FakeMCPClient("srv2", fail=True)
    tools = ToolRegistry()
    reused = await _reuse_mcp_clients(AgentConfig(agent_id="a1"), tools, [ok, bad])
    assert reused is None
    assert ok.disconnected == 1 and bad.disconnected == 1  # 复用批全部断开


# ── 富媒体二波: 飞书/Discord 媒体 + 下载管线 headers ──────────


def test_media2_feishu_extract_image_key() -> None:
    """飞书 image 类型 content → image_key 提取。"""
    from isac.channel.adapters.feishu.adapter import FeishuAdapter

    assert FeishuAdapter._extract_image_key('{"image_key": "img_v2_abc"}') == "img_v2_abc"
    assert FeishuAdapter._extract_image_key("not json") == ""
    assert FeishuAdapter._extract_image_key("") == ""
    assert FeishuAdapter._extract_image_key('{"text": "hi"}') == ""


@pytest.mark.asyncio
async def test_media2_feishu_inbound_image_segment() -> None:
    """image 事件 → media segment 带 resources URL + Bearer headers。"""
    from isac.channel.adapters.feishu.adapter import FeishuAdapter

    adapter = FeishuAdapter({
        "app_id": "cli_x", "app_secret": "s",
        "verification_token": "vt", "api_base": "https://open.feishu.cn",
    })
    adapter._cached_token = ("tok123", time.monotonic() + 600)
    msg = ISACMessage(
        msg_id="om1", platform="feishu", timestamp=1, user_id="ou_1",
        user_name="u", content="", group_id="oc_1",
    )
    payload = {"event": {"message": {
        "message_type": "image", "message_id": "om1",
        "content": '{"image_key": "img_v2_k"}',
    }}}
    await adapter._attach_inbound_image(payload, msg)
    assert len(msg.segments) == 1
    seg = msg.segments[0]
    assert seg.type == "image"
    assert "/open-apis/im/v1/messages/om1/resources/img_v2_k?type=image" in seg.data["url"]
    assert seg.data["headers"]["Authorization"] == "Bearer tok123"


def test_media2_discord_attachment_segments() -> None:
    """Discord attachments → media segment (kind 按 content_type)。"""
    from isac.channel.adapters.discord.adapter import DiscordAdapter

    atts = [
        {"url": "https://cdn.discordapp.com/x/a.png", "content_type": "image/png", "filename": "a.png"},
        {"url": "https://cdn.discordapp.com/x/b.mp4", "content_type": "video/mp4", "filename": "b.mp4"},
        {"url": "https://cdn.discordapp.com/x/c.pdf", "content_type": "application/pdf", "filename": "c.pdf"},
        {"url": "", "content_type": "image/png"},  # 无 url 跳过
        "junk",  # 非 dict 跳过
    ]
    segs = DiscordAdapter._build_attachment_segments(atts)
    assert [s.type for s in segs] == ["image", "video", "file"]
    assert segs[0].data["file_name"] == "a.png"


def test_media2_resolver_feishu_discord() -> None:
    """MediaResolver: 飞书 image / Discord 全 kind 支持; telegram 仍 None。"""
    from isac.artifacts.models import ArtifactRef
    from isac.channel.media_resolver import MediaResolver

    img = ArtifactRef(artifact_id="a" * 64, kind="image", uri="data/uploads/img.png",
                      mime_type="image/png", created_at=0.0, expires_at=0.0)
    aud = ArtifactRef(artifact_id="b" * 64, kind="audio", uri="data/uploads/a.mp3",
                      mime_type="audio/mpeg", created_at=0.0, expires_at=0.0)
    seg = MediaResolver.resolve_for_channel("feishu", img)
    assert seg is not None and seg.type == "image" and seg.data["media_uri"] == "data/uploads/img.png"
    # 飞书仅 image (其余 kind 仍 None 降级)
    assert MediaResolver.resolve_for_channel("feishu", aud) is None
    # Discord 全 kind
    seg_d = MediaResolver.resolve_for_channel("discord", aud)
    assert seg_d is not None and seg_d.type == "audio"
    # Telegram 仍不支持
    assert MediaResolver.resolve_for_channel("telegram", img) is None


@pytest.mark.asyncio
async def test_media2_download_headers_passthrough() -> None:
    """incoming_media: segment data["headers"] 透传下载 (鉴权平台)。"""
    import httpx

    from isac.gateway.incoming_media import download_inbound_media

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, content=b"pngbytes")

    class _HeaderClient:
        """注入协议 get_bytes(url, headers=None) 的真 httpx 包装。"""

        def __init__(self) -> None:
            self._inner = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        async def get_bytes(self, url: str, headers: dict | None = None) -> bytes:
            resp = await self._inner.get(url, headers=headers)
            resp.raise_for_status()
            return resp.content

    class _Store:
        async def put(self, content: bytes, kind: str, mime_type: str) -> Any:
            class _Ref:
                uri = "data/uploads/x.png"
                artifact_id = "a" * 64
            return _Ref()

    class _Msg:
        segments = [SimpleNamespace(type="image", data={
            "url": "https://open.feishu.cn/open-apis/im/v1/messages/om1/resources/img_k?type=image",
            "headers": {"Authorization": "Bearer tok456"},
        })]

    n = await download_inbound_media(_Msg(), _Store(), http_client=_HeaderClient())
    assert n == 1
    assert seen["auth"] == "Bearer tok456"  # headers 真实透传
