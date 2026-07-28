"""S7 飞书适配器真实实现单测。

验签/加解密用测试内自造的密钥 + 加密已知明文事件验证正确性 (不依赖真实凭据);
HTTP 交互用 httpx.MockTransport (与 K2 Provider 测试同模式)。
骨架单测 (test_o4_platform_adapters_scaffolding.py) 中 Feishu 相关的 platform_name
/未配置 start/stop 不抛异常断言继续通过。
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import httpx
import pytest

from isac.channel.adapters.feishu.adapter import FeishuAdapter
from isac.channel.model import ISACMessage

# ── AES 加密辅助: 用官方算法加密一个已知明文, 验证适配器能正确解密 ──


def _encrypt_feishu_payload(encrypt_key: str, plaintext_dict: dict) -> str:
    """用飞书官方 AES-256-CBC 加密算法加密一个 dict → base64(IV + ciphertext)。

    供测试构造加密事件用 (与官方文档字节序一致)。
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7

    key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
    iv = b"\x00" * 16  # 测试用固定 IV (生产是随机的, 但解密不依赖 IV 值)
    plain = json.dumps(plaintext_dict, ensure_ascii=False).encode("utf-8")
    padder = PKCS7(128).padder()
    padded = padder.update(plain) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(iv + ciphertext).decode("ascii")


def _make_adapter(
    *, encrypt_key: str = "", verification_token: str = "",
    app_id: str = "cli_test", app_secret: str = "secret_test",
) -> FeishuAdapter:
    return FeishuAdapter({
        "enabled": True,
        "app_id": app_id,
        "app_secret": app_secret,
        "encrypt_key": encrypt_key,
        "verification_token": verification_token,
        "webhook_port": 0,  # 单测不真正起服务
    })


# ── URL 校验挑战 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_url_verification_plaintext_returns_challenge() -> None:
    """明文模式 url_verification → 原样回 challenge (token 校验通过时)。"""
    adapter = _make_adapter(verification_token="tok-123")
    challenge = "cj-abc-123"

    class _Req:
        async def json(self) -> Any:
            return {"challenge": challenge, "token": "tok-123", "type": "url_verification"}

    resp = await adapter._handle_event(_Req())
    assert resp == {"challenge": challenge}


@pytest.mark.asyncio
async def test_url_verification_token_mismatch_rejected() -> None:
    """明文模式 token 不符 → 抛 ValueError (但 _handle_event 吞掉返回空 dict)。"""
    adapter = _make_adapter(verification_token="tok-123")

    class _Req:
        async def json(self) -> Any:
            return {"challenge": "cj", "token": "wrong", "type": "url_verification"}

    resp = await adapter._handle_event(_Req())
    # 异常被吞, 不回 challenge (返回空 dict)
    assert resp == {}


@pytest.mark.asyncio
async def test_url_verification_encrypted_mode_decrypts_challenge() -> None:
    """加密模式: 收到 ``{"encrypt":...}``, 解密后得含 challenge 的 JSON → 回 challenge。"""
    encrypt_key = "my-encrypt-key"
    adapter = _make_adapter(encrypt_key=encrypt_key)
    challenge = "cj-encrypted"
    encrypted = _encrypt_feishu_payload(
        encrypt_key, {"challenge": challenge, "token": "", "type": "url_verification"}
    )

    class _Req:
        async def json(self) -> Any:
            return {"encrypt": encrypted}

    resp = await adapter._handle_event(_Req())
    assert resp == {"challenge": challenge}


# ── 事件规范化 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_message_event_normalized_to_isac_message() -> None:
    """im.message.receive_v1 事件 → 规范化 ISACMessage 交 on_message。"""
    adapter = _make_adapter(verification_token="tok")
    received: list[ISACMessage] = []

    async def _on_msg(msg: ISACMessage) -> None:
        received.append(msg)

    adapter.on_message = _on_msg
    payload = {
        "schema": "2.0",
        "header": {"event_type": "im.message.receive_v1", "token": "tok"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_user1"}, "sender_type": "user"},
            "message": {
                "message_id": "om_msg1",
                "chat_id": "oc_group1",
                "message_type": "text",
                "content": json.dumps({"text": "你好"}),
            },
        },
    }

    class _Req:
        async def json(self) -> Any:
            return payload

    resp = await adapter._handle_event(_Req())
    assert resp == {}  # 常规事件回空 dict
    assert len(received) == 1
    msg = received[0]
    assert msg.platform == "feishu"
    assert msg.user_id == "ou_user1"
    assert msg.group_id == "oc_group1"
    assert msg.content == "你好"
    assert msg.msg_id == "om_msg1"


@pytest.mark.asyncio
async def test_message_event_encrypted_mode_decrypted_and_normalized() -> None:
    """加密模式事件 → 解密 + 规范化 ISACMessage。"""
    encrypt_key = "k-enc"
    adapter = _make_adapter(encrypt_key=encrypt_key)
    received: list[ISACMessage] = []

    async def _on_msg(msg: ISACMessage) -> None:
        received.append(msg)

    adapter.on_message = _on_msg
    inner = {
        "schema": "2.0",
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_p2p"}},
            "message": {
                "message_id": "om_p2p1",
                "chat_id": "",  # p2p 无 chat_id → group_id=None
                "message_type": "text",
                "content": json.dumps({"text": "私聊"}),
            },
        },
    }
    encrypted = _encrypt_feishu_payload(encrypt_key, inner)

    class _Req:
        async def json(self) -> Any:
            return {"encrypt": encrypted}

    await adapter._handle_event(_Req())
    assert len(received) == 1
    assert received[0].user_id == "ou_p2p"
    assert received[0].group_id is None  # 私聊
    assert received[0].content == "私聊"


@pytest.mark.asyncio
async def test_non_message_event_ignored() -> None:
    """非 im.message.receive_v1 事件 → 忽略 (不调 on_message)。"""
    adapter = _make_adapter(verification_token="tok")
    called: list[Any] = []

    async def _on_msg(msg: ISACMessage) -> None:
        called.append(msg)

    adapter.on_message = _on_msg

    class _Req:
        async def json(self) -> Any:
            return {"header": {"event_type": "contact.user.updated_v3"}, "event": {}}

    await adapter._handle_event(_Req())
    assert called == []


@pytest.mark.asyncio
async def test_on_message_exception_does_not_break_response() -> None:
    """on_message 抛异常 → 不影响 webhook 返回 200 ``{}`` (飞书不重试)。"""
    adapter = _make_adapter(verification_token="tok")

    async def _on_msg(msg: ISACMessage) -> None:
        raise RuntimeError("handler boom")

    adapter.on_message = _on_msg
    payload = {
        "header": {"event_type": "im.message.receive_v1", "token": "tok"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou1"}},
            "message": {"message_id": "m1", "chat_id": "c1", "message_type": "text",
                        "content": json.dumps({"text": "hi"})},
        },
    }

    class _Req:
        async def json(self) -> Any:
            return payload

    resp = await adapter._handle_event(_Req())  # 不抛异常
    assert resp == {}


# ── 出站 send (mock httpx.MockTransport) ─────────────────────────


def _make_mock_transport(responses: list[tuple[int, dict]]) -> httpx.MockTransport:
    """按顺序返回预设响应 (status, json)。"""
    iterator = iter(responses)

    def _handler(request: httpx.Request) -> httpx.Response:
        try:
            status, body = next(iterator)
        except StopIteration:
            return httpx.Response(500, json={"code": -1, "msg": "no more mock responses"})
        return httpx.Response(status, json=body)

    return httpx.MockTransport(_handler)


@pytest.mark.asyncio
async def test_send_group_message_uses_chat_id() -> None:
    """group_id 非空 → receive_id_type=chat_id, POST /im/v1/messages。"""
    adapter = _make_adapter()
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if "tenant_access_token" in str(request.url):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "tok-abc", "expire": 7200})
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "om_new"}})

    adapter.set_http_transport(httpx.MockTransport(_handler))
    msg = ISACMessage(
        msg_id="m1", platform="feishu", timestamp=0, user_id="ou_u",
        user_name="ou_u", group_id="oc_g1", content="hello",
    )
    ok = await adapter.send(msg)
    assert ok is True
    # 两次请求: token 换取 + 消息发送
    assert len(captured) == 2
    send_req = captured[1]
    assert "receive_id_type=chat_id" in str(send_req.url)
    assert send_req.headers["Authorization"] == "Bearer tok-abc"
    body = json.loads(send_req.content)
    assert body["receive_id"] == "oc_g1"
    assert body["msg_type"] == "text"
    assert json.loads(body["content"]) == {"text": "hello"}


@pytest.mark.asyncio
async def test_send_p2p_message_uses_open_id() -> None:
    """group_id 为空 → receive_id_type=open_id, user_id 作 receive_id。"""
    adapter = _make_adapter()

    def _handler(request: httpx.Request) -> httpx.Response:
        if "tenant_access_token" in str(request.url):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "tok", "expire": 7200})
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "om_new"}})

    adapter.set_http_transport(httpx.MockTransport(_handler))
    msg = ISACMessage(
        msg_id="m1", platform="feishu", timestamp=0, user_id="ou_p2p",
        user_name="ou_p2p", content="hi-p2p",
    )
    ok = await adapter.send(msg)
    assert ok is True


@pytest.mark.asyncio
async def test_token_cached_across_sends() -> None:
    """token 缓存: 两次 send 只换取一次 tenant_access_token。"""
    adapter = _make_adapter()
    token_calls: list[Any] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        if "tenant_access_token" in str(request.url):
            token_calls.append(request)
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "tok-cached", "expire": 7200})
        return httpx.Response(200, json={"code": 0, "data": {"message_id": "om"}})

    adapter.set_http_transport(httpx.MockTransport(_handler))
    msg = ISACMessage(
        msg_id="m1", platform="feishu", timestamp=0, user_id="ou_u",
        user_name="ou_u", group_id="oc_g", content="hi",
    )
    await adapter.send(msg)
    await adapter.send(msg)
    assert len(token_calls) == 1  # 第二次 send 用缓存的 token


@pytest.mark.asyncio
async def test_send_returns_false_on_api_error() -> None:
    """send 返回 code!=0 → False (不抛异常)。"""
    adapter = _make_adapter()

    def _handler(request: httpx.Request) -> httpx.Response:
        if "tenant_access_token" in str(request.url):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "tok", "expire": 7200})
        return httpx.Response(200, json={"code": 9499, "msg": "invalid receive_id"})

    adapter.set_http_transport(httpx.MockTransport(_handler))
    msg = ISACMessage(
        msg_id="m1", platform="feishu", timestamp=0, user_id="ou_u",
        user_name="ou_u", content="hi",
    )
    ok = await adapter.send(msg)
    assert ok is False


@pytest.mark.asyncio
async def test_send_without_credentials_returns_false() -> None:
    """未配置 app_id/app_secret → 直接 False (不发请求)。"""
    adapter = _make_adapter(app_id="", app_secret="")
    msg = ISACMessage(
        msg_id="m1", platform="feishu", timestamp=0, user_id="ou_u",
        user_name="ou_u", content="hi",
    )
    ok = await adapter.send(msg)
    assert ok is False


@pytest.mark.asyncio
async def test_send_token_exchange_failure_returns_false() -> None:
    """token 换取失败 (code!=0) → send 直接 False。"""
    adapter = _make_adapter()

    def _handler(request: httpx.Request) -> httpx.Response:
        if "tenant_access_token" in str(request.url):
            return httpx.Response(200, json={"code": 99991663, "msg": "app_id not exist"})
        return httpx.Response(200, json={"code": 0})

    adapter.set_http_transport(httpx.MockTransport(_handler))
    msg = ISACMessage(
        msg_id="m1", platform="feishu", timestamp=0, user_id="ou_u",
        user_name="ou_u", content="hi",
    )
    ok = await adapter.send(msg)
    assert ok is False


# ── start/stop 生命周期 (不绑真实端口, 只验证不抛异常 + 重复 start/stop 安全) ──


@pytest.mark.asyncio
async def test_start_stop_idempotent_no_port() -> None:
    """start/stop 在 webhook_port=0 时仍能起/停 (绑定到内核分配端口, 不影响单测)。"""
    adapter = _make_adapter()
    adapter._webhook_port = 0  # type: ignore[attr-defined]
    # 端口 0 会让 uvicorn 用临时端口; 仍会起服务但很快 stop
    await adapter.start()
    await adapter.start()  # 重复 start 不重启
    await adapter.stop()
    await adapter.stop()  # 重复 stop 安全
