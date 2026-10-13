"""内置工具单元测试。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from isac.agent.tools.base import ToolContext
from isac.agent.tools.social.ask_agent import AskAgentTool
from isac.agent.tools.social.query_memory import QueryMemoryTool
from isac.agent.tools.social.query_person_profile import QueryPersonProfileTool
from isac.agent.tools.social.wait import WaitTool
from isac.core.exceptions import InterAgentLinkDeniedError
from isac.core.types import AgentContext, MemoryHit, ToolResult
from isac.gateway.models import Session, UserProfile
from isac.runtime.bus import InterAgentMessage


class FakeMemory:
    def __init__(self) -> None:
        self.metadata = self

    async def search(self, query: str, top_k: int = 5, **kwargs) -> list[MemoryHit]:
        return [
            MemoryHit(
                id="mem_1",
                content=f"记忆命中: {query}",
                source="sess_1",
                hit_type="episode",
                score=0.9,
            )
        ][:top_k]

    async def get_person_profile(self, agent_id: str, person_id: str) -> dict | None:
        return {
            "person_id": person_id,
            "name": "小明",
            "profile_text": "喜欢先完善文档再写代码",
            "relationship_depth": 0.6,
        }


class DeniedBus:
    async def send(self, message: InterAgentMessage) -> InterAgentMessage | None:
        raise InterAgentLinkDeniedError("denied")


class ReplyBus:
    async def send(self, message: InterAgentMessage) -> InterAgentMessage | None:
        return InterAgentMessage(
            from_agent=message.to_agent,
            to_agent=message.from_agent,
            type="response",
            content=f"回复: {message.content}",
        )


@dataclass
class Message:
    content: str = "帮我查一下记忆"


def make_context(services: dict | None = None) -> ToolContext:
    agent_context = AgentContext(
        session=Session(session_id="sess_1", user_id="user_1", agent_id="agent_a"),
        user_profile=UserProfile(user_id="user_1", nickname="小明"),
        current_message=Message(),
    )
    return ToolContext(args={}, agent_context=agent_context, services=services or {})


@pytest.mark.asyncio
async def test_query_memory_formats_hits() -> None:
    context = make_context({"memory": FakeMemory()})
    context.args = {"query": "ISAC", "top_k": 1}

    result = await QueryMemoryTool().execute(context)

    assert result.is_error is False
    assert "【记忆查询结果】" in result.content
    assert "记忆命中: ISAC" in result.content


@pytest.mark.asyncio
async def test_query_memory_without_service_returns_error() -> None:
    context = make_context()
    context.args = {"query": "ISAC"}

    result = await QueryMemoryTool().execute(context)

    assert result.is_error is True
    assert "未启用记忆服务" in result.content


@pytest.mark.asyncio
async def test_query_person_profile_reads_profile() -> None:
    context = make_context({"memory": FakeMemory()})
    context.args = {"user_name": "user_1"}

    result = await QueryPersonProfileTool().execute(context)

    assert result.is_error is False
    assert "【人物画像】" in result.content
    assert "喜欢先完善文档再写代码" in result.content


@pytest.mark.asyncio
async def test_wait_returns_structured_non_blocking_result() -> None:
    context = make_context()
    context.args = {"seconds": 8}

    result = await WaitTool().execute(context)

    assert result.is_error is False
    assert "等待 8 秒" in result.content


@pytest.mark.asyncio
async def test_wait_clamps_oversized_seconds() -> None:
    """N5b 批次F: LLM 传超大 seconds 应 clamp 到 600 上限 (防会话长期挂起)。"""
    from isac.agent.tools.social.wait import WaitTool

    context = make_context()
    context.args = {"seconds": 999999}
    result = await WaitTool().execute(context)
    assert result.is_error is False
    assert "等待 600 秒" in result.content


@pytest.mark.asyncio
async def test_bash_clamps_oversized_timeout() -> None:
    """N5b 批次F: LLM 传超大 timeout 应 clamp 到 300 上限 (防子进程长期占用)。"""
    from isac.agent.tools.utility.bash import BashTool

    context = make_context({"bash_allowlist": {"ls": {"args": 0}}})
    context.args = {"command": "ls", "timeout": 999999}
    result = await BashTool().execute(context)
    # 执行成功 (ls 允许); 验证 timeout 被 clamp (不报"超时 > 999999s")
    assert "999999" not in result.content


@pytest.mark.asyncio
async def test_ask_agent_returns_response() -> None:
    context = make_context({"bus": ReplyBus()})
    context.args = {"target_agent": "tech_agent", "question": "怎么设计记忆？"}

    result = await AskAgentTool().execute(context)

    assert result.is_error is False
    assert result.content == "回复: 怎么设计记忆？"


@pytest.mark.asyncio
async def test_ask_agent_handles_acl_denied() -> None:
    context = make_context({"bus": DeniedBus()})
    context.args = {"target_agent": "tech_agent", "question": "怎么设计记忆？"}

    result = await AskAgentTool().execute(context)

    assert result.is_error is True
    assert "无权与 Agent tech_agent 通信" in result.content


@pytest.mark.asyncio
async def test_send_emoji_sends_via_channel_send() -> None:
    from isac.agent.tools.social.send_emoji import SendEmojiTool

    sent: list = []

    async def channel_send(message) -> bool:
        sent.append(message)
        return True

    context = make_context({"channel_send": channel_send})
    context.args = {"emoji": "👍"}

    result = await SendEmojiTool().execute(context)

    assert result.is_error is False
    assert "已发送表情" in result.content
    assert sent and sent[0].segments[0].type == "emoji"


@pytest.mark.asyncio
async def test_send_emoji_without_channel_send_returns_friendly_error() -> None:
    from isac.agent.tools.social.send_emoji import SendEmojiTool

    context = make_context()
    context.args = {"emoji": "👍"}

    result = await SendEmojiTool().execute(context)

    assert result.is_error is True
    assert "未启用 Channel" in result.content


@pytest.mark.asyncio
async def test_send_image_requires_image_capability() -> None:
    """L1 重写: 无多模态路由/能力配置 → 友好错误 (旧 image_gen 服务键口径已废)。"""
    from isac.agent.tools.social.send_image import SendImageTool

    async def channel_send(message) -> bool:
        return True

    context = make_context({"channel_send": channel_send})  # 无 model_router
    context.args = {"prompt": "一只猫"}

    result = await SendImageTool().execute(context)

    assert result.is_error is True
    assert "多模态模型路由" in result.content


@pytest.mark.asyncio
async def test_send_image_full_flow() -> None:
    """L1 重写: J2 管线 —— router 选路 → provider.generate → ArtifactRef →
    MediaResolver 按 qq 平台转 image segment → channel_send 发送。"""
    from isac.agent.tools.social.send_image import SendImageTool
    from isac.artifacts.models import ArtifactRef

    sent: list = []

    class _Sel:
        class descriptor:  # 简桩 (工具只读 provider_id/model_id)
            provider_id = "openai"
            model_id = "dall-e-3"

    class FakeRouter:
        def select(self, **_kw):
            return _Sel()

    class FakeProvider:
        async def generate(self, prompt: str, n: int = 1) -> list[ArtifactRef]:
            return [ArtifactRef(
                artifact_id="a" * 64, kind="image", mime_type="image/png",
                uri="data/artifacts/aa/" + "a" * 64 + ".bin", size_bytes=8,
            )]

    class FakePM:
        def multimodal_provider(self, _pid: str, _mid: str):
            return FakeProvider()

    async def channel_send(message) -> bool:
        sent.append(message)
        return True

    # current_message 须带 platform (MediaResolver 按平台转段); qq 支持 image。
    incoming = Message()
    incoming.platform = "qq"

    context = make_context(
        {"model_router": FakeRouter(), "provider_manager": FakePM(), "channel_send": channel_send}
    )
    context.agent_context.current_message = incoming  # type: ignore[assignment]
    context.args = {"prompt": "一只猫"}

    result = await SendImageTool().execute(context)

    assert result.is_error is False
    assert "已发送图片" in result.content
    assert sent and sent[0].segments[0].type == "image"


@pytest.mark.asyncio
async def test_send_image_unsupported_platform_falls_back_to_artifact_ref() -> None:
    """平台不支持媒体段 (webchat) → 不硬发, artifact 引用交还 LLM (走回复文本
    引用 + dispatch 出站转段的标准路径)。"""
    from isac.agent.tools.social.send_image import SendImageTool
    from isac.artifacts.models import ArtifactRef

    class _Sel:
        class descriptor:
            provider_id = "openai"
            model_id = "dall-e-3"

    class FakeRouter:
        def select(self, **_kw):
            return _Sel()

    class FakeProvider:
        async def generate(self, prompt: str, n: int = 1) -> list[ArtifactRef]:
            return [ArtifactRef(artifact_id="b" * 64, kind="image", mime_type="image/png")]

    class FakePM:
        def multimodal_provider(self, _pid: str, _mid: str):
            return FakeProvider()

    async def channel_send(message) -> bool:  # pragma: no cover - 不应被调
        raise AssertionError("不支持媒体段的平台不应直发")

    incoming = Message()
    incoming.platform = "webchat"

    context = make_context(
        {"model_router": FakeRouter(), "provider_manager": FakePM(), "channel_send": channel_send}
    )
    context.agent_context.current_message = incoming  # type: ignore[assignment]
    context.args = {"prompt": "一只猫"}

    result = await SendImageTool().execute(context)

    assert result.is_error is False
    assert "artifact:" in result.content
    assert "不支持直接发送" in result.content


@pytest.mark.asyncio
async def test_fetch_history_without_backend_returns_friendly_error() -> None:
    from isac.agent.tools.social.fetch_history import FetchHistoryTool

    context = make_context()
    context.args = {"limit": 5}

    result = await FetchHistoryTool().execute(context)

    assert result.is_error is True
    assert "未启用历史拉取" in result.content


@pytest.mark.asyncio
async def test_switch_chat_without_session_topic_returns_friendly_error() -> None:
    from isac.agent.tools.social.switch_chat import SwitchChatTool

    context = make_context()
    context.args = {"topic": "周末安排"}

    result = await SwitchChatTool().execute(context)

    assert result.is_error is True
    assert "未启用会话话题" in result.content


@pytest.mark.asyncio
async def test_switch_chat_updates_session_topic() -> None:
    from isac.agent.tools.social.switch_chat import SwitchChatTool

    class FakeSessionTopic:
        def __init__(self) -> None:
            self.set_calls: list = []

        async def set(self, session_id: str, topic: str) -> None:
            self.set_calls.append((session_id, topic))

    session_topic = FakeSessionTopic()
    context = make_context({"session_topic": session_topic})
    context.args = {"topic": "周末安排"}

    result = await SwitchChatTool().execute(context)

    assert result.is_error is False
    assert "周末安排" in result.content
    assert session_topic.set_calls == [("sess_1", "周末安排")]


@pytest.mark.asyncio
async def test_view_forward_message_without_backend_returns_friendly_error() -> None:
    from isac.agent.tools.social.view_forward_message import ViewForwardMessageTool

    context = make_context()
    context.args = {"forward_id": "fwd_1"}

    result = await ViewForwardMessageTool().execute(context)

    assert result.is_error is True
    assert "未启用合并转发" in result.content


@pytest.mark.asyncio
async def test_web_search_without_backend_returns_friendly_error() -> None:
    from isac.agent.tools.utility.web_search import WebSearchTool

    context = make_context()
    context.args = {"query": "Python 3.13"}

    result = await WebSearchTool().execute(context)

    assert result.is_error is True
    assert "未配置 web_search" in result.content


@pytest.mark.asyncio
async def test_web_search_formats_results() -> None:
    from isac.agent.tools.utility.web_search import WebSearchTool

    async def search(query: str, top_k: int = 5) -> list:
        return [{"title": "Python 3.13", "url": "https://python.org", "snippet": "新版本发布"}]

    context = make_context({"web_search": search})
    context.args = {"query": "Python 3.13"}

    result = await WebSearchTool().execute(context)

    assert result.is_error is False
    assert "Python 3.13" in result.content
    assert "python.org" in result.content


@pytest.mark.asyncio
async def test_task_tool_without_runner_returns_friendly_error() -> None:
    from isac.agent.tools.utility.task import TaskTool

    context = make_context()
    context.args = {"task": "分析这段日志"}

    result = await TaskTool().execute(context)

    assert result.is_error is True
    assert "未配置 task_runner" in result.content


@pytest.mark.asyncio
async def test_task_tool_blocks_recursion_at_max_depth() -> None:
    from isac.agent.tools.utility.task import TaskTool

    async def runner(task: str, *, budget: int, parent_context=None) -> ToolResult:
        return ToolResult(content="ok")

    context = make_context({"task_runner": runner})
    # Fix-68: task_depth/task_max_depth 由 runtime 写入 AgentContext.services
    context.agent_context.services["task_depth"] = 3
    context.agent_context.services["task_max_depth"] = 3
    context.args = {"task": "再委派一层"}

    result = await TaskTool().execute(context)

    assert result.is_error is True
    assert "递归深度已达上限" in result.content


@pytest.mark.asyncio
async def test_read_file_respects_line_range() -> None:
    import tempfile

    from isac.agent.tools.utility.read_file import ReadFileTool

    with tempfile.TemporaryDirectory() as workspace:
        path = f"{workspace}/data.txt"

        def _write() -> None:
            from pathlib import Path

            Path(path).write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")

        _write()

        context = make_context({"workspace_root": workspace})
        context.args = {"path": "data.txt", "start_line": 2, "end_line": 3}

        result = await ReadFileTool().execute(context)

    assert result.is_error is False
    assert "line2" in result.content
    assert "line3" in result.content
    assert "line1" not in result.content
    assert "line4" not in result.content


@pytest.mark.asyncio
async def test_write_file_creates_and_appends() -> None:
    import tempfile

    from isac.agent.tools.utility.write_file import WriteFileTool

    with tempfile.TemporaryDirectory() as workspace:
        context = make_context({"workspace_root": workspace})
        context.args = {"path": "out.txt", "content": "hello"}
        result = await WriteFileTool().execute(context)
        assert result.is_error is False

        context.args = {"path": "out.txt", "content": " world", "append": True}
        result = await WriteFileTool().execute(context)
        assert result.is_error is False

        def _read() -> str:
            from pathlib import Path

            return Path(f"{workspace}/out.txt").read_text(encoding="utf-8")

        content = _read()
    assert content == "hello world"
