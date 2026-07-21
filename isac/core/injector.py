"""PromptInjector 抽象基类 (SPECIFICATION.md 2.2 / ARCHITECTURE.md 3.4)。

基类放在 core/ 而非 agent/，是为了让 memory/injector/ 与 agent/injectors/ 都能按
同一条导入依赖链（utils → provider → memory → persona → agent → ...）单向依赖 core，
避免 memory 直接引用 agent 造成循环。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from isac.core.types import InjectionContext


class PromptInjector(ABC):
    """Prompt 注入器抽象基类。所有注入器必须继承此类。"""

    @property
    def key(self) -> str:
        """注入器唯一标识"""
        raise NotImplementedError

    @property
    def priority(self) -> int:
        """注入优先级 (数字越大越先注入)"""
        return 50

    @property
    def max_frequency_seconds(self) -> float:
        """最小触发间隔 (秒)。0 = 每次"""
        return 0.0

    @property
    def max_new_messages(self) -> int:
        """最小新消息数。0 = 不限制"""
        return 0

    @property
    def enabled(self) -> bool:
        """是否启用"""
        return True

    @property
    def tokens_estimate(self) -> int:
        """预估 token 数 (用于预算管理)"""
        return 200

    @abstractmethod
    async def build(self, context: InjectionContext) -> str:
        """返回注入文本，空字符串表示不注入"""
        ...
