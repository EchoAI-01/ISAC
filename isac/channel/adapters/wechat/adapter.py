"""微信 (企业微信 / WeCom) 平台适配器 (O4, DEVELOP.md 3.3)。

O4 激活: 企业微信应用消息回调 Webhook + 主动下发。不引入 SDK, 用项目既有依赖
httpx (HTTP) + uvicorn (服务端) + cryptography (AES-256-CBC 加解密) 实现。

平台协议要点 (字节序核对自企业微信官方文档):
- 回调 URL 校验: GET ``?msg_signature=&timestamp=&nonce=&echostr=``
  msg_signature = sha1(sort([token, timestamp, nonce, echostr])).hexdigest()
  校验通过后 AES 解密 echostr, 返回解密后的明文 echostr (作 text/plain)。
- 消息回调: POST ``?msg_signature=&timestamp=&nonce=``, body XML ``<xml>...<Encrypt>...</xml>``
  msg_signature = sha1(sort([token, timestamp, nonce, encrypt_body])).hexdigest()
  校验通过后 AES 解密 Encrypt 字段 → 内层 XML ``<xml><ToUserName>,<FromUserName>,
  <CreateTime>,<MsgType>,<Content>,<MsgId>,<AgentID>...</xml>``
- AES 算法 (WXBizMsgCrypt): key = base64decode(encoding_aes_key + "="); iv = 密文前 16 字节;
  plain = AES-256-CBC decrypt(密文[16:]) → 前 16 字节是随机串, 接着 4 字节大端 msg_len,
  然后 msg_len 字节 msg (内层 XML), 最后是 receiveid (corpid)。PKCS7 unpad。
  (Fix-37 订正: 此前文档误写为 "msg_len 字节 to_user + xml 正文", 与官方布局颠倒。)

出站 (``send``):
- access_token: GET ``/cgi-bin/gettoken?corpid=&corpsecret=`` → ``{"access_token","expires_in"}``,
  缓存 + 提前 60s 刷新。
- 发消息: POST ``/cgi-bin/message/send?access_token=`` body ``{"touser","msgtype":"text",
  "agentid", "text":{"content":...}}``; errcode=0 才成功。

默认关闭: 仅当 ``channels.wechat.enabled=true`` 且 ``mode="wecom"`` 时生效。未配置
corp_id/secret/agent_id 时 start 起服务但 send 会失败 (不抛异常)。公众号模式 (``mode="mp"``)
保留旧骨架行为 (后续节点实现)。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import struct
import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import PlainTextResponse

from isac.channel.base import PlatformAdapter
from isac.channel.model import ISACMessage
from isac.channel.webhook_guard import DEFAULT_MAX_WEBHOOK_BODY_BYTES, read_body_limited
from isac.utils.logger import get_logger

logger = get_logger(__name__)

# 企业微信 API 端点 (相对 api_base)
_GETTOKEN_PATH = "/cgi-bin/gettoken"
_SEND_MESSAGE_PATH = "/cgi-bin/message/send"
# token 缓存提前刷新窗口 (秒); 企业微信默认 expires_in=7200, 提前 60s 避免临界过期
_TOKEN_REFRESH_LEAD_SECONDS = 60.0
# Webhook 默认监听 host/port/path
_DEFAULT_WEBHOOK_HOST = "127.0.0.1"
_DEFAULT_WEBHOOK_PORT = 9097
_DEFAULT_WEBHOOK_PATH = "/wechat/events"


class WeComAdapter(PlatformAdapter):
    """企业微信应用消息适配器 (O4 激活)。

    仅实现企业微信 (``mode="wecom"``) 路径; 公众号 (``mode="mp"``) 在 :class:`WeChatAdapter`
    工厂里仍走旧骨架, 后续节点实现。
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._corp_id = str(config.get("corp_id", "") or "")
        self._agent_id = str(config.get("agent_id", "") or "")
        self._secret = str(config.get("secret", "") or "")
        self._token = str(config.get("token", "") or "")
        self._encoding_aes_key = str(config.get("encoding_aes_key", "") or "")
        self._api_base = str(config.get("api_base", "https://qyapi.weixin.qq.com") or "https://qyapi.weixin.qq.com")
        self._webhook_host = str(config.get("webhook_host", _DEFAULT_WEBHOOK_HOST) or _DEFAULT_WEBHOOK_HOST)
        self._webhook_port = int(config.get("webhook_port", _DEFAULT_WEBHOOK_PORT) or _DEFAULT_WEBHOOK_PORT)
        self._webhook_path = str(config.get("webhook_path", _DEFAULT_WEBHOOK_PATH) or _DEFAULT_WEBHOOK_PATH)
        # Fix-76: webhook 请求体体积上限 (验签前先限流读取, 防超大 body 打爆内存)
        self._max_body_bytes = int(config.get("max_body_bytes", DEFAULT_MAX_WEBHOOK_BODY_BYTES))
        self._running = False
        self._server: Any = None  # uvicorn.Server
        self._serve_task: asyncio.Task[Any] | None = None
        self._cached_token: tuple[str, float] | None = None
        self._http_transport: Any | None = None
        self.on_message = None  # type: ignore[assignment]  # 由 ChannelRegistry 注入

    @property
    def platform_name(self) -> str:
        return "wechat"

    async def start(self) -> None:
        """启动 webhook 回调服务端 (FastAPI + uvicorn, 独立端口)。

        未配置 corp_id/secret 也能 start (服务可起, 但 send 会失败);
        未配置 token/encoding_aes_key 时事件验签会拒绝 (Fail-closed)。
        """
        if self._running:
            return
        try:
            import uvicorn
            from fastapi import FastAPI
        except ImportError as exc:  # pragma: no cover - 依赖已在 pyproject.toml
            raise ImportError(
                "微信适配器需要 fastapi + uvicorn (已在项目依赖中)。若缺失请运行 uv sync --all-extras"
            ) from exc
        app = FastAPI()
        app.add_api_route(self._webhook_path, self._handle_event, methods=["GET", "POST"])
        config = uvicorn.Config(
            app, host=self._webhook_host, port=self._webhook_port, log_level="warning",
        )
        self._server = uvicorn.Server(config)
        self._running = True
        self._serve_task = asyncio.create_task(
            self._server.serve(), name=f"wecom-webhook-{self._webhook_port}"
        )
        logger.info(
            "企业微信适配器 webhook 服务已启动",
            corp_id=self._corp_id, agent_id=self._agent_id,
            host=self._webhook_host, port=self._webhook_port, path=self._webhook_path,
        )

    async def stop(self) -> None:
        """关闭 webhook 服务端 (should_exit 触发优雅关闭)。"""
        self._running = False
        if self._server is not None:
            self._server.should_exit = True
        if self._serve_task is not None:
            try:
                await asyncio.wait_for(self._serve_task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._serve_task.cancel()
            self._serve_task = None

    async def _handle_event(self, request: Request) -> Any:
        """Webhook 入站主入口: GET = URL 校验挑战, POST = 消息回调。

        任何异常都吞掉并返回 200 "success" (企业微信对非 200/慢响应会重试, 但空 body
        的重试不会带来更多有效数据, 故统一吞掉避免日志污染)。验签失败返回
        ``"success"`` (不返回 echostr 明文), 防止伪造请求绕过校验直接解密。
        """
        try:
            if request.method == "GET":
                return await self._handle_url_verification(request)
            return await self._handle_message_callback(request)
        except Exception as exc:  # noqa: BLE001
            logger.warning("企业微信 webhook 处理事件异常", error=str(exc), exc_info=True)
            return PlainTextResponse("success")

    async def _handle_url_verification(self, request: Request) -> Any:
        """GET 回调: 校验 msg_signature, 解密 echostr, 返回明文 echostr。

        企业微信在配置回调 URL 时发 GET 请求, 携带 ``msg_signature``、
        ``timestamp``、``nonce``、``echostr`` 四个 query 参数。校验:
        ``msg_signature == sha1(sort([token, timestamp, nonce, echostr]))``;
        通过后用 AES 解密 echostr, 返回解密后的明文 (企业微信据此判定 URL 有效)。
        """
        msg_signature = str(request.query_params.get("msg_signature", "") or "")
        timestamp = str(request.query_params.get("timestamp", "") or "")
        nonce = str(request.query_params.get("nonce", "") or "")
        echostr = str(request.query_params.get("echostr", "") or "")
        if not (msg_signature and timestamp and nonce and echostr):
            logger.warning("企业微信 URL 校验缺参数, 拒绝")
            return PlainTextResponse("success")
        if not self._verify_signature(timestamp, nonce, echostr, msg_signature):
            logger.warning("企业微信 URL 校验签名不符, 拒绝")
            return PlainTextResponse("success")
        plain = self._decrypt_aes(echostr)
        if plain is None:
            logger.warning("企业微信 URL 校验 echostr 解密失败, 拒绝")
            return PlainTextResponse("success")
        return PlainTextResponse(plain)

    async def _handle_message_callback(self, request: Request) -> Any:
        """POST 回调: 校验 msg_signature, 解密 Encrypt, 解析 XML, 规范化为 ISACMessage。"""
        # Fix-76: 限流读取 —— request.body() 全量读入内存且无上限, 而验签在读取
        # 之后, 超大 body (含 chunked) 在签名校验之前即可打爆内存; 超限按本文件
        # 既有拒绝惯例回 "success" (避免平台对同一超大请求反复重试)。
        body = await read_body_limited(request, self._max_body_bytes)
        if body is None:
            logger.warning("企业微信消息回调请求体超限, 拒绝", limit=self._max_body_bytes)
            return PlainTextResponse("success")
        msg_signature = str(request.query_params.get("msg_signature", "") or "")
        timestamp = str(request.query_params.get("timestamp", "") or "")
        nonce = str(request.query_params.get("nonce", "") or "")
        if not (msg_signature and timestamp and nonce):
            logger.warning("企业微信消息回调缺签名参数, 拒绝")
            return PlainTextResponse("success")
        try:
            xml_text = body.decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("企业微信消息回调 body 非 UTF-8", error=str(exc))
            return PlainTextResponse("success")
        encrypt_field = _extract_encrypt(xml_text)
        if not encrypt_field:
            logger.warning("企业微信消息回调缺 Encrypt 字段, 拒绝 (明文模式不安全)")
            return PlainTextResponse("success")
        if not self._verify_signature(timestamp, nonce, encrypt_field, msg_signature):
            logger.warning("企业微信消息回调签名不符, 拒绝")
            return PlainTextResponse("success")
        plain_xml = self._decrypt_aes(encrypt_field)
        if plain_xml is None:
            return PlainTextResponse("success")
        msg = _parse_wecom_xml(plain_xml)
        if msg is None:
            return PlainTextResponse("success")
        if self.on_message is not None:
            try:
                await self.on_message(msg)  # type: ignore[misc]
            except Exception as exc:  # noqa: BLE001
                logger.warning("企业微信 on_message 处理异常", error=str(exc))
        return PlainTextResponse("success")

    def _verify_signature(self, timestamp: str, nonce: str, encrypt: str, msg_signature: str) -> bool:
        """校验企业微信签名: sha1(sort([token, timestamp, nonce, encrypt])).hexdigest() == msg_signature。

        用 hmac.compare_digest 常数时间比较, 防止时序侧通道。
        未配置 token 时返回 False (fail-closed): webhook 对外可达, 无 token 校验
        等于允许任意身份伪造消息直达 on_message。
        """
        if not self._token:
            logger.warning("企业微信 webhook 未配置 token, 拒绝事件")
            return False
        parts = sorted([self._token, timestamp, nonce, encrypt])
        expected = hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()
        return hmac.compare_digest(expected, msg_signature)

    def _decrypt_aes(self, encrypt_b64: str) -> str | None:
        """企业微信 AES-256-CBC 解密 (WXBizMsgCrypt 算法)。

        key = base64decode(encoding_aes_key + "="); iv = 密文前 16 字节;
        plain = AES-256-CBC decrypt(密文[16:]) → PKCS7 unpad;
        明文切片与 receiveid 校验见 _extract_xml_from_plain (Fix-37 官方布局)。
        未配置 encoding_aes_key 时返回 None (拒绝明文模式, 与飞书一致)。
        """
        if not self._encoding_aes_key:
            logger.warning("企业微信 webhook 未配置 encoding_aes_key, 拒绝解密")
            return None
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.primitives.padding import PKCS7
        except ImportError as exc:  # pragma: no cover - cryptography 已在项目依赖
            logger.warning("企业微信解密缺 cryptography 依赖", error=str(exc))
            return None
        try:
            key = base64.b64decode(self._encoding_aes_key + "=")
            if len(key) != 32:
                logger.warning("企业微信 encoding_aes_key 解码后非 32 字节", key_len=len(key))
                return None
            enc = base64.b64decode(encrypt_b64)
            if len(enc) < 32 + 4:  # iv(16) + 至少一个 block + 4 字节长度
                logger.warning("企业微信密文过短", length=len(enc))
                return None
            iv = enc[:16]
            ciphertext = enc[16:]
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
            decryptor = cipher.decryptor()
            padded = decryptor.update(ciphertext) + decryptor.finalize()
            unpadder = PKCS7(128).unpadder()
            plain = unpadder.update(padded) + unpadder.finalize()
            return self._extract_xml_from_plain(plain)
        except Exception as exc:  # noqa: BLE001
            logger.warning("企业微信 AES 解密失败", error=str(exc))
            return None

    def _extract_xml_from_plain(self, plain: bytes) -> str | None:
        """从解密后明文提取内层 XML 并校验 receiveid (Fix-37, 自 _decrypt_aes 抽出)。

        官方 WXBizMsgCrypt 明文布局 random(16) + msg_len(4 大端) + msg(msg_len 字节的
        内层 XML) + receiveid(corpid)。此前实现把 msg_len 当前缀长度取 plain[20+msg_len:]
        当 XML —— 取到的实为 corpid 尾部, 与官方协议颠倒; 单测用同样的错误布局编码互相
        印证, 故全绿但真实回调必失败。现按官方布局切片, 并校验 receiveid == corpid
        (防跨企业伪造); 未配置 corp_id 时跳过校验。
        """
        if len(plain) < 20:
            logger.warning("企业微信解密后明文过短", length=len(plain))
            return None
        msg_len = struct.unpack(">I", plain[16:20])[0]
        if 20 + msg_len > len(plain):
            logger.warning("企业微信解密后 msg_len 越界", msg_len=msg_len, plain_len=len(plain))
            return None
        xml_bytes = plain[20:20 + msg_len]
        receiveid = plain[20 + msg_len:]
        if self._corp_id:
            try:
                receiveid_text = receiveid.decode("utf-8")
            except UnicodeDecodeError:
                logger.warning("企业微信 receiveid 非 UTF-8, 拒绝")
                return None
            if receiveid_text != self._corp_id:
                logger.warning("企业微信 receiveid 与 corp_id 不符, 拒绝", receiveid=receiveid_text)
                return None
        return xml_bytes.decode("utf-8")

    async def send(self, message: ISACMessage) -> bool:
        """发送文本消息到企业微信 (touser + agentid)。

        touser 取 message.user_id; agentid 取配置。token 换取/发送失败返回 False (不抛异常)。
        """
        if not self._corp_id or not self._secret or not self._agent_id:
            logger.warning("企业微信 send 缺 corp_id/secret/agent_id, 跳过")
            return False
        touser = str(message.user_id or "")
        if not touser:
            logger.warning("企业微信 send 缺 touser (user_id 为空)")
            return False
        token = await self._get_access_token()
        if not token:
            return False
        body = {
            "touser": touser,
            "msgtype": "text",
            "agentid": int(self._agent_id),
            "text": {"content": str(message.content or "")},
        }
        try:
            resp = await self._http_post(
                f"{self._api_base}{_SEND_MESSAGE_PATH}",
                params={"access_token": token},
                json_body=body,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("企业微信 send 请求发送失败", error=str(exc))
            return False
        if resp is None:
            return False
        # NOTE: 用 `is None` 判定而非 `or` —— 0 在 Python 是 falsy, `0 or -1` = -1
        # 会误判 errcode=0 失败 (企业微信 errcode=0 才是成功)。
        errcode_raw = resp.get("errcode")
        errcode = -1 if errcode_raw is None else int(errcode_raw)
        if errcode != 0:
            logger.warning("企业微信 send 返回非 0 errcode", errcode=errcode, errmsg=resp.get("errmsg", ""))
            return False
        return True

    async def _get_access_token(self) -> str | None:
        """获取 access_token (缓存 + 提前 60s 刷新)。"""
        if self._cached_token is not None:
            token, expires_at = self._cached_token
            if time.monotonic() < expires_at:
                return token
        try:
            resp = await self._http_get(
                f"{self._api_base}{_GETTOKEN_PATH}",
                params={"corpid": self._corp_id, "corpsecret": self._secret},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("企业微信 access_token 换取失败", error=str(exc))
            return None
        if resp is None:
            return None
        errcode_raw = resp.get("errcode")
        errcode = -1 if errcode_raw is None else int(errcode_raw)
        if errcode != 0:
            logger.warning("企业微信 access_token 返回非 0", errcode=errcode, errmsg=resp.get("errmsg", ""))
            return None
        token = str(resp.get("access_token", "") or "")
        expire = int(resp.get("expires_in", 7200) or 7200)
        if not token:
            return None
        self._cached_token = (token, time.monotonic() + max(60, expire - _TOKEN_REFRESH_LEAD_SECONDS))
        return token

    async def _http_get(self, url: str, *, params: dict) -> dict | None:
        """统一 HTTP GET (生产走 httpx.AsyncClient; 测试可注入 transport mock)。

        返回响应 JSON dict; 网络异常/非 JSON 返回 None。
        """
        transport = self._http_transport
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await client.get(url, params=params, timeout=10.0)
        if resp.status_code >= 400:
            logger.warning("企业微信 HTTP 非 2xx", url=url, status=resp.status_code, body=resp.text[:200])
            return None
        try:
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("企业微信 HTTP 响应非 JSON", url=url, error=str(exc))
            return None

    async def _http_post(
        self, url: str, *, json_body: dict, headers: dict, params: dict | None = None
    ) -> dict | None:
        """统一 HTTP POST (生产走 httpx.AsyncClient; 测试可注入 transport mock)。

        返回响应 JSON dict; 网络异常/非 JSON 返回 None。
        """
        transport = self._http_transport
        async with httpx.AsyncClient(transport=transport) as client:
            resp = await client.post(url, json=json_body, headers=headers, params=params, timeout=10.0)
        if resp.status_code >= 400:
            logger.warning("企业微信 HTTP 非 2xx", url=url, status=resp.status_code, body=resp.text[:200])
            return None
        try:
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("企业微信 HTTP 响应非 JSON", url=url, error=str(exc))
            return None

    def set_http_transport(self, transport: Any) -> None:
        """供测试注入 httpx.MockTransport (生产不调用)。"""
        self._http_transport = transport


class WeChatAdapter(PlatformAdapter):
    """微信平台适配器 (工厂分发: ``mode="wecom"`` 走企业微信真实实现, 其余保留骨架)。

    保留旧类名以兼容 ``main._register_channel_adapters`` 的 ``WeChatAdapter(wechat_config)``
    调用点; O4 激活后 ``mode="wecom"`` 默认值会自动路由到真实实现。
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._mode = str(config.get("mode", "wecom") or "wecom")
        if self._mode == "wecom":
            self._impl: PlatformAdapter = WeComAdapter(config)
        else:
            # 公众号 (mode="mp") 暂保留骨架行为, 后续节点实现
            self._impl = _MpStubAdapter(config)
        self.on_message = None  # type: ignore[assignment]

    @property
    def platform_name(self) -> str:
        return "wechat"

    async def start(self) -> None:
        await self._impl.start()
        # 转发 on_message 注入: ChannelRegistry 在 register() 后会设 on_message 到
        # 外层 WeChatAdapter, 这里同步给到内层真实实现。
        self._impl.on_message = self.on_message

    async def stop(self) -> None:
        await self._impl.stop()

    async def send(self, message: ISACMessage) -> bool:
        return await self._impl.send(message)


class _MpStubAdapter(PlatformAdapter):
    """公众号模式骨架 (O4 未实现, 保留旧 no-op 行为)。

    旧骨架里 start/stop no-op、send 返回 False; 这里维持同样行为, 不产生任何 I/O。
    真实公众号接入 (回调 Webhook + AES 加解密 + 客服消息下发) 是后续节点工作。
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._running = False

    @property
    def platform_name(self) -> str:
        return "wechat"

    async def start(self) -> None:
        self._running = True
        logger.debug("公众号适配器 start (骨架 no-op, O4 待实现)")

    async def stop(self) -> None:
        self._running = False

    async def send(self, message: ISACMessage) -> bool:
        _ = message
        return False


_UNSAFE_XML_MARKERS = ("<!doctype", "<!entity")


def _has_unsafe_xml_construct(xml_text: str) -> bool:
    """检测 DOCTYPE/ENTITY 声明。

    XML 实体只能在 DTD (通过 ``<!DOCTYPE`` 声明) 内定义, 官方企业微信回调 XML
    从不带 DTD; 出现即视为恶意输入 (如递归实体展开 / "billion laughs" 拒绝服务),
    在喂给 ``ET.fromstring`` 之前直接拒绝。标准库 ``xml.etree.ElementTree`` 默认
    会展开内部实体, 对此类载荷没有防护 (项目未引入 defusedxml, 故用此前置守卫
    代替, 效果等价且零新依赖)。
    """
    lowered = xml_text.lower()
    return any(marker in lowered for marker in _UNSAFE_XML_MARKERS)


def _extract_encrypt(xml_text: str) -> str:
    """从外层 XML ``<xml><Encrypt><![CDATA[...]]></Encrypt>...</xml>`` 提取 Encrypt 字段。

    这一步发生在签名校验**之前** (校验本身需要 Encrypt 字段的原文), 因此这里
    收到的是完全未鉴权的输入; 用 ElementTree 解析前先过 DOCTYPE/ENTITY 守卫。
    CDATA 会被 ElementTree 自动解包。失败/被拒绝均返回空串, 不抛异常。
    """
    if _has_unsafe_xml_construct(xml_text):
        logger.warning("企业微信外层 XML 含 DOCTYPE/ENTITY 声明, 拒绝 (实体扩展防护)")
        return ""
    try:
        root = ET.fromstring(xml_text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("企业微信外层 XML 解析失败", error=str(exc))
        return ""
    encrypt = root.findtext("Encrypt")
    return str(encrypt or "")


def _parse_wecom_xml(xml_text: str) -> ISACMessage | None:
    """从内层 XML 解析企业微信消息 → ISACMessage。

    企业微信内层 XML 字段: ``<ToUserName>`` (企业微信 corpid)、``<FromUserName>`` (用户 userid)、
    ``<CreateTime>`` (秒级时间戳)、``<MsgType>`` (text/image/event...)、``<Content>`` (文本内容)、
    ``<MsgId>``、``<AgentID>``。只处理 text 类型, 其他类型降级为占位文本 (不阻塞主链路)。

    这一步的输入已经过签名校验 + AES 解密, 风险远低于 :func:`_extract_encrypt`; 仍加
    DOCTYPE/ENTITY 守卫做纵深防御 (防御性一致, 成本几乎为零)。
    """
    if _has_unsafe_xml_construct(xml_text):
        logger.warning("企业微信内层 XML 含 DOCTYPE/ENTITY 声明, 拒绝 (实体扩展防护)")
        return None
    try:
        root = ET.fromstring(xml_text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("企业微信内层 XML 解析失败", error=str(exc))
        return None
    from_user = str(root.findtext("FromUserName") or "")
    msg_id = str(root.findtext("MsgId") or "")
    msg_type = str(root.findtext("MsgType") or "")
    content = str(root.findtext("Content") or "")
    create_time_str = str(root.findtext("CreateTime") or "0")
    try:
        timestamp = int(create_time_str)
    except ValueError:
        timestamp = int(time.time())
    if not from_user:
        logger.warning("企业微信内层 XML 缺 FromUserName, 丢弃", msg_id=msg_id)
        return None
    if msg_type != "text":
        # 非 text 类型 (image/voice/event...) 降级为占位文本, 保持主链路不中断
        content = f"[{msg_type}]"
    return ISACMessage(
        msg_id=msg_id,
        platform="wechat",
        timestamp=timestamp,
        user_id=from_user,
        user_name=from_user,  # 企业微信不直接给昵称, 用 userid 占位 (N3 归一后可填充)
        group_id=None,  # 企业微信应用消息无群组概念, 始终私聊
        content=content,
    )


__all__ = ["WeChatAdapter", "WeComAdapter"]
