"""插件进程级隔离 (O2 企业化)。

[框架已搭建 / scaffolding] IPCEnvelope 契约 + PluginIsolationHost 骨架就位。
当前插件仍为 loader.py 的进程内兼容层 (非安全沙箱); 进程级隔离见
DEVELOPMENT_PLAN.md §四 O2。默认不接管加载路径, 零行为变化。
"""

from __future__ import annotations

from isac.plugin.isolation.host import PluginIsolationHost
from isac.plugin.isolation.protocol import IPCEnvelope

__all__ = [
    "IPCEnvelope",
    "PluginIsolationHost",
]
