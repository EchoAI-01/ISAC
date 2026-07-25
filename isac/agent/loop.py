"""ISACAgentLoop: Agent 循环 (ARCHITECTURE.md 3.5)。

主流程: hook: pre_llm → LLM.chat → hook: post_llm
       if tool_calls: hook: pre_tool → exec_tool → hook: post_tool
       else: hook: final_response → return
错误处理: 工具失败返回错误结果给 LLM (SPECIFICATION.md 5.1)。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from typing import TYPE_CHECKING

from isac.agent.hooks import AgentHooks
from isac.core.events import AgentHookPoint
from isac.core.exceptions import ToolError
from isac.core.types import (
    AgentContext,
    InjectionContext,
    LLMChunk,
    LLMResponse,
    ProgressEvent,
    TokenUsage,
    ToolCall,
    ToolResult,
)
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.agent.prompt_builder import SystemPromptBuilder
    from isac.agent.tools.registry import ToolRegistry
    from isac.provider.base import LLMProvider
    from isac.provider.manager import ProviderManager

logger = get_logger(__name__)


class AgentResult:
    """Agent Loop 运行结果"""

    def __init__(
        self,
        content: str = "",
        interrupted: bool = False,
        stopped_by_budget: bool = False,
    ):
        self.content = content
        self.interrupted = interrupted
        self.stopped_by_budget = stopped_by_budget


class ISACAgentLoop:
    """Agent 循环。每个 AgentInstance 持有一个独立实例。"""

    def __init__(
        self,
        llm: LLMProvider,
        prompt_builder: SystemPromptBuilder,
        hooks: AgentHooks,
        tools: ToolRegistry,
        provider_manager: ProviderManager | None = None,
        services: dict | None = None,
    ):
        self.llm = llm
        self.prompt_builder = prompt_builder
        self.hooks = hooks
        self.tools = tools
        self.provider_manager = provider_manager
        self.services = services or {}

    async def run(self, messages: list[dict], context: AgentContext) -> AgentResult:
        """执行 Agent 循环，直到产出最终回复 / 被打断 / 预算耗尽。

        planned/completed/interrupted 只在本轮确实执行过工具调用 (即存在多步"任务")
        时才报告；单轮直接给出文本回复的简单对话不产生这三类事件, 避免每条问候
        都附带"我先理一下接下来要做的事"这类噪音 (D9)。
        """
        reported_task_progress = False
        while context.budget.remaining:
            context.iteration += 1

            # 每轮重新构建 system prompt (记忆/画像/行话需要刷新)
            injection_context = self._to_injection_context(context)
            system_prompt = await self.prompt_builder.build(injection_context)

            # PRE_LLM: 记忆检索/画像/行话 等在这里注入
            # 顺序调用，每个 hook 收到上一个 hook 修改后的 messages，实现串联
            for hook in self.hooks.get_hooks(AgentHookPoint.PRE_LLM):
                try:
                    result = await hook(messages, context)
                    if isinstance(result, list):
                        messages = result
                except Exception as exc:
                    logger.error("PRE_LLM Hook 执行失败，已跳过", error=str(exc), exc_info=True)

            # LLM 调用 (支持流式和非流式)
            response = await self._call_llm(system_prompt, messages, context)
            context.budget.consume(response.usage)

            # POST_LLM
            await self.hooks.fire(AgentHookPoint.POST_LLM, response, context)

            # 被新消息打断
            if context.interrupt_requested:
                await self._emit_progress_if_task_started(context, reported_task_progress, "interrupted")
                return AgentResult(interrupted=True)

            if response.tool_calls:
                reported_task_progress = await self._emit_task_planned_once(context, reported_task_progress)
                # LLM API 要求 tool 消息必须紧跟在声明了对应 tool_calls 的 assistant
                # 消息之后, 否则下一轮请求里 tool_call_id 找不到归属会被 API 拒绝。
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": [
                            {
                                "id": tool_call.id,
                                "type": "function",
                                "function": {
                                    "name": tool_call.name,
                                    "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
                                },
                            }
                            for tool_call in response.tool_calls
                        ],
                    }
                )
                for tool_call in response.tool_calls:
                    result = await self._execute_tool(tool_call, context)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result.content,
                        }
                    )
            else:
                await self.hooks.fire(AgentHookPoint.FINAL_RESPONSE, response, context)
                await self._emit_progress_if_task_started(context, reported_task_progress, "completed")
                return AgentResult(content=response.content)

            # COMPRESS: 上下文过大时
            if context.should_compress():
                await self.hooks.fire(AgentHookPoint.COMPRESS, messages, context)

        return AgentResult(stopped_by_budget=True)

    async def _execute_tool(self, tool_call: ToolCall, context: AgentContext) -> ToolResult:
        """执行单个工具: PRE_TOOL 权限检查 → 执行 → POST_TOOL 副作用。"""
        # PRE_TOOL: 返回 False 可阻止
        results = await self.hooks.fire(AgentHookPoint.PRE_TOOL, tool_call, context)
        if any(r is False for r in results):
            return ToolResult(content=f"工具 {tool_call.name} 被权限策略阻止", is_error=True)

        metrics = self.services.get("metrics")
        if metrics is not None:
            metrics.counter("isac_tool_calls_total").inc()

        # D9: 慢工具前置事件 —— 只有当工具执行时间超过阈值才报告 tool_started,
        # 用哨兵任务实现, 工具正常完成后立即 cancel, 未触发时不产生任何进度事件。
        # report_progress 为 None、或 Agent 配置 report_before_slow_tool=False 时
        # 不创建哨兵任务 (保持零行为变化 / 尊重显式关闭)。
        slow_tool_task: asyncio.Task[None] | None = None
        if context.report_progress is not None and context.services.get("progress_report_before_slow_tool", True):
            slow_tool_task = asyncio.create_task(self._emit_slow_tool_started(context, tool_call.name))
        try:
            result = await self.tools.execute(tool_call, context, services=self.services)
        except ToolError as exc:
            logger.warning("工具执行失败", tool=tool_call.name, error=str(exc))
            result = ToolResult(content=f"工具 {tool_call.name} 执行失败: {exc.message}", is_error=True)
        except Exception as exc:
            logger.error("工具执行严重错误", tool=tool_call.name, error=str(exc), exc_info=True)
            result = ToolResult(content="工具执行内部错误", is_error=True)
        finally:
            if slow_tool_task is not None:
                slow_tool_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await slow_tool_task

        if metrics is not None and result.is_error:
            metrics.counter("isac_tool_errors_total").inc()

        # POST_TOOL: 触发记忆更新等副作用
        await self.hooks.fire(AgentHookPoint.POST_TOOL, tool_call, result, context)

        # D9: 工具完成后按人设报告进度 (context.report_progress 为 None 时惰性跳过)。
        await self._emit_progress(
            context,
            "tool_failed" if result.is_error else "tool_finished",
            tool_name=tool_call.name,
        )
        return result

    async def _emit_task_planned_once(self, context: AgentContext, already_reported: bool) -> bool:
        """D9: 本轮第一次出现工具调用时报告 planned, 返回更新后的 already_reported。"""
        if already_reported:
            return True
        await self._emit_progress(context, "planned")
        return True

    async def _emit_progress_if_task_started(self, context: AgentContext, task_started: bool, stage: str) -> None:
        """D9: 只有此前已报告过 planned (即存在多步任务) 才发 completed/interrupted 收束。"""
        if task_started:
            await self._emit_progress(context, stage)

    async def _emit_slow_tool_started(self, context: AgentContext, tool_name: str) -> None:
        """D9: sleep 阈值后报告 tool_started; 工具正常完成时被外层 cancel, 永不触发。"""
        threshold = float(context.services.get("progress_slow_tool_threshold_seconds", 2.0))
        await asyncio.sleep(threshold)
        await self._emit_progress(context, "tool_started", tool_name=tool_name)

    async def _emit_progress(
        self,
        context: AgentContext,
        stage: str,
        *,
        tool_name: str | None = None,
        summary: str = "",
    ) -> None:
        """提交进度事件 (D9)。

        ``context.report_progress`` 为 None 时直接返回 (默认关闭), 主链路热路径零变化。
        进度是旁路信号, 发送失败在此吞掉, 不得中断主任务。
        """
        callback = context.report_progress
        if callback is None:
            return
        event = ProgressEvent(
            event_id=uuid.uuid4().hex,
            task_id=str(context.services.get("task_id") or context.session.session_id),
            agent_id=str(context.services.get("agent_id", "")),
            session_id=context.session.session_id,
            stage=stage,
            tool_name=tool_name,
            summary=summary,
            occurred_at=time.time(),
        )
        try:
            await callback(event)
        except Exception as exc:
            logger.warning("进度事件提交失败, 已忽略", stage=stage, error=str(exc))

    async def _call_llm(self, system_prompt: str, messages: list[dict], context: AgentContext) -> LLMResponse:
        """统一 LLM 调用入口，处理流式和非流式。

        优先使用 ProviderManager.chat_with_retry（重试+回退+降级）；
        未注入 ProviderManager 时退化为直接调用 llm.chat（测试/单 Provider 场景）。
        """
        tools_def = self.tools.definitions()
        if context.streaming:
            # 流式模式暂不支持 chat_with_retry 的重试包装 (chunk 已流式推给 on_chunk,
            # 中断后无法干净重试), 直接走原 LLM 流式接口; 用量/指标记录见 _call_llm_streaming。
            return await self._call_llm_streaming(system_prompt, messages, tools_def, context)

        if self.provider_manager is not None:
            agent_id, session_id, trace_id = self._correlation_ids(context)
            return await self.provider_manager.chat_with_retry(
                self.llm,
                agent_id=agent_id,
                session_id=session_id,
                trace_id=trace_id,
                system=system_prompt,
                messages=messages,
                tools=tools_def,
            )
        return await self.llm.chat(system_prompt, messages, tools_def)

    async def _call_llm_streaming(
        self, system_prompt: str, messages: list[dict], tools_def: list[dict], context: AgentContext
    ) -> LLMResponse:
        """流式 LLM 调用: 逐 chunk 转发 on_chunk, 结束后记录一次用量 (J1, 成功/失败都记录)。"""
        start = time.monotonic()
        status = "success"
        response: LLMResponse | None = None
        chunks: list[LLMChunk] = []
        try:
            async for chunk in self.llm.chat_stream(system_prompt, messages, tools_def):
                chunks.append(chunk)
                if context.on_chunk:
                    await context.on_chunk(chunk)
            response = self._merge_chunks(chunks)
            return response
        except Exception:
            status = "failed"
            raise
        finally:
            if self.provider_manager is not None:
                agent_id, session_id, trace_id = self._correlation_ids(context)
                self.provider_manager.record_stream_result(
                    self.llm,
                    response,
                    latency_ms=int((time.monotonic() - start) * 1000),
                    status=status,
                    agent_id=agent_id,
                    session_id=session_id,
                    trace_id=trace_id,
                )

    @staticmethod
    def _correlation_ids(context: AgentContext) -> tuple[str, str, str]:
        """J1: 从 context 取 (agent_id, session_id, trace_id), 供用量记录关联同一逻辑调用。

        trace_id 复用 D9 已经为每轮消息生成的 task_id, 不新增字段。
        """
        return (
            str(context.services.get("agent_id", "")),
            context.session.session_id,
            str(context.services.get("task_id", "")),
        )

    def _merge_chunks(self, chunks: list[LLMChunk]) -> LLMResponse:
        """将流式 chunks 合并为完整响应。"""
        content = "".join(c.delta_content for c in chunks)
        reasoning = "".join(c.delta_reasoning for c in chunks)
        tool_calls = [c.tool_call for c in chunks if c.tool_call]
        usage = chunks[-1].usage if chunks else TokenUsage()
        return LLMResponse(content=content, reasoning=reasoning, tool_calls=tool_calls, usage=usage)

    @staticmethod
    def _to_injection_context(context: AgentContext) -> InjectionContext:
        """AgentContext → InjectionContext (共享同一批字段)。"""
        return InjectionContext(
            session=context.session,
            user_profile=context.user_profile,
            current_message=context.current_message,
            pending_messages=context.pending_messages,
            timestamp=context.timestamp,
            available_prompt_tokens=context.available_prompt_tokens,
        )
