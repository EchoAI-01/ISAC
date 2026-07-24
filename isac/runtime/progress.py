"""D9 任务进度报告框架 (HUMANLIKE_RUNTIME.md / SPECIFICATION.md 1.6)。

Agent Loop 只提交 ``ProgressEvent``；本模块负责策略判断、频控、合并、脱敏、
人格化渲染与平台降级发送。默认关闭 (``policy.enabled=False`` 或未注入 sender
时全程惰性)，主链路热路径零变化。

骨架说明: 控制流与接口已就位；跨窗口合并、LLM 改写、丰富人设模板等复杂逻辑
以占位 / ``TODO(D9)`` 标注，留待 D9 实现节点补齐。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, fields, replace
from typing import TYPE_CHECKING

from isac.core.types import ProgressEvent
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from isac.provider.base import LLMProvider

logger = get_logger(__name__)

# LLM 改写超时: 进度是旁路信号, 宁可回退模板也不能拖慢主任务的用户可感知延迟。
_LLM_RENDER_TIMEOUT_SECONDS = 3.0

# 终态阶段: 不受最小间隔频控约束, 保证用户能收到收尾信号。
_TERMINAL_STAGES = frozenset({"tool_failed", "completed", "interrupted"})
# 任务级终结阶段 (与 _TERMINAL_STAGES 不同: tool_failed 只是单步失败, 任务可能
# 继续尝试别的工具; 只有 completed/interrupted 代表整个任务的故事结束)。
_TASK_TERMINAL_STAGES = frozenset({"completed", "interrupted"})
# 脱敏时从 metadata 中剔除的敏感键 (占位清单, 实现节点接入统一脱敏器/SecretStore)。
_SENSITIVE_METADATA_KEYS = frozenset(
    {"api_key", "token", "authorization", "cookie", "secret", "password", "arguments"}
)
# _terminated_tasks 软上限: 超出后整体清空 (D9-5, 防止长期运行会话无界增长)。
_MAX_TERMINATED_TASKS = 500


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

    ``template`` / ``plain`` 给出确定性文案, 不调用 LLM；``llm`` 模式在注入了
    ``llm`` Provider 时受超时约束地请求改写, 超时/异常/空响应均静默回退模板
    (进度是旁路信号, 渲染失败绝不能影响主任务); 未注入 llm 时保持骨架期零行为
    变化, 直接回退模板。
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

    def __init__(
        self,
        persona: dict | None = None,
        mode: str = "template",
        llm: LLMProvider | None = None,
        timeout_seconds: float = _LLM_RENDER_TIMEOUT_SECONDS,
    ) -> None:
        self._persona = persona or {}
        self._mode = mode
        self._llm = llm
        self._timeout_seconds = timeout_seconds

    async def render(self, event: ProgressEvent) -> str:
        """渲染进度文案。传入的 event.summary 已脱敏, 模板不回显原始参数。"""
        template_text = self._render_template(event)
        if self._mode != "llm" or self._llm is None:
            return template_text
        rewritten = await self._render_with_llm(template_text)
        return rewritten if rewritten else template_text

    async def _render_with_llm(self, template_text: str) -> str | None:
        """受超时约束请求 LLM 用人设语气改写模板文案; 任何失败都返回 None 交由回退。"""
        assert self._llm is not None  # 调用方已判空
        persona_hint = f"人设参考: {self._persona}" if self._persona else "无特定人设, 保持自然口语。"
        system = (
            "你在为一个正在执行任务的 AI 助手改写一句简短的进度提示。"
            f"{persona_hint} 只输出改写后的一句话, 不超过 30 个字, 不添加原文之外的信息, "
            "不使用引号或前缀。"
        )
        try:
            response = await asyncio.wait_for(
                self._llm.chat(system, [{"role": "user", "content": template_text}]),
                timeout=self._timeout_seconds,
            )
        except Exception as exc:
            logger.warning("进度文案 LLM 改写失败, 回退模板", error=str(exc))
            return None
        rewritten = (response.content or "").strip()
        return rewritten or None

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
        self._pending_merge: dict[tuple[str, str], ProgressEvent] = {}
        self._terminated_tasks: set[str] = set()

    def rebind_sender(self, sender: Callable[[str, ProgressEvent], Awaitable[None]] | None) -> None:
        """D9: 复用 per-session 实例时重新绑定 sender (同一 session 后续消息可能来自不同连接)。"""
        self._sender = sender

    async def report(self, event: ProgressEvent) -> bool:
        """提交并按策略发送一个进度事件。返回是否实际发送。"""
        try:
            if not self._should_emit(event):
                return False
            event = self._merge(event)
            event = self._sanitize(event)
            text = await self.renderer.render(event)
            await self._dispatch(text, event)
            self._last_emit_at = event.occurred_at or time.time()
            self._visible_count_by_task[event.task_id] = self._visible_count_by_task.get(event.task_id, 0) + 1
            if event.stage in _TASK_TERMINAL_STAGES:
                self._mark_task_terminated(event.task_id)
            return True
        except Exception as exc:
            logger.warning("进度上报失败, 已忽略", stage=event.stage, error=str(exc))
            return False

    def _mark_task_terminated(self, task_id: str) -> None:
        """D9-5: 任务收束 (completed/interrupted) 后拉黑 task_id, 丢弃迟到的旧进度;
        同时清理该 task 在 _visible_count_by_task / _pending_merge 里的记录, 使
        这两个按 task 累积的字典不会随任务数量无界增长。"""
        if len(self._terminated_tasks) >= _MAX_TERMINATED_TASKS:
            self._terminated_tasks.clear()
        self._terminated_tasks.add(task_id)
        self._visible_count_by_task.pop(task_id, None)
        for key in [k for k in self._pending_merge if k[0] == task_id]:
            del self._pending_merge[key]

    def _should_emit(self, event: ProgressEvent) -> bool:
        """频控与每任务可见上限判定。

        占位: 简单最小间隔 + 计数上限; 终态阶段绕过间隔约束。跨窗口合并见 ``_merge``。
        D9-5: 任务已收束 (completed/interrupted) 后, 该 task 的任何迟到事件直接丢弃。
        """
        if event.task_id in self._terminated_tasks:
            return False
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
        """合并 merge_window_seconds 内, 同 task 同 stage 的相邻事件。

        合并策略: 保留最新事件的其它字段, 把 tool_name 与前一条去重拼接, 让既有
        渲染模板 (依赖 ``{tool}`` 占位符) 自然呈现"这几步都处理好了"式的合并
        文案, 不必改动 PersonaProgressRenderer。不跨 stage / 不跨 task 合并。
        """
        key = (event.task_id, event.stage)
        pending = self._pending_merge.get(key)
        if pending is not None and (event.occurred_at - pending.occurred_at) <= self.policy.merge_window_seconds:
            names = [name for name in (pending.tool_name, event.tool_name) if name]
            if names:
                event = replace(event, tool_name="、".join(dict.fromkeys(names)))
        self._pending_merge[key] = event
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
    llm: LLMProvider | None = None,
) -> ProgressReporter:
    """按 Agent 配置构造 ProgressReporter (供 runtime/assembly 注入工厂使用)。

    llm: persona_rendering="llm" 时用于改写模板文案; 未传入时该模式回退模板。
    """
    policy = ProgressPolicy.from_config(policy_config)
    renderer = PersonaProgressRenderer(persona=persona, mode=policy.persona_rendering, llm=llm)
    return ProgressReporter(
        agent_id=agent_id,
        session_id=session_id,
        policy=policy,
        renderer=renderer,
        sender=sender,
    )
