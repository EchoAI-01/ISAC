"""PluginIsolationHost: 插件进程隔离宿主 (O2, PLUGIN_COMPATIBILITY.md)。

O2 实现: 用 multiprocessing.Process spawn 子进程, stdin/stdout JSON-RPC
IPC; spawn 时设资源限额 (resource.setrlimit CPU/RSS/NOFILE); call 编码
IPCEnvelope → JSON → 管道发送 → 等待 result/error → 解码; 子进程崩溃
自动重启 (最多 max_restart_attempts 次, 默认 3)。默认不接管现有 in-process
loader (loader.py 不变), enabled=False 时主链路零行为变化。

子进程入口 _plugin_worker 是一个最小 echo 服务器, 真实插件 SDK 可替换。
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import resource
import sys
import time
from typing import Any

from isac.plugin.isolation.protocol import IPCEnvelope
from isac.utils.logger import get_logger

logger = get_logger(__name__)

# 默认重启次数上限; 超过后放弃 (is_alive=False)
DEFAULT_MAX_RESTART_ATTEMPTS = 3


def _plugin_worker(plugin_id: str, pipe_conn: Any) -> None:
    """子进程入口: 最小 echo worker (真实插件 SDK 可替换)。

    读 stdin 一行 JSON → 处理 → 写 stdout 一行 JSON。
    限制: CPU 1 核 (软), RSS 256MB, NOFILE 64 (resource.setrlimit)。
    """
    try:
        # 资源限额 (POSIX; macOS/Linux 支持, Windows 跳过)
        if hasattr(resource, "RLIMIT_CPU"):
            resource.setrlimit(resource.RLIMIT_CPU, (1, 1))  # 1 秒 CPU 软/硬上限
        if hasattr(resource, "RLIMIT_NOFILE"):
            resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        if hasattr(resource, "RLIMIT_AS"):
            # RSS 256MB (字节)
            resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
    except (ValueError, OSError, PermissionError):
        pass  # 权限不足或平台不支持时跳过
    while True:
        try:
            line = pipe_conn.recv()
            if line is None:
                break
            env = json.loads(line) if isinstance(line, str) else line
            # echo: 把 payload.echo 回去 (或 echo 字段)
            payload = env.get("payload", {})
            echo_text = payload.get("text", "") or payload.get("echo", "")
            result = {
                "kind": "result",
                "plugin_id": plugin_id,
                "payload": {"echo": echo_text},
                "correlation_id": env.get("correlation_id", ""),
            }
            pipe_conn.send(json.dumps(result))
        except EOFError:
            break
        except Exception as exc:  # noqa: BLE001
            # 子进程内任何异常都返回 error, 不让 worker 崩溃
            err = {
                "kind": "error",
                "plugin_id": plugin_id,
                "payload": {"error": str(exc)},
                "correlation_id": env.get("correlation_id", "") if "env" in dir() else "",
            }
            try:
                pipe_conn.send(json.dumps(err))
            except Exception:  # noqa: BLE001
                break


class PluginIsolationHost:
    """隔离插件宿主 (每个隔离插件一个子进程)。"""

    def __init__(
        self,
        plugin_id: str,
        *,
        max_restart_attempts: int = DEFAULT_MAX_RESTART_ATTEMPTS,
    ) -> None:
        self.plugin_id = plugin_id
        self.max_restart_attempts = max(0, int(max_restart_attempts))
        self._alive = False
        self._process: mp.process.BaseProcess | None = None
        self._parent_conn: Any = None
        self._child_conn: Any = None
        self._restart_count = 0
        self._correlation_counter = 0
        self._ctx: Any = None

    async def spawn(self) -> None:
        """启动隔离子进程 (multiprocessing.Process + Pipe + 资源限额)."""
        if self._alive and self._process is not None and self._process.is_alive():
            return
        # multiprocessing 默认 fork (POSIX), 减少 spawn 开销
        self._ctx = mp.get_context("fork") if sys.platform != "win32" else mp.get_context("spawn")
        self._parent_conn, self._child_conn = self._ctx.Pipe()
        self._process = self._ctx.Process(
            target=_plugin_worker,
            args=(self.plugin_id, self._child_conn),
            daemon=True,
        )
        self._process.start()
        self._alive = True
        logger.info(
            "插件子进程已启动",
            plugin_id=self.plugin_id,
            pid=self._process.pid,
        )

    async def kill(self) -> None:
        """终止隔离子进程并回收资源 (幂等)."""
        if self._process is not None:
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=2.0)
                if self._process.is_alive():
                    self._process.kill()
                    self._process.join(timeout=1.0)
            self._process.close()
            self._process = None
        if self._parent_conn is not None:
            try:
                self._parent_conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._parent_conn = None
        self._alive = False
        logger.debug("插件子进程已终止", plugin_id=self.plugin_id)

    async def call(self, envelope: IPCEnvelope) -> IPCEnvelope:
        """向隔离插件发起一次 IPC 调用并等待结果。

        编码 envelope → JSON → 管道发送 → 等待 result/error → 解码。
        子进程崩溃时自动重启 (最多 max_restart_attempts 次)。
        """
        if not self._alive or self._parent_conn is None:
            raise RuntimeError(f"插件 {self.plugin_id} 未 spawn, 无法调用")
        self._correlation_counter += 1
        envelope.correlation_id = f"corr-{self._correlation_counter}"
        try:
            self._parent_conn.send(json.dumps({
                "kind": envelope.kind,
                "plugin_id": envelope.plugin_id,
                "payload": envelope.payload,
                "correlation_id": envelope.correlation_id,
            }))
        except (BrokenPipeError, OSError) as exc:
            # 管道断 = 子进程崩溃, 触发重启
            logger.warning("IPC 管道断, 触发重启", plugin_id=self.plugin_id, error=str(exc))
            self._on_crash()
            raise RuntimeError(f"插件 {self.plugin_id} 子进程崩溃, 已触发重启") from exc
        # 等待响应 (同步 recv, 包在 to_thread 避免阻塞 event loop)
        import asyncio

        try:
            raw = await asyncio.to_thread(self._parent_conn.recv)
        except EOFError as exc:
            self._on_crash()
            raise RuntimeError(f"插件 {self.plugin_id} 子进程已退出") from exc
        data = json.loads(raw) if isinstance(raw, str) else raw
        return IPCEnvelope(
            kind=data.get("kind", "result"),
            plugin_id=data.get("plugin_id", self.plugin_id),
            payload=data.get("payload", {}),
            correlation_id=data.get("correlation_id", ""),
        )

    def _on_crash(self) -> None:
        """子进程崩溃时调: 计数 + 重启 (未超 max_restart_attempts)."""
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
        # 清理旧 process/conn, 同步 spawn 新子进程 (在 event loop 外)
        try:
            if self._process is not None:
                if self._process.is_alive():
                    self._process.terminate()
                    self._process.join(timeout=1.0)
                self._process.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._parent_conn is not None:
                self._parent_conn.close()
        except Exception:  # noqa: BLE001
            pass
        if self._ctx is None:
            self._ctx = mp.get_context("fork") if sys.platform != "win32" else mp.get_context("spawn")
        self._parent_conn, self._child_conn = self._ctx.Pipe()
        self._process = self._ctx.Process(
            target=_plugin_worker,
            args=(self.plugin_id, self._child_conn),
            daemon=True,
        )
        self._process.start()
        self._alive = True

    @property
    def is_alive(self) -> bool:
        if self._process is None:
            return False
        return self._alive and self._process.is_alive()


# 避免未使用 import 警告
_ = (os, time)
