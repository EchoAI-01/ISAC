"""飞书 (Lark) 平台适配器 (O4, DEVELOP.md 3.3)。

S7 激活: 飞书事件订阅 Webhook 回调 + 出站消息发送。不引入 lark-oapi SDK, 用项目
既有依赖 httpx (HTTP) + uvicorn (服务端) + cryptography (AES-256-CBC 解密) 实现。

入站 (``start`` 起一个内部 uvicorn Server + FastAPI app):
- URL 校验挑战: 收到 ``{"challenge":..., "token":..., "type":"url_verification"}``;
  明文模式校验 ``token == verification_token``, 加密模式先 AES 解密拿到 inner JSON
  再回 challenge; 始终 1 秒内回 ``{"challenge":...}``。
- 加密事件: 请求体 ``{"encrypt": "<base64>"}``; 解密 = SHA256(encrypt_key) 作 AES key,
  base64decode(encrypt) 前 16 字节作 IV, AES-256-CBC + PKCS7 unpad (字节序核对自
  open.feishu.cn 官方文档 step-3 接收事件)。
- 事件: ``im.message.receive_v1`` → event.message.chat_id (group_id) /
  event.sender.sender_id.open_id (user_id) / event.message.message_id (msg_id) /
  event.message.content (JSON 字符串, text 类型解析出 ``{"text": ...}``);
  规范化为 ISACMessage 交 self.on_message; 始终 200 ``{}`` 让飞书不重试
  (慢响应/非 200 会触发重试推送)。

出站 (``send``):
- tenant_access_token: POST ``/open-apis/auth/v3/tenant_access_token/internal``
  body ``{"app_id", "app_secret"}`` → ``{"code":0, "tenant_access_token",
  "expire"}``; 缓存 + 提前 60s 刷新。
- 发消息: POST ``/open-apis/im/v1/messages?receive_id_type=chat_id|open_id``,
  Header ``Authorization: Bearer <token>``, body ``{"receive_id", "msg_type":"text",
  "content": "{\"text\":...}"}``; receive_id 取 group_id 或 user_id。

默认关闭: 仅当 ``channels.feishu.enabled=true`` 时经 main._register_channel_adapters
注册; 未配置时 start/stop/send 无副作用, 零行为变化。未配置 app_id/app_secret 时
start 起服务但 send 会因 token 换取失败返回 False (不抛异常)。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from typing import Any

import httpx
from fastapi import Request

from isac.channel.base import PlatformAdapter
from isac.channel.model import ISACMessage
from isac.utils.logger import get_logger

logger = get_logger(__name__)

# token 换取与消息发送端点 (相对 api_base)
_TENANT_TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"
_SEND_MESSAGE_PATH = "/open-apis/im/v1/messages"
# token 缓存提前刷新窗口 (秒); 飞书默认 expire=7200, 提前 60s 避免临界过期
_TOKEN_REFRESH_LEAD_SECONDS = 60.0
# Webhook 默认监听 host/port/path
_DEFAULT_WEBHOOK_HOST = "127.0.0.1"
_DEFAULT_WEBHOOK_PORT = 9099
_DEFAULT_WEBHOOK_PATH = "/feishu/events"


class FeishuAdapter(PlatformAdapter):
    """飞书 (Lark) Webhook 适配器 (S7 激活)。"""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._app_id = str(config.get("app_id", "") or "")
        self._app_secret = str(config.get("app_secret", "") or "")
        self._verification_token = str(config.get("verification_token", "") or "")
        self._encrypt_key = str(config.get("encrypt_key", "") or "")
        self._api_base = str(config.get("api_base", "https://open.feishu.cn") or "https://open.feishu.cn")
        # webhook 服务端配置
        self._webhook_host = str(config.get("webhook_host", _DEFAULT_WEBHOOK_HOST) or _DEFAULT_WEBHOOK_HOST)
        self._webhook_port = int(config.get("webhook_port", _DEFAULT_WEBHOOK_PORT) or _DEFAULT_WEBHOOK_PORT)
        self._webhook_path = str(config.get("webhook_path", _DEFAULT_WEBHOOK_PATH) or _DEFAULT_WEBHOOK_PATH)
        self._running = False
        self._server: Any = None  # uvicorn.Server
        self._serve_task: asyncio.Task[Any] | None = None
        # tenant_access_token 缓存: (token, expires_at_monotonic)
        self._cached_token: tuple[str, float] | None = None
        # 注入式 httpx transport (供测试 mock HTTP; 生产为 None 走真实网络)
        self._http_transport: Any | None = None
        self.on_message = None  # type: ignore[assignment]  # 由 ChannelRegistry 注入

    @property
    def platform_name(self) -> str:
        return "feishu"

    async def start(self) -> None:
        """启动 webhook 回调服务端 (FastAPI + uvicorn Server, 独立端口)。

        未配置 app_id/app_secret 也能 start (服务可起, 但 send 会失败);
        未配置 verification_token/encrypt_key 时走明文模式 (所有事件直接信任,
        生产应至少配 verification_token)。
        """
        if self._running:
            return
        try:
            import uvicorn
            from fastapi import FastAPI
        except ImportError as exc:  # pragma: no cover - 依赖已在 pyproject.toml
            raise ImportError(
                "飞书适配器需要 fastapi + uvicorn (已在项目依赖中)。若缺失请运行 uv sync --all-extras"
            ) from exc
        app = FastAPI()
        app.add_api_route(self._webhook_path, self._handle_event, methods=["POST"])
        config = uvicorn.Config(
            app, host=self._webhook_host, port=self._webhook_port, log_level="warning",
        )
        self._server = uvicorn.Server(config)
        self._running = True
        self._serve_task = asyncio.create_task(
            self._server.serve(), name=f"feishu-webhook-{self._webhook_port}"
        )
        logger.info(
            "飞书适配器 webhook 服务已启动",
            app_id=self._app_id, host=self._webhook_host, port=self._webhook_port, path=self._webhook_path,
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

    async def _handle_event(self, request: Request) -> dict:
        """Webhook 入站主入口: 校验/解密 → 规范化 → on_message → 200 ``{}``。

        任何异常都吞掉并返回 200 ``{}`` (避免飞书重试; 失败的入站消息丢失在
        日志里, 不影响主链路)。所有处理都在 try/except 里, 保证不阻塞响应。
        """
        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("飞书 webhook 收到非 JSON 请求体", error=str(exc))
            return {}
        try:
            payload = self._decode_payload(body)
            if payload is None:
                return {}  # 解密失败已记 warning
            event_type = str(payload.get("type") or payload.get("header", {}).get("event_type", "") or "")
            if event_type == "url_verification" or "challenge" in payload:
                # URL 校验挑战: 原样回 challenge (飞书据此判定 URL 有效)。
                # 仅明文模式校验 verification_token (加密模式 encrypt_key 已证身份);
                # 校验失败抛 ValueError 由外层吞掉 → 返回空 dict (不回 challenge)。
                if not self._encrypt_key:
                    self._verify_token(payload)
                return {"challenge": payload.get("challenge", "")}
            # 常规事件: 加密模式由 encrypt_key 证明身份, 跳过 token 校验;
            # 明文模式必须配置 verification_token (否则拒绝, 见 _verify_token)。
            if not self._encrypt_key:
                self._verify_token(payload)
            if event_type != "im.message.receive_v1":
                logger.debug("飞书 webhook 忽略非消息事件", event_type=event_type)
                return {}
            msg = self._build_isac_message(payload)
            if msg is not None and self.on_message is not None:
                # on_message 是主链路入口, 异步派生处理任务, 不阻塞响应
                try:
                    await self.on_message(msg)  # type: ignore[misc]
                except Exception as exc:  # noqa: BLE001
                    logger.warning("飞书 on_message 处理异常", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.warning("飞书 webhook 处理事件异常", error=str(exc), exc_info=True)
        return {}

    def _decode_payload(self, body: Any) -> dict | None:
        """加密模式 (``encrypt_key`` 已配置): 从 ``{"encrypt": ...}`` 解密得 inner
        JSON; 明文模式 (未配置 ``encrypt_key``): 原样返回。

        Fix-23: 已配置 ``encrypt_key`` 时, 请求体必须含 ``"encrypt"`` 字段, 否则
        直接拒绝 —— 不能"看请求体形状"决定信任级别。此前的逻辑是"不含 encrypt
        字段就走明文模式", 而 ``_handle_event`` 又用"配了 encrypt_key 就跳过
        token 校验"(假设加密本身已证明身份); 两者叠加意味着已配置 encrypt_key 时,
        攻击者只需不带 "encrypt" 字段发送明文伪造事件, 既不必知道 encrypt_key
        也不必知道 verification_token, 就能让伪造消息完全绕过验证直达 on_message。
        """
        if not isinstance(body, dict):
            return None
        has_encrypt_field = "encrypt" in body
        if self._encrypt_key:
            if not has_encrypt_field:
                logger.warning("飞书 webhook 已配置 encrypt_key 但收到明文请求体, 拒绝")
                return None
            return self._decrypt(body["encrypt"])
        if has_encrypt_field:
            logger.warning("飞书 webhook 收到加密事件但未配置 encrypt_key, 丢弃")
            return None
        return body  # 明文模式

    def _decrypt(self, encrypt_b64: str) -> dict | None:
        """AES-256-CBC 解密 (字节序核对自飞书官方文档)。

        key = SHA256(encrypt_key); enc = base64decode(encrypt); iv = enc[:16];
        ciphertext = enc[16:]; plain = AES.new(key, CBC, iv).decrypt(ciphertext);
        PKCS7 unpad → UTF-8 JSON 字符串 → json.loads。
        """
        import base64

        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives.padding import PKCS7

        try:
            key = hashlib.sha256(self._encrypt_key.encode("utf-8")).digest()
            enc = base64.b64decode(encrypt_b64)
            if len(enc) < 16 + 16:  # iv 至少 16 字节, ciphertext 至少 1 block
                logger.warning("飞书加密事件密文过短", length=len(enc))
                return None
            iv = enc[:16]
            ciphertext = enc[16:]
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
            decryptor = cipher.decryptor()
            padded = decryptor.update(ciphertext) + decryptor.finalize()
            unpadder = PKCS7(128).unpadder()
            plain = unpadder.update(padded) + unpadder.finalize()
            return json.loads(plain.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("飞书事件解密失败", error=str(exc))
            return None

    def _verify_token(self, payload: dict) -> None:
        """明文模式: 校验 header.token == verification_token。

        未配置 verification_token 时拒绝事件 (而非跳过校验): 飞书 webhook
        对外可达, 跳过校验会让任意身份伪造 im.message.receive_v1 事件触发
        on_message; 显式拒绝 + 返回空 dict 不回 challenge, 防止 fail-open
        注入。加密模式由 encrypt_key 证明身份, 不走此路径。
        """
        if not self._verification_token:
            logger.warning("飞书 webhook 未配置 verification_token, 拒绝事件")
            raise ValueError("verification_token not configured")
        token = str((payload.get("header") or {}).get("token", "") or payload.get("token", "") or "")
        if not hmac.compare_digest(token, self._verification_token):
            token_fingerprint = hashlib.sha256(token.encode()).hexdigest()[:8]
            logger.warning("飞书事件 verification_token 不符, 丢弃", token_fingerprint=token_fingerprint)
            raise ValueError("verification_token mismatch")

    def _build_isac_message(self, payload: dict) -> ISACMessage | None:
        """从 im.message.receive_v1 事件体规范化 ISACMessage。"""
        event = payload.get("event") or {}
        message = event.get("message") or {}
        sender = event.get("sender") or {}
        chat_id = str(message.get("chat_id", "") or "")
        open_id = str((sender.get("sender_id") or {}).get("open_id", "") or "")
        message_id = str(message.get("message_id", "") or "")
        msg_type = str(message.get("message_type", "") or "")
        content_str = str(message.get("content", "") or "")
        text = _parse_message_content(msg_type, content_str)
        if not open_id:
            logger.warning("飞书事件缺 sender open_id, 丢弃", message_id=message_id)
            return None
        return ISACMessage(
            msg_id=message_id,
            platform="feishu",
            timestamp=int(time.time()),
            user_id=open_id,
            user_name=open_id,  # 飞书不直接给昵称, 用 open_id 占位 (N3 归一后可填充)
            group_id=chat_id or None,  # chat_id 非空时视为群聊 (含 oc_ 前缀)
            content=text,
        )

    async def send(self, message: ISACMessage) -> bool:
        """发送文本消息到飞书 (chat_id 或 open_id)。

        receive_id 取 group_id (群聊) 或 user_id (私聊 open_id), receive_id_type
        相应设置。token 换取/发送失败返回 False (不抛异常)。
        """
        if not self._app_id or not self._app_secret:
            logger.warning("飞书 send 缺 app_id/app_secret, 跳过")
            return False
        receive_id = str(message.group_id or message.user_id or "")
        if not receive_id:
            logger.warning("飞书 send 缺 receive_id (group_id/user_id 均空)")
            return False
        receive_id_type = "chat_id" if message.group_id else "open_id"
        token = await self._get_tenant_access_token()
        if not token:
            return False
        content_json = json.dumps({"text": str(message.content or "")}, ensure_ascii=False)
        body = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": content_json,
        }
        try:
            resp = await self._http_post(
                f"{self._api_base}{_SEND_MESSAGE_PATH}",
                params={"receive_id_type": receive_id_type},
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
                json_body=body,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("飞书 send 消息发送失败", error=str(exc))
            return False
        if resp is None:
            return False
        # NOTE: 用 `code is None` 判定而非 `or` —— 0 在 Python 是 falsy, `0 or -1` = -1
        # 会误判 code=0 失败 (飞书 code=0 才是成功)。
        code_raw = resp.get("code")
        code = -1 if code_raw is None else int(code_raw)
        if code != 0:
            logger.warning("飞书 send 返回非 0 code", code=code, msg=resp.get("msg", ""))
            return False
        return True

    async def _get_tenant_access_token(self) -> str | None:
        """获取 tenant_access_token (缓存 + 提前 60s 刷新)。"""
        if self._cached_token is not None:
            token, expires_at = self._cached_token
            if time.monotonic() < expires_at:
                return token
        body = {"app_id": self._app_id, "app_secret": self._app_secret}
        try:
            resp = await self._http_post(
                f"{self._api_base}{_TENANT_TOKEN_PATH}",
                json_body=body,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("飞书 tenant_access_token 换取失败", error=str(exc))
            return None
        if resp is None:
            return None
        # NOTE: 用 `code is None` 判定而非 `or` —— 0 在 Python 是 falsy, `0 or -1` = -1
        # 会误判 code=0 失败 (飞书 code=0 才是成功)。
        code_raw = resp.get("code")
        code = -1 if code_raw is None else int(code_raw)
        if code != 0:
            logger.warning("飞书 tenant_access_token 返回非 0", code=code, msg=resp.get("msg", ""))
            return None
        token = str(resp.get("tenant_access_token", "") or "")
        expire = int(resp.get("expire", 7200) or 7200)
        if not token:
            return None
        self._cached_token = (token, time.monotonic() + max(60, expire - _TOKEN_REFRESH_LEAD_SECONDS))
        return token

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
            logger.warning("飞书 HTTP 非 2xx", url=url, status=resp.status_code, body=resp.text[:200])
            return None
        try:
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("飞书 HTTP 响应非 JSON", url=url, error=str(exc))
            return None

    def set_http_transport(self, transport: Any) -> None:
        """供测试注入 httpx.MockTransport (生产不调用)。"""
        self._http_transport = transport


def _parse_message_content(msg_type: str, content_str: str) -> str:
    """从 event.message.content (JSON 字符串) 解析纯文本。

    text 类型: ``{"text": "hello"}`` → ``hello``;
    其他类型 (image/post/file…) 暂返回占位文本 (不阻塞主链路)。
    """
    if not content_str:
        return ""
    try:
        content = json.loads(content_str)
    except Exception:  # noqa: BLE001
        return content_str  # 非 JSON 时降级用原始字符串
    if msg_type == "text" and isinstance(content, dict):
        return str(content.get("text", "") or "")
    if isinstance(content, dict):
        # post 类型有 title/description 字段, 提取作占位
        return str(content.get("title", "") or content.get("description", "") or "")
    return ""
