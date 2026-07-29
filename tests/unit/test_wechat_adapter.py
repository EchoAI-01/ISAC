"""O4 企业微信适配器真实实现单测。

加解密用测试内自造的 encoding_aes_key + 加密已知明文 XML 验证正确性 (不依赖真实凭据);
HTTP 交互用 httpx.MockTransport (与飞书适配器测试同模式)。
"""

from __future__ import annotations

import base64
import hashlib
import struct
from typing import Any

import httpx
import pytest
from fastapi.responses import PlainTextResponse

from isac.channel.adapters.wechat.adapter import (
    WeChatAdapter,
    WeComAdapter,
    _extract_encrypt,
    _parse_wecom_xml,
)
from isac.channel.model import ISACMessage

# ── AES 加密辅助: 用企业微信官方算法加密一个 dict → base64(IV + ciphertext) ──


def _make_aes_key(encoding_aes_key: str) -> bytes:
    """企业微信 key = base64decode(encoding_aes_key + "=")。"""
    return base64.b64decode(encoding_aes_key + "=")


def _encrypt_wecom_payload(encoding_aes_key: str, plain_xml: str, to_user: str = "corp123") -> str:
    """用企业微信 WXBizMsgCrypt 算法加密: 16 字节随机串 + 4 字节大端 msg_len +
    to_user + xml 正文, 然后 AES-256-CBC 加密, 输出 base64(IV + ciphertext)。

    供测试构造加密事件用 (与官方文档字节序一致)。
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7

    key = _make_aes_key(encoding_aes_key)
    iv = b"\x00" * 16  # 测试用固定 IV (生产是随机的, 但解密不依赖 IV 值)
    random_16 = b"\x01" * 16
    to_user_bytes = to_user.encode("utf-8")
    xml_bytes = plain_xml.encode("utf-8")
    msg_len = struct.pack(">I", len(to_user_bytes))
    plain = random_16 + msg_len + to_user_bytes + xml_bytes
    padder = PKCS7(128).padder()
    padded = padder.update(plain) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(iv + ciphertext).decode("ascii")


def _sign(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    """企业微信签名: sha1(sort([token, timestamp, nonce, encrypt])).hexdigest()。"""
    parts = sorted([token, timestamp, nonce, encrypt])
    return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()


def _make_adapter(
    *,
    corp_id: str = "corp_test",
    agent_id: str = "1000001",
    secret: str = "secret_test",
    token: str = "tok-123",
    encoding_aes_key: str = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG",
    webhook_port: int = 0,
) -> WeComAdapter:
    return WeComAdapter({
        "enabled": True,
        "mode": "wecom",
        "corp_id": corp_id,
        "agent_id": agent_id,
        "secret": secret,
        "token": token,
        "encoding_aes_key": encoding_aes_key,
        "webhook_port": webhook_port,
    })


def _make_request(method: str, query: dict, body: bytes = b"") -> Any:
    """构造测试用 Request stub。"""

    class _Req:
        def __init__(self, m: str, q: dict, b: bytes) -> None:
            self.method = m
            self.query_params = q
            self._body = b

        async def body(self) -> bytes:
            return self._body

    return _Req(method, query, body)


# ── URL 校验挑战 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_url_verification_returns_decrypted_echostr() -> None:
    """GET 回调: 校验签名通过 → 解密 echostr → 返回明文 echostr。"""
    adapter = _make_adapter()
    plain_echostr = "hello-echo-123"
    encrypted = _encrypt_wecom_payload(adapter._encoding_aes_key, plain_echostr, to_user=adapter._corp_id)
    timestamp = "1700000000"
    nonce = "nonce-abc"
    signature = _sign(adapter._token, timestamp, nonce, encrypted)

    req = _make_request("GET", {
        "msg_signature": signature, "timestamp": timestamp, "nonce": nonce, "echostr": encrypted,
    })
    resp = await adapter._handle_event(req)
    assert isinstance(resp, PlainTextResponse)
    assert resp.body == plain_echostr.encode("utf-8")


@pytest.mark.asyncio
async def test_url_verification_signature_mismatch_rejected() -> None:
    """GET 回调: 签名不符 → 返回 "success" (不回 echostr 明文, 防伪造)。"""
    adapter = _make_adapter()
    encrypted = _encrypt_wecom_payload(adapter._encoding_aes_key, "plain", to_user=adapter._corp_id)

    req = _make_request("GET", {
        "msg_signature": "wrong-signature", "timestamp": "1700000000",
        "nonce": "n", "echostr": encrypted,
    })
    resp = await adapter._handle_event(req)
    assert isinstance(resp, PlainTextResponse)
    assert resp.body == b"success"


@pytest.mark.asyncio
async def test_url_verification_missing_token_config_rejected() -> None:
    """未配置 token 时 fail-closed: 拒绝所有 URL 校验 (不允许无签名校验的回调)。"""
    adapter = _make_adapter(token="")
    encrypted = _encrypt_wecom_payload(adapter._encoding_aes_key, "plain", to_user=adapter._corp_id)

    req = _make_request("GET", {
        "msg_signature": "any", "timestamp": "1700000000",
        "nonce": "n", "echostr": encrypted,
    })
    resp = await adapter._handle_event(req)
    assert isinstance(resp, PlainTextResponse)
    assert resp.body == b"success"


@pytest.mark.asyncio
async def test_url_verification_missing_encoding_aes_key_rejected() -> None:
    """未配置 encoding_aes_key 时拒绝解密 (与飞书一致, 不允许明文模式事件)。"""
    adapter = _make_adapter(encoding_aes_key="")
    encrypted = "dummy-base64"
    timestamp = "1700000000"
    nonce = "n"
    signature = _sign("tok-123", timestamp, nonce, encrypted)

    req = _make_request("GET", {
        "msg_signature": signature, "timestamp": timestamp, "nonce": nonce, "echostr": encrypted,
    })
    resp = await adapter._handle_event(req)
    assert isinstance(resp, PlainTextResponse)
    assert resp.body == b"success"


# ── 消息回调 ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_message_callback_decrypts_and_normalizes_to_isac_message() -> None:
    """POST 回调: 校验签名 → AES 解密 → XML 解析 → 规范化为 ISACMessage 交 on_message。"""
    adapter = _make_adapter()
    received: list[ISACMessage] = []

    async def _on_msg(msg: ISACMessage) -> None:
        received.append(msg)

    adapter.on_message = _on_msg
    inner_xml = (
        "<xml>"
        "<ToUserName><![CDATA[corp_test]]></ToUserName>"
        "<FromUserName><![CDATA[user_wecom_1]]></FromUserName>"
        "<CreateTime>1700000000</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        "<Content><![CDATA[你好世界]]></Content>"
        "<MsgId>1234567890</MsgId>"
        "<AgentID>1000001</AgentID>"
        "</xml>"
    )
    encrypted = _encrypt_wecom_payload(adapter._encoding_aes_key, inner_xml, to_user=adapter._corp_id)
    outer_xml = f"<xml><Encrypt><![CDATA[{encrypted}]]></Encrypt></xml>"
    timestamp = "1700000000"
    nonce = "nonce-xyz"
    signature = _sign(adapter._token, timestamp, nonce, encrypted)

    req = _make_request("POST", {
        "msg_signature": signature, "timestamp": timestamp, "nonce": nonce,
    }, outer_xml.encode("utf-8"))
    resp = await adapter._handle_event(req)
    assert isinstance(resp, PlainTextResponse)
    assert resp.body == b"success"
    assert len(received) == 1
    msg = received[0]
    assert msg.platform == "wechat"
    assert msg.user_id == "user_wecom_1"
    assert msg.content == "你好世界"
    assert msg.msg_id == "1234567890"
    assert msg.group_id is None  # 企业微信应用消息无私聊/群聊区分


@pytest.mark.asyncio
async def test_message_callback_signature_mismatch_rejected() -> None:
    """POST 回调: 签名不符 → 拒绝, 不调 on_message。"""
    adapter = _make_adapter()
    received: list[ISACMessage] = []

    async def _on_msg(msg: ISACMessage) -> None:
        received.append(msg)

    adapter.on_message = _on_msg
    inner_xml = (
        "<xml>"
        "<FromUserName><![CDATA[u1]]></FromUserName>"
        "<MsgType><![CDATA[text]]></MsgType>"
        "<Content><![CDATA[hi]]></Content>"
        "<MsgId>1</MsgId>"
        "</xml>"
    )
    encrypted = _encrypt_wecom_payload(adapter._encoding_aes_key, inner_xml, to_user=adapter._corp_id)
    outer_xml = f"<xml><Encrypt><![CDATA[{encrypted}]]></Encrypt></xml>"

    req = _make_request("POST", {
        "msg_signature": "wrong-signature", "timestamp": "1700000000", "nonce": "n",
    }, outer_xml.encode("utf-8"))
    resp = await adapter._handle_event(req)
    assert resp.body == b"success"
    assert received == []


@pytest.mark.asyncio
async def test_message_callback_missing_encrypt_field_rejected() -> None:
    """POST 回调: 缺 Encrypt 字段 → 拒绝 (明文模式不安全)。"""
    adapter = _make_adapter()
    received: list[ISACMessage] = []

    async def _on_msg(msg: ISACMessage) -> None:
        received.append(msg)

    adapter.on_message = _on_msg
    # 故意不含 Encrypt 字段
    plain_xml = "<xml><ToUserName>corp</ToUserName><Content>plain</Content></xml>"

    req = _make_request("POST", {
        "msg_signature": "any", "timestamp": "1700000000", "nonce": "n",
    }, plain_xml.encode("utf-8"))
    resp = await adapter._handle_event(req)
    assert resp.body == b"success"
    assert received == []


@pytest.mark.asyncio
async def test_message_callback_doctype_payload_rejected_before_signature_check() -> None:
    """安全回归: 恶意 DOCTYPE/ENTITY 载荷即使签名完全无效, 也必须在解析阶段就被拒绝
    (而不是被 ET.fromstring 展开), 端到端走完整 _handle_event 入口不抛异常/不挂起。"""
    adapter = _make_adapter()
    received: list[ISACMessage] = []

    async def _on_msg(msg: ISACMessage) -> None:
        received.append(msg)

    adapter.on_message = _on_msg
    malicious_outer = (
        "<!DOCTYPE xml ["
        "<!ENTITY lol \"lol\">"
        "<!ENTITY lol2 \"&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;\">"
        "]>"
        "<xml><Encrypt>&lol2;</Encrypt></xml>"
    )
    req = _make_request("POST", {
        "msg_signature": "any", "timestamp": "1700000000", "nonce": "n",
    }, malicious_outer.encode("utf-8"))
    resp = await adapter._handle_event(req)
    assert isinstance(resp, PlainTextResponse)
    assert resp.body == b"success"
    assert received == []


@pytest.mark.asyncio
async def test_message_callback_non_text_type_degraded_to_placeholder() -> None:
    """非 text 类型 (image/voice/event...) 降级为占位文本, 不阻塞主链路。"""
    adapter = _make_adapter()
    received: list[ISACMessage] = []

    async def _on_msg(msg: ISACMessage) -> None:
        received.append(msg)

    adapter.on_message = _on_msg
    inner_xml = (
        "<xml>"
        "<ToUserName><![CDATA[corp_test]]></ToUserName>"
        "<FromUserName><![CDATA[user_wecom_2]]></FromUserName>"
        "<CreateTime>1700000000</CreateTime>"
        "<MsgType><![CDATA[image]]></MsgType>"
        "<PicUrl><![CDATA[https://example.com/x.png]]></PicUrl>"
        "<MsgId>1234567891</MsgId>"
        "</xml>"
    )
    encrypted = _encrypt_wecom_payload(adapter._encoding_aes_key, inner_xml, to_user=adapter._corp_id)
    outer_xml = f"<xml><Encrypt><![CDATA[{encrypted}]]></Encrypt></xml>"
    timestamp = "1700000000"
    nonce = "n"
    signature = _sign(adapter._token, timestamp, nonce, encrypted)

    req = _make_request("POST", {
        "msg_signature": signature, "timestamp": timestamp, "nonce": nonce,
    }, outer_xml.encode("utf-8"))
    await adapter._handle_event(req)
    assert len(received) == 1
    msg = received[0]
    assert msg.content == "[image]"  # 占位文本, 不抛异常


# ── 工厂路由 (mode="wecom" → WeComAdapter, mode="mp" → 骨架) ───────────


def test_wechat_factory_wecom_routes_to_real_implementation() -> None:
    """mode="wecom" (默认) → WeChatAdapter 内部使用真实 WeComAdapter。"""
    adapter = WeChatAdapter({"mode": "wecom", "corp_id": "c", "agent_id": "1", "secret": "s"})
    assert isinstance(adapter._impl, WeComAdapter)


def test_wechat_factory_mp_keeps_skeleton_behavior() -> None:
    """mode="mp" → 保留骨架 (start/stop no-op, send 返回 False)。"""
    adapter = WeChatAdapter({"mode": "mp"})
    # 内部实现不是 WeComAdapter (公众号骨架)
    assert not isinstance(adapter._impl, WeComAdapter)


def test_wechat_factory_default_mode_is_wecom() -> None:
    """未指定 mode 时默认走企业微信 (与 config.sample.jsonc 默认值一致)。"""
    adapter = WeChatAdapter({})
    assert isinstance(adapter._impl, WeComAdapter)


# ── 出站 send (mock httpx.MockTransport) ─────────────────────────


def _make_mock_transport(responses: list[tuple[int, dict]]) -> httpx.MockTransport:
    """按顺序返回预设响应 (status, json)。"""
    iterator = iter(responses)

    def _handler(request: httpx.Request) -> httpx.Response:
        try:
            status, body = next(iterator)
        except StopIteration:
            return httpx.Response(500, json={"errcode": -1, "errmsg": "no more mock responses"})
        return httpx.Response(status, json=body)

    return httpx.MockTransport(_handler)


@pytest.mark.asyncio
async def test_send_text_message_succeeds() -> None:
    """access_token 换取 + message/send 两步均 errcode=0 → send 返回 True。"""
    adapter = _make_adapter()
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if "gettoken" in str(request.url.path):
            return httpx.Response(200, json={"errcode": 0, "access_token": "tok-abc", "expires_in": 7200})
        return httpx.Response(200, json={"errcode": 0, "msgid": "msg-1"})

    adapter.set_http_transport(httpx.MockTransport(_handler))
    msg = ISACMessage(
        msg_id="m1", platform="wechat", timestamp=0,
        user_id="user_wecom_1", user_name="user_wecom_1", content="hello",
    )
    ok = await adapter.send(msg)
    assert ok is True
    assert len(captured) == 2
    # 第二个请求是 message/send, 应带 touser + agentid + text.content
    send_req = captured[1]
    import json as _json
    body = _json.loads(send_req.content.decode("utf-8"))
    assert body["touser"] == "user_wecom_1"
    assert body["msgtype"] == "text"
    assert body["agentid"] == 1000001
    assert body["text"]["content"] == "hello"


@pytest.mark.asyncio
async def test_send_returns_false_when_missing_credentials() -> None:
    """缺 corp_id/secret/agent_id 时 send 返回 False (不发起请求)。"""
    adapter = _make_adapter(corp_id="", secret="", agent_id="")
    msg = ISACMessage(
        msg_id="m1", platform="wechat", timestamp=0,
        user_id="u1", user_name="u1", content="x",
    )
    ok = await adapter.send(msg)
    assert ok is False


@pytest.mark.asyncio
async def test_send_returns_false_when_token_fetch_fails() -> None:
    """token 换取失败 (errcode != 0) → send 返回 False, 不再调 message/send。"""
    adapter = _make_adapter()
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"errcode": 40013, "errmsg": "invalid corpid"})

    adapter.set_http_transport(httpx.MockTransport(_handler))
    msg = ISACMessage(
        msg_id="m1", platform="wechat", timestamp=0,
        user_id="u1", user_name="u1", content="x",
    )
    ok = await adapter.send(msg)
    assert ok is False
    assert call_count == 1  # 只调了 gettoken, 未调 message/send


@pytest.mark.asyncio
async def test_send_returns_false_when_message_send_returns_nonzero_errcode() -> None:
    """message/send 返回 errcode != 0 (如 42001 token 过期) → send 返回 False。"""
    adapter = _make_adapter()

    def _handler(request: httpx.Request) -> httpx.Response:
        if "gettoken" in str(request.url.path):
            return httpx.Response(200, json={"errcode": 0, "access_token": "tok-abc", "expires_in": 7200})
        return httpx.Response(200, json={"errcode": 42001, "errmsg": "access_token expired"})

    adapter.set_http_transport(httpx.MockTransport(_handler))
    msg = ISACMessage(
        msg_id="m1", platform="wechat", timestamp=0,
        user_id="u1", user_name="u1", content="x",
    )
    ok = await adapter.send(msg)
    assert ok is False


@pytest.mark.asyncio
async def test_access_token_cached_across_calls() -> None:
    """access_token 缓存 + 提前 60s 刷新: 连续两次 send 只换一次 token。"""
    adapter = _make_adapter()
    token_calls = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if "gettoken" in str(request.url.path):
            token_calls += 1
            return httpx.Response(200, json={"errcode": 0, "access_token": "tok-cached", "expires_in": 7200})
        return httpx.Response(200, json={"errcode": 0, "msgid": "msg-1"})

    adapter.set_http_transport(httpx.MockTransport(_handler))
    msg = ISACMessage(
        msg_id="m1", platform="wechat", timestamp=0,
        user_id="u1", user_name="u1", content="x",
    )
    await adapter.send(msg)
    await adapter.send(msg)
    assert token_calls == 1  # 第二次 send 复用第一次的 token, 不重新换取


# ── 辅助函数单测 ─────────────────────────────────────────────────


def test_extract_encrypt_parses_cdata_field() -> None:
    """_extract_encrypt 从外层 XML 提取 Encrypt 字段 (CDATA 自动解包)。"""
    xml = "<xml><Encrypt><![CDATA[abc123base64]]></Encrypt><Other>x</Other></xml>"
    assert _extract_encrypt(xml) == "abc123base64"


def test_extract_encrypt_returns_empty_on_invalid_xml() -> None:
    """非合法 XML 返回空串 (不抛异常)。"""
    assert _extract_encrypt("not xml") == ""


def test_extract_encrypt_returns_empty_when_missing_field() -> None:
    """XML 合法但无 Encrypt 字段 → 空串。"""
    assert _extract_encrypt("<xml><Other>x</Other></xml>") == ""


def test_extract_encrypt_rejects_doctype_entity_expansion_payload() -> None:
    """安全回归: 含 DOCTYPE/递归 ENTITY 声明的 "billion laughs" 载荷必须被直接拒绝
    (返回空串), 不能进入 ET.fromstring 被展开——该端点在这一步之前签名尚未校验,
    是完全未鉴权的输入。"""
    payload = (
        "<?xml version=\"1.0\"?>"
        "<!DOCTYPE xml ["
        "<!ENTITY lol \"lol\">"
        "<!ENTITY lol2 \"&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;\">"
        "<!ENTITY lol3 \"&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;\">"
        "]>"
        "<xml><Encrypt>&lol3;</Encrypt></xml>"
    )
    assert _extract_encrypt(payload) == ""


def test_extract_encrypt_rejects_case_insensitive_doctype() -> None:
    """DOCTYPE 关键字大小写/前导空白变体同样被拒绝 (小写 + 换行)。"""
    payload = "<xml>\n<!doctype\nxml [<!entity x \"y\">]>\n<Encrypt>z</Encrypt></xml>"
    assert _extract_encrypt(payload) == ""


def test_parse_wecom_xml_extracts_text_message() -> None:
    """_parse_wecom_xml 解析 text 类型消息 → ISACMessage。"""
    xml = (
        "<xml>"
        "<ToUserName><![CDATA[corp123]]></ToUserName>"
        "<FromUserName><![CDATA[user1]]></FromUserName>"
        "<CreateTime>1700000000</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        "<Content><![CDATA[hello]]></Content>"
        "<MsgId>123</MsgId>"
        "</xml>"
    )
    msg = _parse_wecom_xml(xml)
    assert msg is not None
    assert msg.platform == "wechat"
    assert msg.user_id == "user1"
    assert msg.content == "hello"
    assert msg.msg_id == "123"
    assert msg.timestamp == 1700000000


def test_parse_wecom_xml_returns_none_when_missing_from_user() -> None:
    """缺 FromUserName → 返回 None (无法定位消息来源, 丢弃)。"""
    xml = "<xml><MsgType><![CDATA[text]]></MsgType><Content><![CDATA[x]]></Content></xml>"
    assert _parse_wecom_xml(xml) is None


def test_parse_wecom_xml_non_text_degrades_to_placeholder() -> None:
    """非 text 类型 → 占位文本 [msg_type]。"""
    xml = (
        "<xml>"
        "<FromUserName><![CDATA[user1]]></FromUserName>"
        "<CreateTime>1700000000</CreateTime>"
        "<MsgType><![CDATA[event]]></MsgType>"
        "<MsgId>1</MsgId>"
        "</xml>"
    )
    msg = _parse_wecom_xml(xml)
    assert msg is not None
    assert msg.content == "[event]"


def test_parse_wecom_xml_rejects_doctype_entity_expansion_payload() -> None:
    """内层 XML 同样加 DOCTYPE/ENTITY 守卫做纵深防御。"""
    payload = "<!DOCTYPE xml [<!ENTITY x \"y\">]><xml><FromUserName>u</FromUserName></xml>"
    assert _parse_wecom_xml(payload) is None
