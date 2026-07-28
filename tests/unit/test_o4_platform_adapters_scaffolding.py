"""O4 平台适配器骨架单测: 飞书 / 微信 / QQ 官方机器人 (TODO(O4))。

验证三个骨架适配器满足 PlatformAdapter 契约: platform_name 稳定、start/stop no-op
不抛异常、send 恒返回 False (未实现); 以及 main._register_channel_adapters 的
enabled-gated 注册分支 (默认关闭零注册、启用时注册且与既有 OneBot "qq" 并存不撞键)。
骨架阶段不产生任何连接/收发 I/O, 主链路零行为变化。
"""

from __future__ import annotations

import pytest

from isac.channel.adapters.feishu.adapter import FeishuAdapter
from isac.channel.adapters.qq_official.adapter import QQOfficialAdapter
from isac.channel.adapters.wechat.adapter import WeChatAdapter
from isac.channel.model import ISACMessage
from isac.channel.registry import ChannelRegistry
from isac.main import _register_channel_adapters


def _msg(platform: str) -> ISACMessage:
    return ISACMessage(
        msg_id="m1", platform=platform, timestamp=0, user_id="u1", user_name="tester", content="hi"
    )


class TestFeishuAdapterSkeleton:
    def test_platform_name(self) -> None:
        assert FeishuAdapter({"app_id": "cli_x"}).platform_name == "feishu"

    @pytest.mark.asyncio
    async def test_start_stop_noop(self) -> None:
        adapter = FeishuAdapter({})
        await adapter.start()
        await adapter.stop()  # 不抛异常即可

    @pytest.mark.asyncio
    async def test_send_returns_false(self) -> None:
        assert await FeishuAdapter({}).send(_msg("feishu")) is False


class TestWeChatAdapterSkeleton:
    def test_platform_name(self) -> None:
        assert WeChatAdapter({"mode": "wecom"}).platform_name == "wechat"

    @pytest.mark.asyncio
    async def test_start_stop_noop(self) -> None:
        adapter = WeChatAdapter({})
        await adapter.start()
        await adapter.stop()

    @pytest.mark.asyncio
    async def test_send_returns_false(self) -> None:
        assert await WeChatAdapter({}).send(_msg("wechat")) is False


class TestQQOfficialAdapterSkeleton:
    def test_platform_name(self) -> None:
        assert QQOfficialAdapter({"app_id": "x"}).platform_name == "qq_official"

    @pytest.mark.asyncio
    async def test_start_stop_noop(self) -> None:
        adapter = QQOfficialAdapter({})
        await adapter.start()
        await adapter.stop()

    @pytest.mark.asyncio
    async def test_send_returns_false(self) -> None:
        assert await QQOfficialAdapter({}).send(_msg("qq_official")) is False


class TestO4RegistrationBranches:
    def test_three_platforms_register_when_enabled(self) -> None:
        registry = ChannelRegistry()
        _register_channel_adapters(
            registry,
            {
                "channels": {
                    "feishu": {"enabled": True, "app_id": "cli_x"},
                    "wechat": {"enabled": True, "mode": "wecom"},
                    "qq_official": {"enabled": True, "app_id": "x"},
                }
            },
        )
        assert {a.platform_name for a in registry.list()} == {"feishu", "wechat", "qq_official"}

    def test_disabled_registers_nothing(self) -> None:
        registry = ChannelRegistry()
        _register_channel_adapters(
            registry,
            {"channels": {"feishu": {"enabled": False}, "wechat": {}, "qq_official": {"enabled": False}}},
        )
        assert registry.list() == []

    def test_qq_official_coexists_with_onebot_qq(self) -> None:
        """OneBot 占 "qq"、官方机器人占 "qq_official", 同时启用互不覆盖。"""
        registry = ChannelRegistry()
        _register_channel_adapters(
            registry,
            {
                "channels": {
                    "onebot": {"enabled": True, "host": "127.0.0.1", "port": 18081},
                    "qq_official": {"enabled": True, "app_id": "x"},
                }
            },
        )
        assert {a.platform_name for a in registry.list()} == {"qq", "qq_official"}
