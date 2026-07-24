"""D9 任务进度报告框架 (HUMANLIKE_RUNTIME.md / SPECIFICATION.md 1.6)。

Agent Loop 只提交 ``ProgressEvent``；本模块负责策略判断、频控、合并、脱敏、
人格化渲染与平台降级发送。默认关闭 (``policy.enabled=False`` 或未注入 sender
时全程惰性)，主链路热路径零变化。

骨架说明: 控制流与接口已就位；跨窗口合并、LLM 改写、丰富人设模板等复杂逻辑
以占位 / ``TODO(D9)`` 标注，留待 D9 实现节点补齐。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING

from isac.core.types import ProgressEvent
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = get_logger(__name__)

# 终态阶段: 不受最小间隔频控约束, 保证用户能收到收尾信号。
_TERMINAL_STAGES = frozenset({"tool_failed", "completed", "interrupted"})
# 脱敏时从 metadata 中剔除的敏感键 (占位清单, 实现节点接入统一脱敏器/SecretStore)。
_SENSITIVE_METADATA_KEYS = frozenset(
    {"api_key", "token", "authorization", "cookie", "secret", "password", "arguments"}
)


@dataclass
class ProgressPolicy:
    """每个 Agent 可覆盖的进度可见性与发送策略 (SPECIFICATION.md 1.6)。"""

    enabled: bool = True
    report_after_tool: bool = True
    report_before_slow_tool: bool = True
    slow_tool_threshold_seconds: float = 2.0
    min_interval_seconds: float = 2.0
    merge_window_seconds: float = 1.5
    max_visible_events_per_task: int = 8
    persona_rendering: str = "template"  # "template" | "llm" | "plain"

    @classmethod
    def from_config(cls, config: dict | None) -> ProgressPolicy:
        """从 Agent persona/progress 配置片段构造策略, 未知键忽略。"""
        config = config or {}
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in config.items() if k in known})


class PersonaProgressRenderer:
    """把结构化 ProgressEvent 渲染为符合人设的进度文案。

    骨架: ``template`` / ``plain`` 给出确定性文案, 不调用 LLM；``llm`` 模式留待
    实现节点接入受预算 / 超时约束的改写, 当前回退到模板渲染。
    """

    # 各阶段默认模板 (人设化词汇由 D9 实现节点结合 persona 扩展)。
    _STAGE_TEMPLATES = {
        "planned": "我先理一下接下来要做的事。",
        "tool_started": "我正在用 {tool} 处理…",
        "tool_finished": "{tool} 这步处理好了。",
        "tool_failed": "{tool} 没跑通, 我再想想别的办法。",
        "completed": "这件事我处理完了。",
        "interrupted": "先停一下, 我看看新消息。",
    }

    def __init__(self, persona: dict | None = None, mode: str = "template") -> None:
        self._persona = persona or {}
        self._mode = mode

    def render(self, event: ProgressEvent) -> str:
        """渲染进度文案。传入的 event.summary 已脱敏, 模板不回显原始参数。"""
        if self._mode == "llm":
            # TODO(D9): 接入受预算 / 超时 / 降级约束的 LLM 改写; 当前回退模板。
            return self._render_template(event)
        return self._render_template(event)

    def _render_template(self, event: ProgressEvent) -> str:
        tool = event.tool_name or "工具"
        template = self._STAGE_TEMPLATES.get(event.stage, "我在处理这件事。")
        text = template.format(tool=tool)
        if event.summary:
            text = f"{text} {event.summary}"
        return text


class ProgressReporter:
    """进度上报编排器: 频控 → 合并 → 脱敏 → 渲染 → 平台降级发送。

    每个 (agent, session) 任务持有一个实例。``sender`` 为 None 时全程惰性 (不发送),
    用于默认关闭场景。任一环节异常都不得冒泡影响主任务 —— 进度是尽力而为的旁路。
    """

    def __init__(
        self,
        *,
        agent_id: str,
        session_id: str,
        policy: ProgressPolicy | None = None,
        renderer: PersonaProgressRenderer | None = None,
        sender: Callable[[str, ProgressEvent], Awaitable[None]] | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.session_id = session_id
        self.policy = policy or ProgressPolicy()
        self.renderer = renderer or PersonaProgressRenderer(mode=self.policy.persona_rendering)
        self._sender = sender
        self._last_emit_at: float = 0.0
        self._visible_count_by_task: dict[str, int] = {}

    async def report(self, event: ProgressEvent) -> bool:
        """提交并按策略发送一个进度事件。返回是否实际发送。"""
        try:
            if not self._should_emit(event):
                return False
            event = self._merge(event)
            event = self._sanitize(event)
            text = self.renderer.render(event)
            await self._dispatch(text, event)
            self._last_emit_at = event.occurred_at or time.time()
            self._visible_count_by_task[event.task_id] = self._visible_count_by_task.get(event.task_id, 0) + 1
            return True
        except Exception as exc:
            logger.warning("进度上报失败, 已忽略", stage=event.stage, error=str(exc))
            return False

    def _should_emit(self, event: ProgressEvent) -> bool:
        """频控与每任务可见上限判定。

        占位: 简单最小间隔 + 计数上限; 终态阶段绕过间隔约束。跨窗口合并见 ``_merge``。
        """
        if not self.policy.enabled or not event.visible:
            return False
        count = self._visible_count_by_task.get(event.task_id, 0)
        if count >= self.policy.max_visible_events_per_task:
            return False
        if event.stage in _TERMINAL_STAGES:
            return True
        now = event.occurred_at or time.time()
        return (now - self._last_emit_at) >= self.policy.min_interval_seconds

    def _merge(self, event: ProgressEvent) -> ProgressEvent:
        """合并 merge_window 内的连续同类事件 (占位: 暂原样返回)。

        TODO(D9): 在 merge_window_seconds 窗口内合并相邻 tool_started/finished 降噪。
        """
        return event

    def _sanitize(self, event: ProgressEvent) -> ProgressEvent:
        """剔除敏感字段 (占位: 基础键名过滤; 实现节点接统一脱敏器)。

        summary / 文本禁止包含 reasoning、密钥、令牌、原始工具参数及未清洗结果。
        """
        if event.metadata:
            event.metadata = {k: v for k, v in event.metadata.items() if k.lower() not in _SENSITIVE_METADATA_KEYS}
        return event

    async def _dispatch(self, text: str, event: ProgressEvent) -> None:
        """发送渲染后的进度文案。sender 为 None 时惰性 no-op。

        普通 IM 由 sender 负责设置 ``metadata.message_kind=progress`` 等降级标记;
        WebChat 由 sender 负责输出原生 progress 帧。
        """
        if self._sender is None:
            return
        await self._sender(text, event)


def build_progress_reporter(
    *,
    agent_id: str,
    session_id: str,
    persona: dict | None = None,
    policy_config: dict | None = None,
    sender: Callable[[str, ProgressEvent], Awaitable[None]] | None = None,
) -> ProgressReporter:
    """按 Agent 配置构造 ProgressReporter (供 runtime/assembly 注入工厂使用)。"""
    policy = ProgressPolicy.from_config(policy_config)
    renderer = PersonaProgressRenderer(persona=persona, mode=policy.persona_rendering)
    return ProgressReporter(
        agent_id=agent_id,
        session_id=session_id,
        policy=policy,
        renderer=renderer,
        sender=sender,
    )
