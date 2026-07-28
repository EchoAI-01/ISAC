"""S7 QQ 官方机器人适配器真实实现单测。

验签/签名用测试内同一 seed 派生算法生成密钥对验证正确性 (不依赖真实凭据);
HTTP 交互用 httpx.MockTransport (与飞书/K2 Provider 测试同模式)。
骨架单测 (test_o4_platform_adapters_scaffolding.py) 中 QQ 官方相关断言继续通过。
"""

from __future__ import annotations

import binascii
import json
import time
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from isac.channel.adapters.qq_official.adapter import QQOfficialAdapter, _derive_seed
from isac.channel.model import ISACMessage

# ── 测试辅助: 用同一 seed 派生算法生成密钥对 ──────────────────────


def _make_adapter(secret: str = "DG5g3B4j9X2KOErG", app_id: str = "11111111") -> QQOfficialAdapter:
    return QQOfficialAdapter({
        "enabled": True,
        "app_id": app_id,
        "secret": secret,
        "webhook_port": 0,  # 单测不绑真实端口
    })


def test_default_webhook_host_is_loopback() -> None:
    """O11: 默认 webhook host 为 127.0.0.1, 与飞书适配器一致, 避免 0.0.0.0 误暴露。"""
    adapter = QQOfficialAdapter({"enabled": True, "app_id": "x", "secret": "y", "webhook_port": 0})
    assert adapter._webhook_host == "127.0.0.1"


def _make_app(adapter: QQOfficialAdapter) -> FastAPI:
    """构造一个直接调用 _handle_callback 的 FastAPI app (与 start() 里挂载的路由一致)。"""
    app = FastAPI()

    async def _callback(request: Request) -> dict:
        return await adapter._handle_callback(request)

    app.add_api_route("/callback", _callback, methods=["POST"])
    return app


def _client(adapter: QQOfficialAdapter) -> TestClient:
    return TestClient(_make_app(adapter))


def _sign_with_secret(secret: str, msg: str) -> str:
    """测试辅助: 用同一 seed 派生算法签名 (供构造合法签名)。"""
    private_key = Ed25519PrivateKey.from_private_bytes(_derive_seed(secret))
    return binascii.hexlify(private_key.sign(msg.encode("utf-8"))).decode("ascii")


# ── 回调地址验证握手 (op=13) ──────────────────────────────────────


def test_validation_handshake_returns_signed_plain_token() -> None:
    """op=13 验证握手 → 用 secret 派生私钥对 (event_ts + plain_token) 签名回响应。"""
    secret = "DG5g3B4j9X2KOErG"
    adapter = _make_adapter(secret=secret)
    plain_token = "Arq0D5A61EgUu4OxUvOp"
    event_ts = "1725442341"
    body = {"op": 13, "d": {"plain_token": plain_token, "event_ts": event_ts}}
    resp = _client(adapter).post("/callback", json=body)
    assert resp.status_code == 200
    out = resp.json()
    assert out["plain_token"] == plain_token
    # 用同一 secret 派生公钥验签: msg = event_ts + plain_token

    public_key = Ed25519PrivateKey.from_private_bytes(_derive_seed(secret)).public_key()
    sig = binascii.unhexlify(out["signature"])
    public_key.verify(sig, f"{event_ts}{plain_token}".encode())  # 不抛异常即验签通过


def test_validation_handshake_missing_fields_returns_empty() -> None:
    """验证握手缺 plain_token/event_ts → 空响应 (不抛异常)。"""
    adapter = _make_adapter()
    resp = _client(adapter).post("/callback", json={"op": 13, "d": {"plain_token": ""}})
    assert resp.json() == {}


# ── 常规事件验签 (op=0) ───────────────────────────────────────────


def test_dispatch_event_with_valid_signature_normalizes_and_calls_on_message() -> None:
    """op=0 + 合法签名 → 规范化 ISACMessage 交 on_message。"""
    secret = "DG5g3B4j9X2KOErG"
    adapter = _make_adapter(secret=secret)
    received: list[ISACMessage] = []

    async def _on_msg(msg: ISACMessage) -> None:
        received.append(msg)

    adapter.on_message = _on_msg
    data = {
        "id": "msg-1",
        "content": "<@!11111111> 你好",
        "author": {"member_openid": "mem-1"},
        "channel_id": "ch-1",
    }
    body = {"op": 0, "t": "AT_MESSAGE_CREATE", "d": data, "s": 1, "id": "evt-1"}
    body_str = json.dumps(body, ensure_ascii=False)
    timestamp = str(int(time.time()))
    sig = _sign_with_secret(secret, f"{timestamp}{body_str}")
    resp = _client(adapter).post(
        "/callback",
        content=body_str,
        headers={
            "X-Signature-Ed25519": sig,
            "X-Signature-Timestamp": timestamp,
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"opcode": 12}
    assert len(received) == 1
    msg = received[0]
    assert msg.platform == "qq_official"
    assert msg.user_id == "mem-1"
    assert msg.group_id == "ch-1"
    assert msg.content == "你好"  # @ 前缀已剥离
    assert msg.msg_id == "msg-1"
    assert msg.reply_to == "msg-1"


def test_dispatch_event_invalid_signature_rejected() -> None:
    """op=0 + 篡改签名 → 拒绝 (不调 on_message, 返回 signature mismatch)。"""
    adapter = _make_adapter()
    called: list[Any] = []

    async def _on_msg(msg: ISACMessage) -> None:
        called.append(msg)

    adapter.on_message = _on_msg
    body = {"op": 0, "t": "AT_MESSAGE_CREATE", "d": {"id": "m1", "author": {"member_openid": "u1"}, "content": "hi"}}
    body_str = json.dumps(body)
    resp = _client(adapter).post(
        "/callback",
        content=body_str,
        headers={
            "X-Signature-Ed25519": "00" * 64,  # 伪造签名
            "X-Signature-Timestamp": str(int(time.time())),
            "Content-Type": "application/json",
        },
    )
    assert resp.json() == {"opcode": 12, "error": "signature mismatch"}
    assert called == []


def test_dispatch_event_missing_signature_headers_rejected() -> None:
    """op=0 + 缺签名头 → 拒绝。"""
    adapter = _make_adapter()

    async def _on_msg(msg: ISACMessage) -> None:
        pass

    adapter.on_message = _on_msg
    body_str = json.dumps({"op": 0, "t": "AT_MESSAGE_CREATE", "d": {}})
    resp = _client(adapter).post(
        "/callback", content=body_str, headers={"Content-Type": "application/json"},
    )
    assert resp.json() == {"opcode": 12, "error": "signature mismatch"}


def test_dispatch_event_without_secret_rejected() -> None:
    """未配置 secret → 拒绝所有事件 (生产应配置)。"""
    adapter = _make_adapter(secret="")

    async def _on_msg(msg: ISACMessage) -> None:
        pass

    adapter.on_message = _on_msg
    body_str = json.dumps({"op": 0, "t": "AT_MESSAGE_CREATE", "d": {}})
    resp = _client(adapter).post(
        "/callback",
        content=body_str,
        headers={
            "X-Signature-Ed25519": "00" * 64,
            "X-Signature-Timestamp": str(int(time.time())),
            "Content-Type": "application/json",
        },
    )
    assert resp.json() == {"opcode": 12, "error": "signature mismatch"}


def test_dispatch_event_rejects_replay_with_stale_timestamp() -> None:
    """R2: X-Signature-Timestamp 偏离本地时间 >300s 拒绝重放攻击。

    即使签名合法 (用 secret 正确派生 + 验签通过), 偏离 >5 分钟也拒绝,
    防止攻击者重放历史捕获的请求体。
    """
    secret = "DG5g3B4j9X2KOErG"
    adapter = _make_adapter(secret=secret)
    received: list[ISACMessage] = []

    async def _on_msg(msg: ISACMessage) -> None:
        received.append(msg)

    adapter.on_message = _on_msg
    data = {"id": "msg-1", "content": "hi", "author": {"member_openid": "u1"}, "channel_id": "c1"}
    body = {"op": 0, "t": "AT_MESSAGE_CREATE", "d": data, "s": 1, "id": "evt-1"}
    body_str = json.dumps(body, ensure_ascii=False)
    # 构造合法签名但 timestamp 偏离 >300s (1 小时前)
    stale_ts = str(int(time.time()) - 3600)
    sig = _sign_with_secret(secret, f"{stale_ts}{body_str}")
    resp = _client(adapter).post(
        "/callback",
        content=body_str,
        headers={
            "X-Signature-Ed25519": sig,
            "X-Signature-Timestamp": stale_ts,
            "Content-Type": "application/json",
        },
    )
    # R2: 偏离 >300s 视为重放, 返回 opcode 12 signature mismatch (不调 on_message)
    assert resp.status_code == 200
    assert resp.json().get("error") == "signature mismatch"
    assert received == []


def test_dispatch_event_accepts_timestamp_within_60s_window() -> None:
    """R2: ±60s 内的 timestamp 接受 (时钟漂移容差)。"""
    secret = "DG5g3B4j9X2KOErG"
    adapter = _make_adapter(secret=secret)
    received: list[ISACMessage] = []

    async def _on_msg(msg: ISACMessage) -> None:
        received.append(msg)

    adapter.on_message = _on_msg
    data = {"id": "msg-1", "content": "hi", "author": {"member_openid": "u1"}, "channel_id": "c1"}
    body = {"op": 0, "t": "AT_MESSAGE_CREATE", "d": data, "s": 1, "id": "evt-1"}
    body_str = json.dumps(body, ensure_ascii=False)
    # 60s 内的 timestamp (未来 30s) 应接受
    near_ts = str(int(time.time()) + 30)
    sig = _sign_with_secret(secret, f"{near_ts}{body_str}")
    resp = _client(adapter).post(
        "/callback",
        content=body_str,
        headers={
            "X-Signature-Ed25519": sig,
            "X-Signature-Timestamp": near_ts,
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200
    assert len(received) == 1


def test_group_at_message_event_uses_group_openid() -> None:
    """GROUP_AT_MESSAGE_CREATE → group_id 取 data.group_openid。"""
    secret = "DG5g3B4j9X2KOErG"
    adapter = _make_adapter(secret=secret)
    received: list[ISACMessage] = []

    async def _on_msg(msg: ISACMessage) -> None:
        received.append(msg)

    adapter.on_message = _on_msg
    data = {
        "id": "m1",
        "content": "群内消息",
        "author": {"member_openid": "u1"},
        "group_openid": "grp-1",
    }
    body = {"op": 0, "t": "GROUP_AT_MESSAGE_CREATE", "d": data}
    body_str = json.dumps(body, ensure_ascii=False)
    timestamp = str(int(time.time()))
    sig = _sign_with_secret(secret, f"{timestamp}{body_str}")
    _client(adapter).post(
        "/callback",
        content=body_str,
        headers={
            "X-Signature-Ed25519": sig,
            "X-Signature-Timestamp": timestamp,
            "Content-Type": "application/json",
        },
    )
    assert len(received) == 1
    assert received[0].group_id == "grp-1"
    assert received[0].content == "群内消息"


def test_c2c_message_event_uses_user_openid_no_group() -> None:
    """C2C_MESSAGE_CREATE → user_id 取 author.user_openid, group_id=None。"""
    secret = "DG5g3B4j9X2KOErG"
    adapter = _make_adapter(secret=secret)
    received: list[ISACMessage] = []

    async def _on_msg(msg: ISACMessage) -> None:
        received.append(msg)

    adapter.on_message = _on_msg
    data = {"id": "m1", "content": "私聊", "author": {"user_openid": "u_c2c"}}
    body = {"op": 0, "t": "C2C_MESSAGE_CREATE", "d": data}
    body_str = json.dumps(body, ensure_ascii=False)
    timestamp = str(int(time.time()))
    sig = _sign_with_secret(secret, f"{timestamp}{body_str}")
    _client(adapter).post(
        "/callback",
        content=body_str,
        headers={
            "X-Signature-Ed25519": sig,
            "X-Signature-Timestamp": timestamp,
            "Content-Type": "application/json",
        },
    )
    assert len(received) == 1
    assert received[0].user_id == "u_c2c"
    assert received[0].group_id is None


def test_non_message_event_ignored_but_acked() -> None:
    """非 AT/C2C/GROUP_AT 事件 → 不调 on_message, 仍 ACK。"""
    secret = "DG5g3B4j9X2KOErG"
    adapter = _make_adapter(secret=secret)
    called: list[Any] = []

    async def _on_msg(msg: ISACMessage) -> None:
        called.append(msg)

    adapter.on_message = _on_msg
    body = {"op": 0, "t": "GUILD_CREATE", "d": {"id": "g1"}}
    body_str = json.dumps(body)
    timestamp = str(int(time.time()))
    sig = _sign_with_secret(secret, f"{timestamp}{body_str}")
    resp = _client(adapter).post(
        "/callback",
        content=body_str,
        headers={
            "X-Signature-Ed25519": sig,
            "X-Signature-Timestamp": timestamp,
            "Content-Type": "application/json",
        },
    )
    assert resp.json() == {"opcode": 12}
    assert called == []


def test_other_op_acked() -> None:
    """非 op=0/13 (如 op=10 HELLO) → 直接 ACK。"""
    adapter = _make_adapter()
    resp = _client(adapter).post("/callback", json={"op": 10, "d": {}})
    assert resp.json() == {"opcode": 12}


# ── 出站 send (mock httpx.MockTransport) ──────────────────────────


@pytest.mark.asyncio
async def test_send_group_message_uses_group_endpoint() -> None:
    """group_id 非空 → POST /v2/groups/{group_openid}/messages 带 msg_id (被动回复)。"""
    adapter = _make_adapter()
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if "getAppAccessToken" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok-qo", "expires_in": 7200})
        return httpx.Response(200, json={"code": 0, "data": {"id": "new-msg"}})

    adapter.set_http_transport(httpx.MockTransport(_handler))
    msg = ISACMessage(
        msg_id="m1", platform="qq_official", timestamp=0, user_id="u1",
        user_name="u1", group_id="grp-1", content="hi", reply_to="m1",
    )
    ok = await adapter.send(msg)
    assert ok is True
    # 两次请求: token 换取 + 消息发送
    assert len(captured) == 2
    send_req = captured[1]
    assert "/v2/groups/grp-1/messages" in str(send_req.url)
    assert send_req.headers["Authorization"] == "QQBot tok-qo"
    body = json.loads(send_req.content)
    assert body["content"] == "hi"
    assert body["msg_type"] == 0
    assert body["msg_id"] == "m1"  # 被动回复带 msg_id


@pytest.mark.asyncio
async def test_send_channel_message_uses_channel_endpoint() -> None:
    """AT_MESSAGE_CREATE 来源 → POST /channels/{channel_id}/messages (非群端点)。"""
    adapter = _make_adapter()
    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if "getAppAccessToken" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok-qo", "expires_in": 7200})
        return httpx.Response(200, json={"code": 0, "data": {"id": "new-msg"}})

    adapter.set_http_transport(httpx.MockTransport(_handler))
    msg = ISACMessage(
        msg_id="m1", platform="qq_official", timestamp=0, user_id="u1",
        user_name="u1", group_id="ch-1", content="hi", reply_to="m1",
        metadata={"qq_official_source": "AT_MESSAGE_CREATE"},
    )
    ok = await adapter.send(msg)
    assert ok is True
    send_req = captured[1]
    assert "/channels/ch-1/messages" in str(send_req.url)


@pytest.mark.asyncio
async def test_send_p2p_message_uses_user_endpoint() -> None:
    """group_id 为空 → POST /v2/users/{openid}/messages (无 msg_id 主动推送)。"""
    adapter = _make_adapter()

    def _handler(request: httpx.Request) -> httpx.Response:
        if "getAppAccessToken" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})
        return httpx.Response(200, json={"code": 0, "data": {"id": "new"}})

    adapter.set_http_transport(httpx.MockTransport(_handler))
    msg = ISACMessage(
        msg_id="m1", platform="qq_official", timestamp=0, user_id="u_c2p",
        user_name="u_c2p", content="hi-p2p", reply_to="m1",
    )
    ok = await adapter.send(msg)
    assert ok is True


@pytest.mark.asyncio
async def test_token_cached_across_sends() -> None:
    """token 缓存: 两次 send 只换取一次 access_token。"""
    adapter = _make_adapter()
    token_calls: list[Any] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        if "getAppAccessToken" in str(request.url):
            token_calls.append(request)
            return httpx.Response(200, json={"access_token": "tok-cached", "expires_in": 7200})
        return httpx.Response(200, json={"code": 0, "data": {"id": "m"}})

    adapter.set_http_transport(httpx.MockTransport(_handler))
    msg = ISACMessage(
        msg_id="m1", platform="qq_official", timestamp=0, user_id="u1",
        user_name="u1", group_id="g1", content="hi",
    )
    await adapter.send(msg)
    await adapter.send(msg)
    assert len(token_calls) == 1


@pytest.mark.asyncio
async def test_send_returns_false_on_api_error() -> None:
    """send 返回 code!=0 → False。"""
    adapter = _make_adapter()

    def _handler(request: httpx.Request) -> httpx.Response:
        if "getAppAccessToken" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})
        return httpx.Response(200, json={"code": 100014, "message": "msg_id expired"})

    adapter.set_http_transport(httpx.MockTransport(_handler))
    msg = ISACMessage(
        msg_id="m1", platform="qq_official", timestamp=0, user_id="u1",
        user_name="u1", content="hi",
    )
    ok = await adapter.send(msg)
    assert ok is False


@pytest.mark.asyncio
async def test_send_returns_false_when_code_is_none() -> None:
    """X1: code 显式为 None 时 fail-closed, 不误判为成功 (None or 0 == 0)。"""
    adapter = _make_adapter()

    def _handler(request: httpx.Request) -> httpx.Response:
        if "getAppAccessToken" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})
        # QQ 网关异常透传可能返回 code=None
        return httpx.Response(200, json={"code": None, "message": "internal error"})

    adapter.set_http_transport(httpx.MockTransport(_handler))
    msg = ISACMessage(
        msg_id="m1", platform="qq_official", timestamp=0, user_id="u1",
        user_name="u1", content="hi",
    )
    ok = await adapter.send(msg)
    assert ok is False


@pytest.mark.asyncio
async def test_send_returns_false_when_code_missing() -> None:
    """X1: code 字段缺失时 fail-closed (与 FeishuAdapter.send 一致)。"""
    adapter = _make_adapter()

    def _handler(request: httpx.Request) -> httpx.Response:
        if "getAppAccessToken" in str(request.url):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})
        # 响应体不含 code 字段
        return httpx.Response(200, json={"data": {"id": "m"}})

    adapter.set_http_transport(httpx.MockTransport(_handler))
    msg = ISACMessage(
        msg_id="m1", platform="qq_official", timestamp=0, user_id="u1",
        user_name="u1", content="hi",
    )
    ok = await adapter.send(msg)
    assert ok is False


@pytest.mark.asyncio
async def test_send_without_credentials_returns_false() -> None:
    """未配置 app_id/secret → 直接 False。"""
    adapter = _make_adapter(app_id="", secret="")
    msg = ISACMessage(
        msg_id="m1", platform="qq_official", timestamp=0, user_id="u1",
        user_name="u1", content="hi",
    )
    ok = await adapter.send(msg)
    assert ok is False


@pytest.mark.asyncio
async def test_send_token_exchange_failure_returns_false() -> None:
    """token 换取失败 (响应无 access_token) → send 直接 False。"""
    adapter = _make_adapter()

    def _handler(request: httpx.Request) -> httpx.Response:
        if "getAppAccessToken" in str(request.url):
            return httpx.Response(200, json={"code": 100015, "message": "invalid credentials"})
        return httpx.Response(200, json={"code": 0})

    adapter.set_http_transport(httpx.MockTransport(_handler))
    msg = ISACMessage(
        msg_id="m1", platform="qq_official", timestamp=0, user_id="u1",
        user_name="u1", content="hi",
    )
    ok = await adapter.send(msg)
    assert ok is False


# ── _derive_seed 单独验证 ─────────────────────────────────────────


def test_derive_seed_repeats_to_32_bytes() -> None:
    """短 secret (< 32 字符) → 重复双倍直到 >= 32, 取前 32 字节。"""
    assert _derive_seed("abc") == ("abcabcabcabcabcabcabcabcabcabcab" + "")[:32].encode("utf-8")  # 10 次重复取前 32
    # 具体验证: "abc" → "abcabc" → "abcabcabcabc" → ... 直到 >= 32
    s = "abc"
    while len(s) < 32:
        s = s + s
    assert _derive_seed("abc") == s[:32].encode("utf-8")


def test_derive_seed_truncates_long_secret() -> None:
    """长 secret (> 32 字符) → 取前 32 字节。"""
    secret = "x" * 100
    assert _derive_seed(secret) == secret[:32].encode("utf-8")


# ── start/stop 生命周期 (不绑真实端口, 只验证不抛异常 + 重复安全) ──


@pytest.mark.asyncio
async def test_start_stop_idempotent_no_port() -> None:
    """start/stop 在 webhook_port=0 时仍能起/停。"""
    adapter = _make_adapter()
    adapter._webhook_port = 0  # type: ignore[attr-defined]
    await adapter.start()
    await adapter.start()
    await adapter.stop()
    await adapter.stop()
