"""ApplicationRuntime: 应用统一生命周期与后台任务管理 (K1, DEVELOPMENT_PLAN.md)。

之前 main() 调用 channel_registry.start_all() 后直接返回, 事件循环结束就把
Control/Alert/Channel 后台任务全部取消, 进程无法持续驻留; uvicorn 用裸
create_task 启动不持有引用, 关闭路径缺失 (CODE_REVIEW_REPORT.md #12/#13)。

本模块引入 ApplicationRuntime 作为统一容器:
- 所有后台任务通过 spawn(coro) 注册到 TaskGroup, 持有强引用, 关闭时统一 cancel+await
- signal_handler 注册 SIGINT/SIGTERM, 触发 request_stop() (优雅关闭)
- 后台任务异常不会静默丢失: TaskGroup 会把第一个异常作为 ExceptionGroup 抛出
- 启动失败时已注册资源按 LIFO 倒序 stop, 不留泄漏

用法:
    runtime = ApplicationRuntime()
    await runtime.start()              # 进入 TaskGroup 上下文
    runtime.spawn(adapter.start())    # Channel 适配器后台
    runtime.spawn(alert_manager._check_loop())  # Alert 后台
    await runtime.serve_forever()      # 阻塞直到收到 SIGINT/SIGTERM
    await runtime.shutdown()           # 优雅关闭 (stop_all + 取消所有 task + await)
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from isac.utils.logger import get_logger

logger = get_logger(__name__)


class ApplicationRuntime:
    """应用统一生命周期容器。

    持有 asyncio.TaskGroup 与 stop 事件, 提供资源注册/优雅关闭/signal 处理。
    资源通过 register_lifecycle(start, stop) 成对注册, 启动按注册顺序, 关闭按 LIFO。
    """

    def __init__(self) -> None:
        self._tg: asyncio.TaskGroup | None = None
        self._stop_event: asyncio.Event | None = None
        self._lifecycle: list[tuple[str, Callable[[], Awaitable[None]], Callable[[], Awaitable[None]]]] = []
        self._tasks: list[asyncio.Task[Any]] = []
        self._started = False
        self._closed = False

    @property
    def started(self) -> bool:
        return self._started

    def register_lifecycle(
        self,
        name: str,
        start: Callable[[], Awaitable[None]],
        stop: Callable[[], Awaitable[None]],
    ) -> None:
        """注册一个 (start, stop) 资源对, 启动按注册顺序, 关闭按 LIFO 倒序。"""
        if self._started:
            raise RuntimeError(f"运行时已启动, 不能注册资源: {name}")
        self._lifecycle.append((name, start, stop))

    def spawn(self, coro: Coroutine[Any, Any, Any], *, name: str = "") -> asyncio.Task[Any]:
        """把后台 coro 注册到 TaskGroup; 持有强引用避免被 GC。

        TaskGroup 内部异常会冒泡到 __aexit__, 由 serve_forever 的 try/except 转译为
        request_stop() 让关闭路径走起来, 不静默丢失。
        """
        if self._tg is None:
            raise RuntimeError("runtime 未 start(), 不能 spawn")
        task: asyncio.Task[Any] = self._tg.create_task(coro, name=name or None)
        self._tasks.append(task)
        return task

    async def start(self) -> None:
        """启动所有注册的资源 (按注册顺序), 失败时已启动的按 LIFO 回滚。"""
        if self._started:
            return
        self._started = True
        self._stop_event = asyncio.Event()
        self._tg = asyncio.TaskGroup()
        await self._tg.__aenter__()
        started_names: list[str] = []
        for name, start, _ in self._lifecycle:
            try:
                await start()
                started_names.append(name)
                logger.info("资源已启动", resource=name)
            except Exception:
                logger.error("资源启动失败, 回滚已启动资源", resource=name, exc_info=True)
                # LIFO 回滚
                for rollback_name, _, stop in reversed(
                    [(n, s, t) for n, s, t in self._lifecycle if n in started_names]
                ):
                    try:
                        await stop()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("回滚停止失败", resource=rollback_name, error=str(exc))
                await self._tg.__aexit__(None, None, None)
                self._started = False
                self._tg = None
                raise

    def request_stop(self) -> None:
        """请求优雅关闭 (SIGINT/SIGTERM 触发或外部调用)。"""
        if self._stop_event is not None and not self._stop_event.is_set():
            logger.info("收到关闭请求, 开始优雅关闭")
            self._stop_event.set()

    def install_signal_handlers(self) -> None:
        """注册 SIGINT/SIGTERM, 触发 request_stop() 而非默认 KeyboardInterrupt。

        安装失败 (如非主线程) 仅记日志, 不阻塞启动——某些测试环境无法注册信号。
        """
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.request_stop)
            except (NotImplementedError, RuntimeError, ValueError) as exc:
                logger.warning(
                    "信号处理注册失败 (Windows/非主线程环境), 依赖默认 KeyboardInterrupt",
                    signal=sig.name,
                    error=str(exc),
                )

    def remove_signal_handlers(self) -> None:
        """关闭后清理信号 handler, 避免下次启动重复 (测试多轮场景)。"""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.remove_signal_handler(sig)
            except (NotImplementedError, RuntimeError, ValueError, KeyError):
                pass

    async def serve_forever(self) -> None:
        """阻塞直到 request_stop() 触发, 期间后台任务在 TaskGroup 内运行。"""
        if self._stop_event is None:
            raise RuntimeError("runtime 未 start(), 不能 serve_forever")
        try:
            await self._stop_event.wait()
        except asyncio.CancelledError:
            # 外部 cancel (测试场景或父任务关闭) 也视为 request_stop
            self.request_stop()
            raise

    async def shutdown(self) -> None:
        """优雅关闭: stop LIFO + cancel 所有后台 task + await TaskGroup 退出。

        TaskGroup.__aexit__ 在正常退出时不会 cancel 未完成的 spawn task (只 cancel
        发生异常时的兄弟 task); 因此 shutdown 需要先显式 cancel 所有未完成的 spawn
        task, 再走 __aexit__ 等待它们结束 (K1)。
        """
        if not self._started or self._closed:
            return
        self._closed = True
        # 1. LIFO 停止已注册资源 (channel/control/alert/provider/storage/...)
        for name, _, stop in reversed(self._lifecycle):
            try:
                await stop()
                logger.info("资源已停止", resource=name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("停止资源失败, 继续关闭其他资源", resource=name, error=str(exc))
        # 2. 显式 cancel 所有未完成的 spawn task (TaskGroup 在 __aexit__ 默认不 cancel)
        for task in self._tasks:
            if not task.done():
                task.cancel(msg="application shutdown")
        # 3. TaskGroup.__aexit__ 等所有 task 结束
        if self._tg is not None:
            try:
                await self._tg.__aexit__(None, None, None)
            except BaseException as exc:  # noqa: BLE001
                logger.warning("TaskGroup 关闭时收到异常 (已记录, 不再抛出)", error=str(exc))
        self.remove_signal_handlers()
        self._started = False
        self._tasks.clear()
        logger.info("应用运行时已关闭")
