"""插件进程隔离 IPC 协议契约 (O2)。

宿主进程与隔离插件进程间的消息封套。纯数据、不含行为; 传输在 host.py。

[框架已搭建 / scaffolding] 契约就位; 真实 IPC 编解码与传输留待 O2 实现节点。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IPCEnvelope:
    """宿主 ↔ 隔离插件进程的 IPC 消息封套 (O2)。"""

    kind: str  # call | result | error | event | heartbeat
    plugin_id: str
    payload: dict = field(default_factory=dict)
    correlation_id: str = ""  # 关联 call ↔ result
