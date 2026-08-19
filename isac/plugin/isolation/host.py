"""PluginIsolationHost: 插件进程隔离宿主 (O2, PLUGIN_COMPATIBILITY.md)。

O2 实现: 用 multiprocessing.Process spawn 子进程, socketpair 上长度前缀 JSON
字节帧 IPC (Fix-89: 此前用 multiprocessing.Pipe —— recv() 是 pickle 反序列化,
承载不可信插件代码的隔离子进程可构造恶意 pickle 载荷在宿主 recv 时执行任意代码,
沙箱逃逸; 现传输层只读字节 + json.loads, 解码路径零代码执行); spawn 时设资源
限额 (resource.setrlimit CPU/NOFILE/AS, POSIX only); call 编码 IPCEnvelope →
JSON 帧 → 发送 → 等待 result/error → 解码; 子进程崩溃自动重启 (最多
max_restart_attempts 次, 默认 3)。默认不接管现有 in-process loader (loader.py
不变), enabled=False 时主链路零行为变化。

CR3-H2: 子进程 worker 不再是纯 echo 桩 —— kind="load" 让隔离子进程用
PluginLoader 真实加载插件入口 (顶层代码在子进程内执行, 不污染宿主),
kind="call" + payload.method 调用已加载插件的方法 (async 方法用 asyncio.run);
payload.text/echo 的 echo 语义保留 (连通性探测 + 向后兼容)。
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import socket
import sys
from typing import Any

from isac.plugin.isolation.protocol import IPCEnvelope
from isac.utils.logger import get_logger

# CR3-H2: resource 是 POSIX-only 模块, Windows 上顶层 import 直接 ImportError
# (曾导致本模块在 Windows 上完全不可导入, 连测试都无法收集)。平台守卫后
# Windows 跳过资源限额 (multiprocessing spawn 子进程会重新 import 本模块,
# 守卫对宿主与子进程双向生效)。sys.platform 判定让 mypy 按平台窄化类型。
if sys.platform == "win32":  # pragma: no cover - Windows 无 resource 模块
    resource = None
else:
    import resource

logger = get_logger(__name__)

# 默认重启次数上限; 超过后放弃 (is_alive=False)
DEFAULT_MAX_RESTART_ATTEMPTS = 3
# Fix-77: IPC 响应等待超时 (秒)。子进程挂死 (插件代码死锁/死循环且不退出) 时
# 无超时的 recv 永久阻塞, 且 call 经 _lock 串行化 → 该插件的后续所有调用全部
# 排队挂死。超时按崩溃处理 (terminate + respawn)。
DEFAULT_IPC_TIMEOUT_SECONDS = 30.0

# 可 JSON 序列化的原生类型 (worker 方法返回值超出此集合时降级为 str)
_JSON_SAFE_TYPES = (str, int, float, bool, type(None), list, dict)

# Fix-89: IPC 单帧上限。长度前缀来自对端 (隔离子进程跑不可信插件代码),
# 恶意声明超大长度会让读取侧按长度预分配/阻塞 → 读前强制上限, 超限视为
# 协议违规 (宿主按崩溃重启处理)。插件载荷是 JSON 结果/错误文本, 16MB 足够。
_MAX_FRAME_BYTES = 16 * 1024 * 1024


class _JsonFrameTransport:
    """Fix-89: 长度前缀 JSON 字节帧传输 (替代 pickle 语义的 multiprocessing.Pipe)。

    威胁模型: 隔离子进程承载不可信插件代码, 对管道另一端写入的内容完全可控。
    multiprocessing.Connection.recv() 是 pickle 反序列化 —— 恶意插件直接写构造
    好的 pickle 字节流 (如带 __reduce__ 的对象), 宿主 recv 时即执行任意代码,
    应用层的 JSON 协议在 pickle 之后才生效, 不构成防护 (已实测复现)。
    本传输层只读裸字节: 4 字节大端长度 + UTF-8 JSON, 解码仅 json.loads,
    路径上无任何代码执行点。send(dict)/recv()->dict 的接口形状与旧 Pipe 用法
    对齐 (序列化职责移入传输层), 宿主/worker 两侧共用。
    """

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        # 缓冲读: recv 在 to_thread 内阻塞等待, makefile 提供 read(n) 精确读语义
        self._reader = sock.makefile("rb")

    def send(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        if len(payload) > _MAX_FRAME_BYTES:
            raise ValueError(f"IPC 帧超限 ({len(payload)} > {_MAX_FRAME_BYTES})")
        self._sock.sendall(len(payload).to_bytes(4, "big") + payload)

    def recv(self) -> dict[str, Any]:
        header = self._reader.read(4)
        if len(header) < 4:
            raise EOFError("IPC 连接已关闭")
        length = int.from_bytes(header, "big")
        if length > _MAX_FRAME_BYTES:
            # 对端声明非法长度 (恶意/损坏): 不能按其读取, 视为协议违规
            raise ValueError(f"IPC 帧长度异常: {length}")
        body = self._reader.read(length)
        if len(body) < length:
            raise EOFError("IPC 连接意外中断")
        return json.loads(body.decode("utf-8"))  # type: ignore[no-any-return]

    def close(self) -> None:
        try:
            self._reader.close()
        finally:
            try:
                self._sock.close()
            except OSError:
                pass


# 默认资源限额 (POSIX; 可经 PluginIsolationHost(rlimits=...) 覆盖)
_DEFAULT_RLIMITS: dict[str, tuple[int, int]] = {
    # 2026-08-19 (M11): cpu 默认 (1,1)=累计 1 秒 CPU 即 SIGXCPU, 任何做实事的隔离
    # 插件都会被杀 (sample 配置建议 60,60 但代码默认未改)。对齐 sample 提到 60,60。
    "cpu": (60, 60),
    "nofile": (64, 64),
    "as": (256 * 1024 * 1024, 256 * 1024 * 1024),
}


def _apply_rlimits(rlimits: dict[str, tuple[int, int]] | None = None) -> None:
    """子进程资源限额 (POSIX; Windows 跳过)。限额的是 CPU/NOFILE/AS (非 RSS)。

    N5b 批次C C3: rlimits 可配 (此前 RLIMIT_CPU (1,1) 硬编码, 长任务插件直接
    SIGXCPU 被杀且不可调)。

    M11: 设置失败此前 ``except: pass`` 静默 —— 限额没生效时隔离"看起来生效",
    是最危险的状态; 现失败记 warning (不 raise, 避免平台差异阻断插件加载, 但
    不再无声)。
    """
    if resource is None:
        return
    cfg = rlimits or _DEFAULT_RLIMITS
    try:
        if hasattr(resource, "RLIMIT_CPU"):
            resource.setrlimit(resource.RLIMIT_CPU, cfg.get("cpu", _DEFAULT_RLIMITS["cpu"]))
        if hasattr(resource, "RLIMIT_NOFILE"):
            resource.setrlimit(resource.RLIMIT_NOFILE, cfg.get("nofile", _DEFAULT_RLIMITS["nofile"]))
        if hasattr(resource, "RLIMIT_AS"):
            resource.setrlimit(resource.RLIMIT_AS, cfg.get("as", _DEFAULT_RLIMITS["as"]))
    except (ValueError, OSError, PermissionError) as exc:
        # M11: 权限不足/平台不支持时不 raise (避免阻断), 但必须留痕 —— 静默失效
        # 会让隔离看起来生效而实际未限额。
        logger.warning("子进程 rlimits 设置失败 (隔离限额未生效)", error=str(exc))


def _worker_load(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """在子进程内真实加载插件 (CR3-H2): 插件顶层代码只在这里执行, 不进宿主。"""
    from pathlib import Path

    from isac.plugin.runtime.loader import PluginLoader

    plugin_path = str(payload.get("path", "") or "")
    if not plugin_path:
        raise ValueError("load 缺少 payload.path")
    loaded = asyncio.run(PluginLoader().load(Path(plugin_path)))
    state["plugin"] = loaded.instance
    state["plugin_name"] = loaded.name
    return {"loaded": loaded.name, "format": loaded.format.value}


def _worker_call(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """处理 call: echo 探测 (payload.text/echo) 或已加载插件的方法调用。"""
    if "text" in payload or "echo" in payload:
        # echo 桩语义保留: 连通性探测 + 既有调用方/测试兼容
        return {"echo": payload.get("text", "") or payload.get("echo", "")}
    method_name = str(payload.get("method", "") or "")
    if not method_name:
        raise ValueError("call 缺少 payload.method (或 payload.text 做 echo 探测)")
    plugin = state.get("plugin")
    if plugin is None:
        raise RuntimeError("插件尚未加载, 先发送 kind=load")
    if method_name.startswith("_"):
        raise PermissionError(f"拒绝调用私有方法: {method_name}")
    method = getattr(plugin, method_name, None)
    if method is None or not callable(method):
        raise AttributeError(f"插件 {state.get('plugin_name')} 无可调用方法: {method_name}")
    kwargs = payload.get("args", {}) or {}
    result = method(**kwargs)
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    if not isinstance(result, _JSON_SAFE_TYPES):
        result = str(result)
    return {"result": result}


def _plugin_worker(
    plugin_id: str, sock: socket.socket, rlimits: dict[str, tuple[int, int]] | None = None
) -> None:
    """子进程入口: 循环处理 load/call 请求 (CR3-H2: 真实加载插件, echo 兼容)。

    读 JSON 帧一条 → 处理 → 写回 JSON 帧一条 (Fix-89: 经 _JsonFrameTransport
    字节帧, 不再经 pickle)。业务异常回 kind=error 不崩溃; 连接断开 (EOFError)
    退出。资源限额见 _apply_rlimits (POSIX only, C3 可配)。
    """
    _apply_rlimits(rlimits)
    transport = _JsonFrameTransport(sock)
    state: dict[str, Any] = {}
    while True:
        correlation_id = ""
        try:
            env = transport.recv()
            if env is None:
                break
            correlation_id = str(env.get("correlation_id", "") or "")
            kind = str(env.get("kind", "call") or "call")
            payload = env.get("payload", {}) or {}
            try:
                if kind == "load":
                    result_payload = _worker_load(state, payload)
                else:
                    result_payload = _worker_call(state, payload)
                response = {
                    "kind": "result",
                    "plugin_id": plugin_id,
                    "payload": result_payload,
                    "correlation_id": correlation_id,
                }
            except Exception as exc:  # noqa: BLE001 业务异常回 error, 不让 worker 崩溃
                response = {
                    "kind": "error",
                    "plugin_id": plugin_id,
                    "payload": {"error": str(exc)},
                    "correlation_id": correlation_id,
                }
            transport.send(response)
        except EOFError:
            break
        except Exception as exc:  # noqa: BLE001 协议层异常: 尽力回 error, 失败则退出
            try:
                transport.send(
                    {
                        "kind": "error",
                        "plugin_id": plugin_id,
                        "payload": {"error": str(exc)},
                        "correlation_id": correlation_id,
                    }
                )
            except Exception:  # noqa: BLE001
                break


class PluginIsolationHost:
    """隔离插件宿主 (每个隔离插件一个子进程)。"""

    def __init__(
        self,
        plugin_id: str,
        *,
        max_restart_attempts: int = DEFAULT_MAX_RESTART_ATTEMPTS,
        rlimits: dict[str, tuple[int, int]] | None = None,
        ipc_timeout: float = DEFAULT_IPC_TIMEOUT_SECONDS,
    ) -> None:
        self.plugin_id = plugin_id
        self.max_restart_attempts = max(0, int(max_restart_attempts))
        # Fix-77: IPC 响应等待超时 (见 DEFAULT_IPC_TIMEOUT_SECONDS 注释)
        self._ipc_timeout = max(0.1, float(ipc_timeout))
        # N5b 批次C C3: 资源限额可配 (透传给子进程 _apply_rlimits), 默认 None 用内置默认。
        self._rlimits = rlimits
        # N5b 批次C C3: 缓存 plugin_path, 崩溃 respawn 后据此重新 load_plugin。
        self._plugin_path: str | None = None
        self._alive = False
        self._process: mp.process.BaseProcess | None = None
        self._parent_conn: Any = None
        self._child_conn: Any = None
        self._restart_count = 0
        self._correlation_counter = 0
        self._ctx: Any = None
        # N5b 批次C C4: call 串行化锁 —— 并发 call 共享同一 _parent_conn, 无锁则
        # send/recv 竞争致响应错配 (correlation_id 不匹配)。asyncio.Lock 串行化 IPC。
        self._lock: Any = None  # 延迟创建 (需事件循环)
        # N5b 批次C C3: 崩溃 respawn 后 worker state 已重置, 需重新 load_plugin;
        # 标记位让下次 call 在拿锁前重载 (避免在持锁的 call 内重入 load_plugin→call 死锁)。
        self._needs_reload: bool = False

    async def spawn(self) -> None:
        """启动隔离子进程 (multiprocessing.Process + socketpair 字节帧 IPC + 资源限额).

        Fix-89: 传输从 multiprocessing.Pipe (pickle) 换成 socketpair +
        _JsonFrameTransport (长度前缀 JSON 字节帧) —— Pipe.recv 的 pickle
        反序列化是沙箱逃逸点 (子进程可控字节流 → 宿主 RCE)。socket 对象经
        multiprocessing.reduction 的 fd 传递机制作为 Process 参数送入子进程。
        """
        if self._alive and self._process is not None and self._process.is_alive():
            return
        # CR2-Fix-20: 此前用 fork (POSIX) 减少 spawn 开销; fork 会让子进程继承
        # 父进程 fork 时刻的完整内存 (包括已解密密钥/已建立的连接对象等), 隔离
        # 插件子进程本应尽量减少与父进程共享状态。改用 spawn: 子进程从头启动
        # Python 解释器, 只继承 target/args 显式传入的内容; 要求目标函数可被
        # pickle, _plugin_worker 是模块级函数, 满足要求。
        self._ctx = mp.get_context("spawn")
        parent_sock, child_sock = socket.socketpair()
        self._parent_conn = _JsonFrameTransport(parent_sock)
        self._child_conn = child_sock  # 仅用于 start 后关闭父侧副本 (C5 同构)
        self._process = self._ctx.Process(
            target=_plugin_worker,
            args=(self.plugin_id, child_sock, self._rlimits),
            daemon=True,
        )
        self._process.start()
        self._alive = True
        # N5b 批次C C5: 父侧 close child 端 (子进程经 fd 传递持自己的副本; 父持有
        # child 端 FD 会导致子退出时父端不释放 EOF 不传播, respawn/kill 泄漏 FD)。
        try:
            child_sock.close()
        except Exception:  # noqa: BLE001
            pass
        logger.info(
            "插件子进程已启动",
            plugin_id=self.plugin_id,
            pid=self._process.pid,
        )

    async def kill(self) -> None:
        """终止隔离子进程并回收资源 (幂等)。

        CR2-Fix-20: Process.join() 是阻塞调用, 此前直接同步调用会阻塞整个
        event loop (最坏情况 terminate 2s + kill 1s = 3s); 包 asyncio.to_thread
        让阻塞发生在线程池而非事件循环线程上。
        """
        if self._process is not None:
            if self._process.is_alive():
                self._process.terminate()
                await asyncio.to_thread(self._process.join, 2.0)
                if self._process.is_alive():
                    self._process.kill()
                    await asyncio.to_thread(self._process.join, 1.0)
            self._process.close()
            self._process = None
        if self._parent_conn is not None:
            try:
                self._parent_conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._parent_conn = None
        # N5b 批次C C5: 父侧 close _child_conn (此前只关 _parent_conn, _child_conn 永不
        # close → 每次 respawn/kill 泄漏一个 FD; 子进程已 dup 自己的端, 父侧关闭安全)。
        if self._child_conn is not None:
            try:
                self._child_conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._child_conn = None
        self._alive = False
        logger.debug("插件子进程已终止", plugin_id=self.plugin_id)

    @property
    def plugin_path(self) -> str | None:
        """Fix-135: 隔离插件的真实目录路径 (load_plugin 时缓存)。

        供 PluginManager.reload/uninstall 在 manifest.name≠目录名时定位真实目录
        (隔离插件不在 _loaded, 此前只能按 plugins_dir/name 回退 → 定位错目录)。
        """
        return self._plugin_path

    async def load_plugin(self, plugin_path: str) -> IPCEnvelope:
        """让隔离子进程真实加载插件目录 (CR3-H2)。

        插件入口文件的顶层代码在子进程内执行 —— 恶意/异常插件影响的是资源受限
        的 worker 进程, 不是宿主。返回 kind=result (payload.loaded=插件名) 或
        kind=error (payload.error=失败原因)。

        N5b 批次C C3: 缓存 plugin_path, 子进程崩溃 respawn 后据此重新 load_plugin
        (此前 _on_crash 只 spawn 空 worker 不重新加载, 崩溃恢复名存实亡)。
        """
        self._plugin_path = str(plugin_path)
        return await self.call(
            IPCEnvelope(kind="load", plugin_id=self.plugin_id, payload={"path": str(plugin_path)})
        )

    async def call(self, envelope: IPCEnvelope) -> IPCEnvelope:
        """向隔离插件发起一次 IPC 调用并等待结果。

        编码 envelope → JSON → 管道发送 → 等待 result/error → 解码。
        子进程崩溃时自动重启 (最多 max_restart_attempts 次)。

        N5b 批次C C4: async with _lock 串行化 send+recv (此前并发 call 共享同一
        _parent_conn 无锁, 响应错配); _ipc_roundtrip 校验响应 correlation_id 匹配
        (此前 FIFO recv, 残留/乱序响应会拿到别人的结果)。C3: 崩溃 respawn 后下次
        call 开头重载 plugin (worker state 已重置)。
        """
        if not self._alive or self._parent_conn is None:
            raise RuntimeError(f"插件 {self.plugin_id} 未 spawn, 无法调用")
        # C3: 崩溃 respawn 后 worker state 已重置, 需重新 load_plugin (若有缓存路径);
        # 在拿锁前重载, 避免在持锁的 call 内重入 load_plugin→call 死锁。
        if self._needs_reload and self._plugin_path:
            self._needs_reload = False
            await self.load_plugin(self._plugin_path)
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            self._correlation_counter += 1
            envelope.correlation_id = f"corr-{self._correlation_counter}"
            data = await self._ipc_roundtrip(envelope)
        return IPCEnvelope(
            kind=data.get("kind", "result"),
            plugin_id=data.get("plugin_id", self.plugin_id),
            payload=data.get("payload", {}),
            correlation_id=data.get("correlation_id", ""),
        )

    async def _ipc_roundtrip(self, envelope: IPCEnvelope) -> dict[str, Any]:
        """C4: 串行化发送 + 接收 + 校验 correlation_id (须在 _lock 内调用)。"""
        try:
            self._parent_conn.send({
                "kind": envelope.kind,
                "plugin_id": envelope.plugin_id,
                "payload": envelope.payload,
                "correlation_id": envelope.correlation_id,
            })
        except (BrokenPipeError, OSError) as exc:
            # 管道断 = 子进程崩溃, 触发重启
            logger.warning("IPC 管道断, 触发重启", plugin_id=self.plugin_id, error=str(exc))
            await self._on_crash()
            raise RuntimeError(f"插件 {self.plugin_id} 子进程崩溃, 已触发重启") from exc
        # 等待响应 (同步 recv, 包在 to_thread 避免阻塞 event loop)
        try:
            # Fix-77: 加超时 —— 子进程挂死 (插件死锁/死循环且不退出) 时 recv
            # 永久阻塞, 且 _lock 串行化让该插件后续所有 call 排队挂死。超时按
            # 崩溃处理: _on_crash 杀挂死进程 (连接随之关闭, 被阻塞的 recv 线程
            # 收到 EOF/OSError 自行退出 —— to_thread 任务无法取消, 但线程会随
            # 连接关闭而终结) + respawn 新子进程。
            data = await asyncio.wait_for(
                asyncio.to_thread(self._parent_conn.recv), timeout=self._ipc_timeout
            )
        except TimeoutError as exc:
            logger.warning(
                "IPC 响应超时, 视为子进程挂死, 触发重启",
                plugin_id=self.plugin_id, timeout=self._ipc_timeout,
            )
            await self._on_crash()
            raise RuntimeError(
                f"插件 {self.plugin_id} IPC 响应超时 ({self._ipc_timeout}s), 子进程已重启"
            ) from exc
        except EOFError as exc:
            await self._on_crash()
            raise RuntimeError(f"插件 {self.plugin_id} 子进程已退出") from exc
        except (ValueError, OSError) as exc:
            # Fix-89: 帧长度异常/JSON 解析失败/连接重置 —— 对端是不可信插件
            # 代码, 协议违规一律按崩溃重启, 不消费其内容。
            logger.warning("IPC 协议违规, 触发重启", plugin_id=self.plugin_id, error=str(exc))
            await self._on_crash()
            raise RuntimeError(f"插件 {self.plugin_id} IPC 协议违规, 子进程已重启") from exc
        # C4: 校验响应 correlation_id 匹配 (不匹配说明残留/并发错配, 视为崩溃重置)
        resp_corr = str(data.get("correlation_id", "") or "")
        if resp_corr and resp_corr != envelope.correlation_id:
            logger.warning(
                "IPC 响应 correlation_id 不匹配", plugin_id=self.plugin_id,
                expected=envelope.correlation_id, got=resp_corr,
            )
            await self._on_crash()
            raise RuntimeError(f"插件 {self.plugin_id} IPC 响应错配 (correlation_id 不匹配)")
        return data

    def _close_conns(self) -> None:
        """关闭父侧 pipe 两端 (幂等; 防 _child_conn FD 泄漏)。"""
        for _attr in ("_parent_conn", "_child_conn"):
            _conn = getattr(self, _attr, None)
            if _conn is not None:
                try:
                    _conn.close()
                except Exception:  # noqa: BLE001
                    pass
                setattr(self, _attr, None)

    async def _on_crash(self) -> None:
        """子进程崩溃时调: 计数 + 重启 (未超 max_restart_attempts)。

        CR2-Fix-20: Process.join() 是阻塞调用, 包 asyncio.to_thread 避免阻塞
        event loop (与 kill() 同款修复; call() 调用点相应改为 await)。
        """
        self._alive = False
        if self._restart_count >= self.max_restart_attempts:
            logger.warning(
                "插件子进程崩溃次数超上限, 放弃重启",
                plugin_id=self.plugin_id,
                restart_count=self._restart_count,
                max_attempts=self.max_restart_attempts,
            )
            return
        self._restart_count += 1
        logger.info(
            "插件子进程崩溃, 尝试重启",
            plugin_id=self.plugin_id,
            restart_count=self._restart_count,
        )
        # 清理旧 process/conn, 重新 spawn 新子进程
        try:
            if self._process is not None:
                if self._process.is_alive():
                    self._process.terminate()
                    await asyncio.to_thread(self._process.join, 1.0)
                    # 第三轮审查 Major: SIGKILL 兜底 (与 kill() 对齐) —— 插件可在
                    # worker 内捕获/忽略 SIGTERM, terminate 后仍存活: 继续持有旧
                    # 连接写端使被超时放弃的 recv 线程永久阻塞, 自身成为孤儿进程。
                    # 每次 IPC 超时都可触发一轮, 不兜底 = 可被无限泄漏。
                    if self._process.is_alive():
                        self._process.kill()
                        await asyncio.to_thread(self._process.join, 1.0)
                self._process.close()
        except Exception:  # noqa: BLE001
            pass
        self._close_conns()
        if self._ctx is None:
            self._ctx = mp.get_context("spawn")
        # Fix-89: respawn 同样用 socketpair 字节帧 (不再用 pickle 语义的 Pipe)
        parent_sock, child_sock = socket.socketpair()
        self._parent_conn = _JsonFrameTransport(parent_sock)
        self._child_conn = child_sock
        self._process = self._ctx.Process(
            target=_plugin_worker,
            args=(self.plugin_id, child_sock, self._rlimits),
            daemon=True,
        )
        self._process.start()
        self._alive = True
        try:
            child_sock.close()
        except Exception:  # noqa: BLE001
            pass
        # C3: respawn 后 worker state 已重置 (空 plugin), 标记下次 call 重载插件
        # (此前 respawn 空 worker 不 reload, 后续 call 报"插件尚未加载" → 崩溃恢复名存实亡)。
        if self._plugin_path:
            self._needs_reload = True

    @property
    def is_alive(self) -> bool:
        if self._process is None:
            return False
        return self._alive and self._process.is_alive()
