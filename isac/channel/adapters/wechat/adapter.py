"""微信平台适配器骨架 (O4, DEVELOP.md 3.3)。

[骨架 / scaffolding] 实现 PlatformAdapter 4 个抽象方法, 但连接/收发均为占位:
``start``/``stop`` no-op, ``send`` 返回 False。真实接入由 O4 微信实现节点填充。
默认不接入任何 Channel (仅当 channels.wechat.enabled=true 时经
main._register_channel_adapters 注册, 骨架期即使注册也不产生任何 I/O), 零行为变化。

平台机制备忘 (供实现参考, 非本次范围):
- 合规路径: **个人微信** 收发违反微信服务协议且封号风险高, 不做; 走官方开放能力二选一:
  (a) 「微信公众号」(服务号): 消息回调 Webhook (Token 签名校验 + 可选 AES 消息加解密
      EncodingAESKey) 入站; 出站受「48 小时客服消息窗口」限制, 超窗只能用模板消息。
  (b) 「企业微信」(WeCom): 应用消息回调入站 + ``message/send`` 主动下发出站, 无 48h 限制,
      更适合 Bot。推荐企业微信路径。
- 出站: 需 access_token (公众号用 appid/secret, 企业微信用 corpid/corpsecret 换取, 缓存续期)。
- 身份: 公众号 openid / 企业微信 userid; 归一到 ISAC 身份体系见 N3/P4。

配置示例 (data/config.jsonc):
    {
        "channels": {
            "wechat": {
                "enabled": true,
                "mode": "wecom",              // "wecom" 企业微信 | "mp" 公众号
                "corp_id": "",                // wecom: 企业 ID
                "agent_id": "",               // wecom: 应用 AgentId
                "secret": "",                 // wecom: 应用 Secret / mp: AppSecret
                "app_id": "",                 // mp: 公众号 AppID
                "token": "",                  // 回调 URL 校验 Token
                "encoding_aes_key": "",       // 消息加解密 (可空=明文模式)
                "api_base": "https://qyapi.weixin.qq.com"
            }
        }
    }
"""

from __future__ import annotations

from typing import Any

from isac.channel.base import PlatformAdapter
from isac.channel.model import ISACMessage
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class WeChatAdapter(PlatformAdapter):
    """微信 (公众号 / 企业微信) 适配器骨架 (O4 待实现)。"""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._mode = str(config.get("mode", "wecom"))
        self._api_base = str(config.get("api_base", "https://qyapi.weixin.qq.com"))
        self._running = False

    @property
    def platform_name(self) -> str:
        return "wechat"

    async def start(self) -> None:
        """建立微信消息回调服务端并开始接收消息。

        TODO(O4): 起回调 HTTP 服务端处理平台推送 —— 校验 Token 签名 (echostr
        challenge), 按 encoding_aes_key 解密, 解析 XML/JSON 消息体, 规范化为
        ISACMessage 后交给 self.on_message。骨架阶段 no-op (不监听)。
        """
        self._running = True
        logger.debug("微信适配器 start (骨架 no-op)", mode=self._mode)

    async def stop(self) -> None:
        """关闭回调服务端并清理资源。TODO(O4): 停止 HTTP 服务端与后台任务。骨架 no-op。"""
        self._running = False

    async def send(self, message: ISACMessage) -> bool:
        """把出站消息发送到微信。

        TODO(O4): 企业微信调 ``POST /cgi-bin/message/send`` (touser/agentid);
        公众号受 48h 客服消息窗口约束, 超窗降级模板消息。均需先换取并缓存 access_token。
        骨架阶段返回 False (未实现)。
        """
        _ = message
        return False
