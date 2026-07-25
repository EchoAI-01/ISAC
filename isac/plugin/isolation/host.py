"""PluginIsolationHost: 插件进程隔离宿主骨架 (O2)。

[框架已搭建 / scaffolding] 把插件从进程内兼容层升级为进程级隔离的挂接点就位:
spawn/kill/call/健康检查;真正的子进程宿主、IPC 传输、资源限额、崩溃恢复留待 O2
实现节点 (见 TODO)。默认不接管现有 in-process 加载路径 (loader.py 不变), 零行为变化。
"""

from __future__ import annotations

from isac.plugin.isolation.protocol import IPCEnvelope
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class PluginIsolationHost:
    """隔离插件宿主骨架 (每个隔离插件一个子进程)。

    当前插件仍走 loader.py 的进程内加载 (兼容层, 非安全沙箱); 本宿主是 O2 升级到
    进程级隔离的落点。骨架阶段全部 no-op / 抛 NotImplementedError, 不被主链路调用。
    """

    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        self._alive = False

    async def spawn(self) -> None:
        """启动隔离子进程。

        TODO(O2): fork/exec 子进程宿主 + 建立 IPC 管道 + 资源限额 (cgroup/rlimit)。
        骨架阶段 no-op (不真正启动进程)。
        """
        logger.debug("插件隔离 spawn (骨架 no-op)", plugin_id=self.plugin_id)

    async def kill(self) -> None:
        """终止隔离子进程并回收资源。TODO(O2): 优雅终止 + 超时强杀。"""
        self._alive = False

    async def call(self, envelope: IPCEnvelope) -> IPCEnvelope:
        """向隔离插件发起一次 IPC 调用并等待结果。

        TODO(O2): 编码 envelope → 管道发送 → 等待 result/error → 解码。
        骨架阶段抛 NotImplementedError (被 registry 捕获为工具错误, 但默认不接入)。
        """
        raise NotImplementedError("插件进程隔离 (O2) 尚未实现")

    @property
    def is_alive(self) -> bool:
        return self._alive
