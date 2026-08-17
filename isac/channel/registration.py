"""U2 通道注册: 按 config.channels 实例化平台适配器 + 默认路由兜底。

原 isac/main.py 的 _register_channel_adapters/_ensure_default_routing 拆出 (U2)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from isac.channel.registry import ChannelRegistry
from isac.router.router import MessageRouter
from isac.utils.logger import get_logger

logger = get_logger(__name__)

DATA_DIR = Path("data")

def _register_channel_adapters(channel_registry: ChannelRegistry, global_config: dict[str, Any]) -> None:
    """Q0: 按 channels.* 配置注册各平台适配器。

    此前生产入口只有 OneBot 一个注册分支, Telegram/Discord/WebChat 三个适配器
    实现+单测齐全却零调用点 (开箱只有需要外部 NapCat 的 QQ 一条可聊通道)。
    全部惰性导入: 未启用的平台不 import 对应模块, 可选依赖不成为强制依赖。
    """
    channels_config = global_config.get("channels", {}) or {}

    onebot_config = channels_config.get("onebot")
    if onebot_config and onebot_config.get("enabled"):
        from isac.channel.adapters.onebot.adapter import OneBotAdapter

        channel_registry.register(OneBotAdapter(onebot_config))
    telegram_config = channels_config.get("telegram")
    if telegram_config and telegram_config.get("enabled"):
        from isac.channel.adapters.telegram.adapter import TelegramAdapter

        channel_registry.register(TelegramAdapter(telegram_config))
    discord_config = channels_config.get("discord")
    if discord_config and discord_config.get("enabled"):
        from isac.channel.adapters.discord.adapter import DiscordAdapter

        channel_registry.register(DiscordAdapter(discord_config))
    webchat_config = channels_config.get("webchat")
    if webchat_config and webchat_config.get("enabled"):
        from isac.channel.adapters.webchat.adapter import WebChatAdapter

        channel_registry.register(WebChatAdapter(webchat_config))
    # O4 适配器: 飞书/企业微信已激活真实 Webhook + 出站消息; 公众号 (wechat mode="mp") 仍骨架。
    # 仅在显式 enabled 时注册, 默认不接入 → 零行为变化。
    feishu_config = channels_config.get("feishu")
    if feishu_config and feishu_config.get("enabled"):
        from isac.channel.adapters.feishu.adapter import FeishuAdapter

        channel_registry.register(FeishuAdapter(feishu_config))
    wechat_config = channels_config.get("wechat")
    if wechat_config and wechat_config.get("enabled"):
        from isac.channel.adapters.wechat.adapter import WeChatAdapter

        channel_registry.register(WeChatAdapter(wechat_config))
    qq_official_config = channels_config.get("qq_official")
    if qq_official_config and qq_official_config.get("enabled"):
        from isac.channel.adapters.qq_official.adapter import QQOfficialAdapter

        channel_registry.register(QQOfficialAdapter(qq_official_config))
    registered = [adapter.platform_name for adapter in channel_registry.list()]
    if registered:
        logger.info("Channel 适配器已注册", platforms=registered)
    else:
        logger.info("未启用任何 Channel 适配器 (channels.* 均未 enabled)")


def _ensure_default_routing(router: MessageRouter, channel_registry: ChannelRegistry, fallback_agent_id: str) -> None:
    """Q0: 裸部署 (未配置任何路由规则) 时为每个已注册平台登记默认 Agent。

    此前无 data/routing.jsonc 时所有无触发词消息在 router 层全部 DROP, 新用户
    首跑收不到任何回复。仅在规则完全为空 (无 bindings 且无 default_agents) 时
    兜底 —— 用户显式配置过任何路由即完全不动, 保留有意的 DROP 语义; 只改内存
    规则不落盘, 不把隐式默认写进用户配置文件。
    """
    rules = router.get_rules()
    if rules.bindings or rules.default_agents:
        return
    platforms = [adapter.platform_name for adapter in channel_registry.list()]
    if not platforms:
        return
    for platform in platforms:
        rules.default_agents[platform] = fallback_agent_id
    router.set_rules(rules)
    logger.info(
        "未配置任何路由规则, 已为已启用平台登记默认 Agent (仅内存, 不落盘)",
        platforms=platforms,
        agent_id=fallback_agent_id,
    )
