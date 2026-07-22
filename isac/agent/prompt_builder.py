"""SystemPromptBuilder: System Prompt 组装器 (ARCHITECTURE.md 3.4)。

所有子系统的集成枢纽:
- 注入器按 priority 排序注入
- 注入器自带频率控制 (max_frequency_seconds / max_new_messages)
- 注入器自带 token 预算估算 (tokens_estimate)，可预算裁剪
"""

from __future__ import annotations

import time

from isac.core.injector import PromptInjector
from isac.core.types import InjectionContext
from isac.utils.logger import get_logger

logger = get_logger(__name__)


class SystemPromptBuilder:
    """System Prompt 组装器。每个 AgentInstance 持有一个独立实例。"""

    def __init__(self) -> None:
        self._injectors: list[PromptInjector] = []
        self._last_trigger_at: dict[str, float] = {}  # injector.key -> 上次触发时间 (monotonic)
        self._messages_since_trigger: dict[str, int] = {}  # injector.key -> 距上次触发的新消息数

    def register(self, injector: PromptInjector) -> None:
        """注册注入器。"""
        self._injectors.append(injector)
        # 初始化频率计数器，避免 max_new_messages 首次触发前键不存在导致死锁
        self._messages_since_trigger[injector.key] = 0

    async def build(self, context: InjectionContext) -> str:
        """按优先级组装各注入器的 Prompt 块。"""
        blocks: list[str] = []
        for injector in sorted(self._injectors, key=lambda i: -i.priority):
            if not injector.enabled:
                continue
            if not self._check_frequency(injector, context):
                logger.debug("注入器冷却中，跳过", injector=injector.key)
                continue
            try:
                text = await injector.build(context)
            except Exception as exc:
                # DEVELOP.md 4.1: Injector 失败不影响其他 Injector
                logger.warning("Injector 失败，跳过", injector=injector.key, error=str(exc))
                continue
            if not text:
                continue
            # TODO: token 预算裁剪 (tokens_estimate vs context.available_prompt_tokens)
            blocks.append(text)
            self._mark_triggered(injector)

        prompt = "\n\n".join(blocks)
        logger.debug("System Prompt 组装完成", injectors=len(blocks))
        return prompt

    def _check_frequency(self, injector: PromptInjector, context: InjectionContext) -> bool:
        """频率控制: 最小间隔 + 最小新消息数。"""
        if injector.max_frequency_seconds > 0:
            last = self._last_trigger_at.get(injector.key, 0.0)
            if time.monotonic() - last < injector.max_frequency_seconds:
                return False
        if injector.max_new_messages > 0:
            if self._messages_since_trigger.get(injector.key, 0) < injector.max_new_messages:
                return False
        return True

    def _mark_triggered(self, injector: PromptInjector) -> None:
        self._last_trigger_at[injector.key] = time.monotonic()
        self._messages_since_trigger[injector.key] = 0

    def notify_new_message(self) -> None:
        """会话收到新消息时调用，用于 max_new_messages 计数。"""
        for key in self._messages_since_trigger:
            self._messages_since_trigger[key] += 1
