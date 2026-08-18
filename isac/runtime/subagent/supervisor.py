"""J4 SubAgentSupervisor (SPECIFICATION.md 2.5)。

管理子任务生命周期: submit / get_status / list_runs / fetch_log / cancel。生效权限是
父 Agent 权限、Agent SubAgentPolicy、Channel/全局策略与本次任务限制的交集。

J4-1: 真实执行循环落地。submit() 接受 runner_factory 注入时, 用 asyncio.create_task
后台派生子 Agent 执行; 状态机 queued → running → succeeded/failed/cancelled/timed_out;
超时通过 asyncio.wait_for 控制; 取消通过 asyncio.Task.cancel() 传播。
未注入 runner_factory 时保持骨架行为 (返回 queued, 不启动后台 task)。
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from isac.core.types import TokenUsage
from isac.runtime.subagent.models import TERMINAL_STATUSES, SubAgentPolicy, SubAgentRun
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from isac.core.types import AgentContext
    from isac.runtime.subagent.journal import SubAgentJournal
    from isac.runtime.subagent.models import SubAgentEvent, SubAgentResult, SubAgentTask

logger = get_logger(__name__)

# Fix-130: _runs 内存索引默认上限。到达终态的 run 已落 Journal (持久化可回读),
# 内存索引只保留最近这么多条, 防长期运行无界增长。
DEFAULT_MAX_TRACKED_RUNS = 500


class SubAgentSupervisor:
    """子任务监督器。"""

    def __init__(
        self,
        journal: SubAgentJournal | None = None,
        *,
        parent_policy: SubAgentPolicy | None = None,
        runner_factory: Callable[[SubAgentTask], Awaitable[SubAgentResult]] | None = None,
        cancel_grace_seconds: float = 0.5,
        max_concurrent: int = 4,
        max_tracked_runs: int = DEFAULT_MAX_TRACKED_RUNS,
    ) -> None:
        self._journal = journal
        # 父 Agent / 全局默认策略, 与任务策略求交集得到生效权限。
        self._parent_policy = parent_policy or SubAgentPolicy()
        # J4-1: 子 Agent 执行循环工厂, 由 main.py / AgentManager 注入。
        # None 时 submit() 保持骨架行为 (返回 queued, 不启动后台 task)。
        self._runner_factory = runner_factory
        self._cancel_grace_seconds = cancel_grace_seconds
        self._runs: dict[str, SubAgentRun] = {}
        # Fix-130: _runs 内存索引上限 —— 长期运行下每个 submit 都新增一条 run 且从不
        # 淘汰, 无界增长。到达终态的 run 已落 Journal (持久化, 可经 fetch_log/restore
        # 读回), 内存索引只保留最近 max_tracked_runs 条; 超限时按 finished_at 从最旧
        # 终态 run 开始淘汰 (活跃 run 绝不淘汰)。<=0 表示不限制 (向后兼容)。
        self._max_tracked_runs = max(0, int(max_tracked_runs))
        # 后台 task 索引 (task_id → asyncio.Task), 用于 cancel 传播
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        # Q5: 并发上限 (信号量), 防止短时间大量 submit 把父 Agent 的 LLM 调用
        # 配额耗尽或导致上下文窗口爆掉。默认 4 (合理基线, 可按 LLM 配额调整)。
        # <=0 表示不限制 (向后兼容默认行为)。
        self._max_concurrent = max(0, int(max_concurrent))
        self._concurrency_sem: asyncio.Semaphore | None = (
            asyncio.Semaphore(self._max_concurrent) if self._max_concurrent > 0 else None
        )

    def set_runner_factory(
        self,
        runner_factory: Callable[[SubAgentTask], Awaitable[SubAgentResult]],
    ) -> None:
        """在 AgentManager 就绪后绑定生产 runner。"""
        self._runner_factory = runner_factory

    async def submit(self, task: SubAgentTask) -> SubAgentRun:
        """登记一个子任务并返回 queued 状态。

        J4-1: 若 runner_factory 已注入, 用 asyncio.create_task 后台派生执行;
        状态机 queued → running → succeeded/failed/timed_out/cancelled;
        超时通过 asyncio.wait_for 控制。未注入时保持骨架行为。
        """
        effective = self._effective_policy(task)
        task.policy = effective
        depth = int(task.context.get("task_depth", 0) or 0)
        if depth > effective.max_depth:
            raise ValueError(
                f"子任务递归深度 {depth} 超过策略上限 {effective.max_depth}"
            )
        now = int(time.time())
        run = SubAgentRun(
            task_id=task.task_id, status="queued", started_at=now, updated_at=now,
            parent_agent_id=task.parent_agent_id,
        )
        self._runs[task.task_id] = run
        if self._journal is not None:
            await self._journal.upsert_run(run)
        logger.info("子任务已登记", task_id=task.task_id, max_tokens=effective.max_tokens)
        # J4-1: 启动后台执行循环 (若有 runner_factory)
        if self._runner_factory is not None:
            bg_task = asyncio.create_task(self._run_task(task, effective))
            self._tasks[task.task_id] = bg_task
        return run

    async def _run_task(self, task: SubAgentTask, policy: SubAgentPolicy) -> None:
        """后台执行子任务: 状态 running → 调 runner → 终态。

        任何异常都捕获并置终态, 不让后台 task 异常静默丢失。Journal 接收 status 事件。
        Q5: 经 max_concurrent 信号量限流, 防止短时间大量 submit 把父 Agent 的
        LLM 调用配额耗尽或上下文窗口爆掉; max_concurrent<=0 时无限制 (向后兼容)。
        """
        run = self._runs.get(task.task_id)
        if run is None:
            return
        # 信号量 acquire (若有); 释放放在 finally 确保 cancel/timeout 也释放
        sem_acquired = False
        if self._concurrency_sem is not None:
            await self._concurrency_sem.acquire()
            sem_acquired = True
        try:
            # 状态 → running + 写 journal
            await self._transition(
                run, task.task_id, "running", "status", "running", max_log_bytes=policy.max_log_bytes
            )

            runner = self._runner_factory(task) if self._runner_factory is not None else None
            if runner is None:
                return
            try:
                # 超时控制: asyncio.wait_for 在 timeout_seconds 后取消 runner
                result = await asyncio.wait_for(runner, timeout=policy.timeout_seconds)
                # cancel() 可能已把 run 置为终态；吞掉 CancelledError 的 runner 晚到结果
                # 不得把 cancelled 覆盖成 succeeded。
                if run.status in TERMINAL_STATUSES:
                    return
                run.result_summary = result.summary
                # Q5: 保留 SubAgentResult.usage 与 evidence_refs 到 run 上 (此前被丢弃,
                # 控制面拿不到)。_transition 把它们落到 run.usage / run.evidence_refs,
                # routes_subagent 的 list_subagent_runs / get_status 都能读到。
                await self._transition(
                    run, task.task_id, "succeeded", "status", f"succeeded: {result.summary}",
                    finished=True, max_log_bytes=policy.max_log_bytes,
                    usage=result.usage, evidence_refs=result.evidence_refs,
                )
            except TimeoutError:
                await self._transition(
                    run, task.task_id, "timed_out", "error",
                    f"timed_out: 任务超时 ({policy.timeout_seconds}s)",
                    finished=True, error_code="TIMEOUT",
                    error_summary=f"任务超时 ({policy.timeout_seconds}s)",
                    max_log_bytes=policy.max_log_bytes,
                )
                logger.warning("子任务超时", task_id=task.task_id, timeout=policy.timeout_seconds)
            except asyncio.CancelledError:
                # 被 cancel() 主动取消 (run.status 已被 cancel() 置为 cancelled)
                if self._journal is not None:
                    await self._journal.append(
                        self._make_event(task.task_id, "status", "cancelled"),
                        max_log_bytes=policy.max_log_bytes,
                    )
                raise  # CancelledError 必须向上传播 (asyncio 约定)
            except Exception as exc:  # noqa: BLE001
                await self._transition(
                    run, task.task_id, "failed", "error", f"failed: {str(exc)[:500]}",
                    finished=True, error_code=type(exc).__name__, error_summary=str(exc)[:500],
                    max_log_bytes=policy.max_log_bytes,
                )
                logger.warning("子任务失败", task_id=task.task_id, error=str(exc))
        finally:
            if sem_acquired and self._concurrency_sem is not None:
                self._concurrency_sem.release()
            self._tasks.pop(task.task_id, None)

    async def _transition(
        self,
        run: SubAgentRun,
        task_id: str,
        status: str,
        event_type: str,
        summary: str,
        *,
        finished: bool = False,
        error_code: str = "",
        error_summary: str = "",
        max_log_bytes: int | None = None,
        usage: TokenUsage | None = None,
        evidence_refs: list[str] | None = None,
    ) -> None:
        """状态转移 + journal 写入 (upsert_run + append event)。"""
        now = int(time.time())
        run.status = status
        run.updated_at = now
        if finished:
            run.finished_at = now
        if error_code:
            run.error_code = error_code
        if error_summary:
            run.error_summary = error_summary
        # Q5: usage 与 evidence_refs 落到 run 上 (此前 SubAgentResult 的这两个字段被丢弃)。
        if usage is not None:
            run.usage = usage
            run.tokens_used = int(getattr(usage, "total_tokens", 0) or 0)
        if evidence_refs is not None:
            run.evidence_refs = list(evidence_refs)
        # Fix-130: 到达终态时顺带淘汰超上限的旧终态 run (活跃 run 不受影响)。
        if finished:
            self._prune_terminal_runs()
        if self._journal is None:
            return
        try:
            await self._journal.upsert_run(run)
            await self._journal.append(self._make_event(task_id, event_type, summary), max_log_bytes=max_log_bytes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Journal 写入失败, 不阻塞 _run_task", task_id=task_id, error=str(exc))

    @staticmethod
    def _make_event(task_id: str, event_type: str, summary: str) -> SubAgentEvent:
        """构造一个 SubAgentEvent (seq 由 Journal.append 内部分配)。"""
        from isac.runtime.subagent.models import SubAgentEvent

        return SubAgentEvent(
            task_id=task_id,
            seq=0,  # Journal.append 会用 COALESCE(MAX(seq)+1, 1) 重写
            event_type=event_type,
            timestamp=int(time.time()),
            summary=summary,
        )

    def _prune_terminal_runs(self) -> None:
        """Fix-130: _runs 超上限时淘汰最旧的**终态** run (活跃 run 绝不动)。

        终态 run 已落 Journal, 内存索引淘汰后仍可经 fetch_log/restore_interrupted
        回读, 不丢数据。max_tracked_runs<=0 时不限制 (向后兼容)。终态 run 不足时
        只淘汰现有终态条目, 允许短暂超出上限 (等更多 run 到终态再收敛), 绝不误删
        queued/running 活跃任务。
        """
        if self._max_tracked_runs <= 0 or len(self._runs) <= self._max_tracked_runs:
            return
        terminal = [
            (task_id, run)
            for task_id, run in self._runs.items()
            if run.status in TERMINAL_STATUSES
        ]
        # 最旧在前 (finished_at 缺省回落 updated_at)
        terminal.sort(key=lambda kv: kv[1].finished_at or kv[1].updated_at)
        excess = len(self._runs) - self._max_tracked_runs
        for task_id, _run in terminal[:excess]:
            self._runs.pop(task_id, None)

    async def get_status(self, task_id: str, requester: AgentContext | None = None) -> SubAgentRun | None:
        """查询子任务状态; 不存在返回 None。"""
        self._authorize(requester, task_id)
        return self._runs.get(task_id)

    async def list_runs(
        self, requester: AgentContext | None = None, filters: dict[str, Any] | None = None
    ) -> list[SubAgentRun]:
        """列出子任务 (可选按 status/parent_agent_id 过滤)。

        list 没有单一 task_id 可交给 _authorize 做存在性校验, 跨 Agent 边界改为
        直接按 parent_agent_id 过滤结果集 (调用方按需传入, 不强制)。
        """
        self._authorize(requester, None)
        runs = list(self._runs.values())
        filters = filters or {}
        status = filters.get("status")
        if status:
            runs = [r for r in runs if r.status == status]
        parent_agent_id = filters.get("parent_agent_id")
        if parent_agent_id:
            runs = [r for r in runs if r.parent_agent_id == parent_agent_id]
        return runs

    async def fetch_log(
        self, task_id: str, after_seq: int = 0, limit: int = 100, requester: AgentContext | None = None
    ) -> list[SubAgentEvent]:
        """分页读取脱敏日志 (委托 Journal); 无 Journal 时返回空列表。"""
        self._authorize(requester, task_id)
        if self._journal is None:
            return []
        return await self._journal.fetch_after(task_id, after_seq, limit)

    async def cancel(self, task_id: str, requester: AgentContext | None = None) -> SubAgentRun | None:
        """取消子任务 (幂等)。已达终态不改写; running 中取消通过 asyncio.Task.cancel() 传播。"""
        self._authorize(requester, task_id)
        run = self._runs.get(task_id)
        if run is None:
            return None
        if run.status in TERMINAL_STATUSES:
            return run
        run.status = "cancelled"
        run.updated_at = int(time.time())
        run.finished_at = run.updated_at
        self._prune_terminal_runs()  # Fix-130: cancel 也直达终态, 顺带淘汰超限旧终态 run
        if self._journal is not None:
            await self._journal.upsert_run(run)
        # J4-1: 取消传播到后台 task (asyncio.Task.cancel → runner 收到 CancelledError)
        bg_task = self._tasks.get(task_id)
        if bg_task is not None and not bg_task.done():
            bg_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(bg_task), timeout=self._cancel_grace_seconds)
            except asyncio.CancelledError:
                # Fix-114: 区分两种 CancelledError 来源 ——
                # ① **后台任务被取消** (cancel 的正常预期结果): shield 把 bg_task 的
                #    CancelledError 透传出来, 当前任务自身并未被取消 (cancelling()==0),
                #    吞掉它是正确的;
                # ② **当前任务自身被取消** (优雅关闭/打断传播): cancelling()>0。此前
                #    无差别 `pass` 会把这种情况也吞掉, 导致取消协议失效 (该终止的任务
                #    继续往下执行)。仅对 ② 重新抛出; run 状态已在上方标 cancelled 并落
                #    journal, 无未完成的清理, 重抛安全。
                current = asyncio.current_task()
                if current is not None and current.cancelling() > 0:
                    raise
            except TimeoutError:
                run.error_code = "CANCEL_TIMEOUT"
                run.error_summary = (
                    f"取消请求已发出，但执行器未在 {self._cancel_grace_seconds}s 内退出"
                )
                if self._journal is not None:
                    await self._journal.upsert_run(run)
                    await self._journal.append(
                        self._make_event(task_id, "error", run.error_summary)
                    )
                logger.warning(
                    "子任务取消宽限期超时",
                    task_id=task_id,
                    grace_seconds=self._cancel_grace_seconds,
                )
            except Exception as exc:  # noqa: BLE001
                run.error_code = "CANCEL_FAILED"
                run.error_summary = str(exc)[:500]
                logger.warning("子任务取消等待失败", task_id=task_id, error=str(exc))
        return run

    def _effective_policy(self, task: SubAgentTask) -> SubAgentPolicy:
        """生效权限 = 父/全局策略 ∩ 任务策略。

        TODO(J4): 再与 Channel/全局策略求交集, 保证恒为父层子集。
        """
        return self._parent_policy.intersect(task.policy)

    def _authorize(self, requester: AgentContext | None, task_id: str | None) -> None:
        """请求方鉴权: 拒绝一个 Agent 查询/操作另一个 Agent 创建的子任务。

        requester=None 表示控制面/管理员调用 (不代表某个具体 Agent 身份), 放行,
        由 Control API 自己的 scope 校验负责; requester 有值但对应的 run 不存在
        (task_id 未知) 时也放行, 交给调用方的 "run is None" 分支处理 404, 这里
        只做已存在任务的归属校验, 避免把"资源不存在"和"无权访问"混为一谈。
        """
        if requester is None or task_id is None:
            return
        run = self._runs.get(task_id)
        if run is None or not run.parent_agent_id:
            return
        # getattr 防御: requester 理论上总是真实 AgentContext (由 loop/tool 层构造),
        # 但保留兜底避免调用方传入不完整占位对象时直接抛 AttributeError 崩掉主链路。
        services = getattr(requester, "services", None) or {}
        requester_agent_id = str(services.get("agent_id", "") or "")
        if requester_agent_id and requester_agent_id != run.parent_agent_id:
            raise PermissionError(f"无权访问其它 Agent 创建的子任务: {task_id}")

    async def restore_interrupted(self) -> int:
        """J4-3: 重启恢复。从 Journal 读出所有持久化 run, 把 running/queued 标记为
        cancelled (中断后不恢复旧进度, 与 D9 ProgressReporter 思路一致); 已终态保留。

        返回标记为 cancelled 的 run 数量。无 Journal 时返回 0 (no-op)。
        """
        if self._journal is None:
            return 0
        # 先从 DB 读出所有持久化 run, 重建内存索引
        persisted = await self._journal.restore()
        if not persisted:
            return 0
        now = int(time.time())
        marked = 0
        for run in persisted:
            # running/queued 视为中断, 标记 cancelled
            # Fix-83: **先改状态落库, 再登记内存索引** —— 此前先 `_runs[...] = run`
            # 再改状态, 两步之间有 await (upsert_run), 并发 get_status/list_runs
            # 会看到"重启前已死的任务仍是 running"的幻影中间态 (调用方可能据此
            # 等待/查询一个永远不会终结的任务)。
            if run.status in ("running", "queued", "waiting_tool"):
                run.status = "cancelled"
                run.updated_at = now
                run.finished_at = now
                run.error_code = "INTERRUPTED"
                run.error_summary = "进程重启, 任务中断"
                marked += 1
                await self._journal.upsert_run(run)
            self._runs[run.task_id] = run
        if marked > 0:
            logger.info("SubAgent 重启恢复完成", marked_cancelled=marked, total=len(persisted))
        return marked
