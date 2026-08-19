"""网关级入站消息幂等去重 (阶段3-2 M4)。

背景: dispatch 主链路全程无 ``(platform, msg_id)`` 去重 —— OneBot WS 重连、webhook
重试等场景的重复投递会**重复落事件 + 重复回复**。此前仅 qq_official 适配器有事件级
去重 (Fix-96), onebot/telegram/discord/webchat/feishu/wechat 均为 0。

本模块提供平台无关的 ``InboundDeduplicator`` (LRU 上限 + TTL 过期双约束, 与
qq_official Fix-96 同构), 由 dispatch 入口统一接线, 一次覆盖全部渠道 —— 各适配器
无需各自实现, 口径一致。

设计取舍: LRU+TTL 双限保证表不无界增长; 空 msg_id 不去重 (无法判重, 放行避免误丢);
TTL 窗口外的"古老重投"会再次放行 —— 与 qq_official 一致的有界内存权衡。
"""

from __future__ import annotations

import time
from collections import OrderedDict

# 去重表容量与 TTL 默认值 (对齐 qq_official Fix-96 量级; 入口级覆盖全渠道, 上限略放大)。
DEFAULT_DEDUP_MAX = 4096
DEFAULT_DEDUP_TTL_SECONDS = 600.0


class InboundDeduplicator:
    """入站消息 ``(platform, msg_id)`` 幂等去重表 (LRU + TTL 双限)。

    单一入口 ``is_duplicate()``; 同步、无 IO、O(1) 均摊, 可安全置于消息主链路。
    非线程安全 —— 设计为在 dispatch 单一事件循环内调用 (与 SessionLockManager 同域)。
    """

    def __init__(
        self,
        max_entries: int = DEFAULT_DEDUP_MAX,
        ttl_seconds: float = DEFAULT_DEDUP_TTL_SECONDS,
    ) -> None:
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._max = max(1, int(max_entries))
        self._ttl = max(0.0, float(ttl_seconds))

    def is_duplicate(self, platform: str, msg_id: str) -> bool:
        """已见 (TTL 内) 返回 True; 首见记录并返回 False。

        空 msg_id 不去重 (无法判重, 放行避免误丢)。顺带惰性清理过期条目并按
        LRU 上限淘汰最旧, 保证表不无界增长。
        """
        if not msg_id:
            return False
        key = f"{platform}:{msg_id}"
        now = time.time()
        # 惰性清理过期条目 (从最旧开始, 遇未过期即停)
        while self._seen:
            oldest_key, oldest_ts = next(iter(self._seen.items()))
            if now - oldest_ts < self._ttl:
                break
            self._seen.pop(oldest_key, None)
        if key in self._seen:
            self._seen.move_to_end(key)
            return True
        self._seen[key] = now
        while len(self._seen) > self._max:
            self._seen.popitem(last=False)
        return False

    def __len__(self) -> int:
        return len(self._seen)
