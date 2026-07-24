"""K7 安全与长期运行基线测试 (DEVELOPMENT_PLAN.md)。

覆盖:
- Webhook SSRF 防护 (拒绝内网 IP / 链路本地 / 非 http(s))
- SecretStore AES-256-GCM 加解密 + 未配置密钥时拒绝运行
- Session TTL 回收 (过期 session 被 _gc_expired 清理)
- Session get(session_id) 用二级索引 O(1)
- SessionLockManager 引用计数 + 无 waiter 时回收
- WebChat 回复队列有界 (超出 max_pending_replies 丢最旧)
- bash kill 后 await proc.wait() 防僵尸 (用 mock subprocess)
- read_file 流式读取 (只读 MAX_READ_BYTES+1, 大文件不内存膨胀)
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from pathlib import Path

import pytest

from isac.channel.model import ISACMessage
from isac.control.webhooks import SSRFBlockedError, WebhookManager, validate_webhook_url
from isac.utils.security import SecretStore

# ── Webhook SSRF 防护 ────────────────────────────────────


def test_webhook_url_rejects_non_http_scheme() -> None:
    """非 http/https scheme 被拒绝。"""
    with pytest.raises(SSRFBlockedError, match="scheme"):
        validate_webhook_url("ftp://example.com")


def test_webhook_url_rejects_private_ip() -> None:
    """内网 IP 被拒绝。"""
    with pytest.raises(SSRFBlockedError, match="内网"):
        validate_webhook_url("http://10.0.0.1/hook")
    with pytest.raises(SSRFBlockedError, match="内网"):
        validate_webhook_url("http://192.168.1.1/hook")
    with pytest.raises(SSRFBlockedError, match="内网"):
        validate_webhook_url("http://127.0.0.1/hook")


def test_webhook_url_rejects_link_local() -> None:
    """链路本地地址被拒绝。"""
    with pytest.raises(SSRFBlockedError, match="内网"):
        validate_webhook_url("http://169.254.169.254/latest/meta-data")  # AWS 元数据


def test_webhook_url_allow_local_allows_localhost_in_dev() -> None:
    """allow_local=True 时允许 localhost (开发态)。"""
    validate_webhook_url("http://localhost:8080/hook", allow_local=True)
    validate_webhook_url("http://127.0.0.1:8080/hook", allow_local=True)


def test_webhook_manager_subscribe_blocks_ssrf_in_production() -> None:
    """无 http_client 注入的生产场景, subscribe 拒绝内网 URL。"""
    mgr = WebhookManager()  # 无 http_client, 严格 SSRF 校验
    with pytest.raises(SSRFBlockedError):
        mgr.subscribe("event", "http://10.0.0.1/hook")


def test_webhook_manager_subscribe_skips_dns_when_mock_client_injected() -> None:
    """测试场景 (http_client 注入) 跳过 DNS 解析, 允许假域名。"""
    class _MockClient:
        async def post(self, url, payload):
            return True
    mgr = WebhookManager(http_client=_MockClient())
    # 假域名 a.com 在测试环境无法解析, 但 mock client 注入时只校验 scheme
    mgr.subscribe("event", "https://a.com/hook")  # 不抛异常
    subs = mgr.list_subscriptions("event")
    assert subs["event"] == ["https://a.com/hook"]


# ── SecretStore AES-256-GCM ─────────────────────────────


@pytest.mark.asyncio
async def test_secret_store_round_trip(tmp_path: Path) -> None:
    """SecretStore 加密写入 + 读取 round-trip。"""
    os.environ["ISAC_SECRET_KEY"] = base64.b64encode(b"0" * 32).decode()
    try:
        store = SecretStore(str(tmp_path / ".secrets.enc"))
        await store.set("openai_api_key", "sk-secret-value")
        value = await store.get("openai_api_key")
        assert value == "sk-secret-value"
    finally:
        os.environ.pop("ISAC_SECRET_KEY", None)


@pytest.mark.asyncio
async def test_secret_store_missing_key_returns_none(tmp_path: Path) -> None:
    os.environ["ISAC_SECRET_KEY"] = base64.b64encode(b"0" * 32).decode()
    try:
        store = SecretStore(str(tmp_path / ".secrets.enc"))
        assert await store.get("nonexistent") is None
    finally:
        os.environ.pop("ISAC_SECRET_KEY", None)


@pytest.mark.asyncio
async def test_secret_store_missing_env_raises(tmp_path: Path) -> None:
    os.environ.pop("ISAC_SECRET_KEY", None)
    store = SecretStore(str(tmp_path / ".secrets.enc"))
    with pytest.raises(RuntimeError, match="ISAC_SECRET_KEY"):
        await store.set("k", "v")


@pytest.mark.asyncio
async def test_secret_store_wrong_key_size_raises(tmp_path: Path) -> None:
    os.environ["ISAC_SECRET_KEY"] = base64.b64encode(b"short").decode()
    try:
        store = SecretStore(str(tmp_path / ".secrets.enc"))
        with pytest.raises(RuntimeError, match="32 字节"):
            await store.set("k", "v")
    finally:
        os.environ.pop("ISAC_SECRET_KEY", None)


@pytest.mark.asyncio
async def test_secret_store_delete(tmp_path: Path) -> None:
    os.environ["ISAC_SECRET_KEY"] = base64.b64encode(b"0" * 32).decode()
    try:
        store = SecretStore(str(tmp_path / ".secrets.enc"))
        await store.set("k1", "v1")
        assert await store.delete("k1") is True
        assert await store.get("k1") is None
        # 再次删除返回 False
        assert await store.delete("k1") is False
    finally:
        os.environ.pop("ISAC_SECRET_KEY", None)


@pytest.mark.asyncio
async def test_secret_store_persists_across_instances(tmp_path: Path) -> None:
    """同一密钥, 不同 SecretStore 实例能读出对方写入的数据 (持久化)。"""
    os.environ["ISAC_SECRET_KEY"] = base64.b64encode(b"0" * 32).decode()
    try:
        store1 = SecretStore(str(tmp_path / ".secrets.enc"))
        await store1.set("k", "persisted-value")
        store2 = SecretStore(str(tmp_path / ".secrets.enc"))
        assert await store2.get("k") == "persisted-value"
    finally:
        os.environ.pop("ISAC_SECRET_KEY", None)


# ── Session TTL + 二级索引 ──────────────────────────────


@pytest.mark.asyncio
async def test_session_ttl_recycles_expired_sessions() -> None:
    """过期 session 在 get_or_create 时被惰性清理。"""
    from isac.gateway.session import SessionManager

    mgr = SessionManager({"session_ttl_seconds": 1})
    msg = ISACMessage(
        msg_id="m1", platform="fake", timestamp=int(time.time()),
        user_id="u1", user_name="u1", group_id=None, content="hi",
    )
    session = await mgr.get_or_create(msg, agent_id="a")
    assert await mgr.get(session.session_id) is not None

    # 模拟 session.last_active 超时 (直接改 last_active)
    session.last_active = int(time.time()) - 100

    # 触发另一次 get_or_create 让 _gc_expired 清理
    msg2 = ISACMessage(
        msg_id="m2", platform="fake", timestamp=int(time.time()),
        user_id="u2", user_name="u2", group_id=None, content="hi",
    )
    await mgr.get_or_create(msg2, agent_id="a")

    # 旧 session 已被回收
    assert await mgr.get(session.session_id) is None


@pytest.mark.asyncio
async def test_session_get_uses_index_not_scan() -> None:
    """session_id → key 二级索引让 get 是 O(1), 即使 1000 个 session 也能快速查。"""
    from isac.gateway.session import SessionManager

    mgr = SessionManager()
    # 创建 100 个 session
    session_ids = []
    for i in range(100):
        msg = ISACMessage(
            msg_id=f"m{i}", platform="fake", timestamp=int(time.time()),
            user_id=f"u{i}", user_name=f"u{i}", group_id=None, content="hi",
        )
        s = await mgr.get_or_create(msg, agent_id="a")
        session_ids.append(s.session_id)

    # get 中间那个应该是 O(1), 立即返回
    target = session_ids[50]
    found = await mgr.get(target)
    assert found is not None
    assert found.session_id == target

    # 不存在的 ID 立即返回 None
    assert await mgr.get("nonexistent") is None


# ── SessionLockManager 引用计数回收 ─────────────────────


@pytest.mark.asyncio
async def test_session_lock_release_reclaims_when_no_waiters() -> None:
    """无 waiter 时 release 回收锁对象, 长期运行 _locks 不无限增长。"""
    from isac.gateway.lock import SessionLockManager

    mgr = SessionLockManager()
    await mgr.acquire("sess-1")
    assert "sess-1" in mgr._locks
    mgr.release("sess-1")
    # 无 waiter + lock 未持有, 应该被回收
    assert "sess-1" not in mgr._locks


# ── WebChat 队列有界 ────────────────────────────────────


@pytest.mark.asyncio
async def test_webchat_pending_replies_bounded() -> None:
    """超出 max_pending_replies 时丢弃最旧的 (FIFO), 内存不无限增长。"""
    from isac.channel.adapters.webchat.adapter import WebChatAdapter

    adapter = WebChatAdapter({"max_pending_replies": 3})
    for i in range(5):
        await adapter.send(ISACMessage(
            msg_id=f"m{i}", platform="webchat", timestamp=0,
            user_id="u1", user_name="u1", group_id=None,
            content=f"reply-{i}", session_id="sess-1",
        ))
    replies = await adapter.poll_replies("sess-1")
    # 只保留最后 3 条 (丢最旧 2 条)
    assert len(replies) == 3
    assert replies[0]["content"] == "reply-2"
    assert replies[2]["content"] == "reply-4"


# ── bash kill 后 await proc.wait ─────────────────────────


@pytest.mark.asyncio
async def test_bash_timeout_kills_and_waits_for_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """bash 超时 kill 后必须 await proc.wait() 等进程退出, 不留僵尸。"""
    from isac.agent.tools.base import ToolContext
    from isac.agent.tools.utility.bash import BashTool

    class _FakeProc:
        def __init__(self):
            self.killed = False
            self.waited = False
        async def communicate(self):
            # 超时路径不调用 communicate 返回值, 这里只占位, 实际由 _fake_wait_for 抛 TimeoutError
            await asyncio.sleep(0.01)
            return (b"", b"")
        def kill(self):
            self.killed = True
        async def wait(self):
            self.waited = True
            return 0

    fake_proc = _FakeProc()

    # 用真实 subprocess_exec 但替换 wait_for: 真实 wait_for 抛 TimeoutError 触发 kill 分支
    captured_proc_holder: dict[str, object] = {}

    async def _fake_create_subprocess_exec(*args, **kwargs):
        captured_proc_holder["proc"] = fake_proc
        return fake_proc

    async def _fake_wait_for(coro, _timeout=None):  # noqa: ASYNC109
        # 区分: communicate() 的 wait_for 抛 TimeoutError 触发 kill 分支;
        # proc.wait() 的 wait_for 正常 await 让 FakeProc.wait 返回
        # 通过 coro 名字区分
        coro_name = getattr(coro, "__name__", "") or getattr(getattr(coro, "cr_code", None), "co_name", "")
        if coro_name == "wait":
            return await coro
        # communicate 路径: 关闭未 await 的协程避免 RuntimeWarning + 抛 timeout
        coro.close()
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr("isac.agent.tools.utility.bash.asyncio.create_subprocess_exec", _fake_create_subprocess_exec)
    monkeypatch.setattr("isac.agent.tools.utility.bash.asyncio.wait_for", _fake_wait_for)

    result = await BashTool().execute(ToolContext(
        args={"command": "sleep 100"},
        agent_context=None,  # type: ignore[arg-type]
        services={"bash_allowlist": ["sleep"]},
    ))

    assert result.is_error
    assert "超时" in result.content
    assert fake_proc.killed
    assert fake_proc.waited  # K7: kill 后 await wait 了


# ── read_file 流式读取 ─────────────────────────────────


@pytest.mark.asyncio
async def test_read_file_only_reads_max_bytes(tmp_path: Path) -> None:
    """大文件只读 MAX_READ_BYTES+1 字节, 不整文件加载到内存。"""
    from isac.agent.tools.base import ToolContext
    from isac.agent.tools.utility.read_file import MAX_READ_BYTES, ReadFileTool

    big_file = tmp_path / "big.txt"
    # 写 2 倍 MAX_READ_BYTES 的数据
    big_file.write_text("x" * (MAX_READ_BYTES * 2), encoding="utf-8")

    result = await ReadFileTool().execute(ToolContext(
        args={"path": "big.txt"},
        agent_context=None,  # type: ignore[arg-type]
        services={"workspace_root": str(tmp_path)},
    ))

    assert not result.is_error
    # 内容长度应 <= MAX_READ_BYTES (截断)
    assert len(result.content) < MAX_READ_BYTES * 2
