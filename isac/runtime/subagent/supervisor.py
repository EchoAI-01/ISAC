"""J4 SubAgentSupervisor (SPECIFICATION.md 2.5)。

管理子任务生命周期: submit / get_status / list_runs / fetch_log / cancel。生效权限是
父 Agent 权限、Agent SubAgentPolicy、Channel/全局策略与本次任务限制的交集。

骨架状态: 运行索引 + 状态查询 + 权限交集 + 幂等取消 + 日志分页 就位; 真实子 Agent
执行循环 (独立 History/Prompt/Budget/Workspace)、超时/取消向 Provider/工具/子进程传播
留待 J4 实现节点。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from isac.runtime.subagent.models import TERMINAL_STATUSES, SubAgentPolicy, SubAgentRun
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.core.types import AgentContext
    from isac.runtime.subagent.journal import SubAgentJournal
    from isac.runtime.subagent.models import SubAgentEvent, SubAgentTask

logger = get_logger(__name__)


class SubAgentSupervisor:
    """子任务监督器。"""

    def __init__(self, journal: SubAgentJournal | None = None, *, parent_policy: SubAgentPolicy | None = None) -> None:
        self._journal = journal
        # 父 Agent / 全局默认策略, 与任务策略求交集得到生效权限。
        self._parent_policy = parent_policy or SubAgentPolicy()
        self._runs: dict[str, SubAgentRun] = {}

    async def submit(self, task: SubAgentTask) -> SubAgentRun:
        """登记一个子任务并返回 queued 状态。

        骨架: 只创建 Run 与生效策略, 不启动真实执行循环 (留待 J4 实现节点)。
        """
        effective = self._effective_policy(task)
        now = int(time.time())
        run = SubAgentRun(task_id=task.task_id, status="queued", started_at=now, updated_at=now)
        self._runs[task.task_id] = run
        if self._journal is not None:
            await self._journal.upsert_run(run)
        logger.info("子任务已登记", task_id=task.task_id, max_tokens=effective.max_tokens)
        return run

    async def get_status(self, task_id: str, requester: AgentContext | None = None) -> SubAgentRun | None:
        """查询子任务状态; 不存在返回 None。"""
        self._authorize(requester, task_id)
        return self._runs.get(task_id)

    async def list_runs(
        self, requester: AgentContext | None = None, filters: dict[str, Any] | None = None
    ) -> list[SubAgentRun]:
        """列出子任务 (可选按 status 过滤)。"""
        self._authorize(requester, None)
        runs = list(self._runs.values())
        status = (filters or {}).get("status")
        if status:
            runs = [r for r in runs if r.status == status]
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
        """取消子任务 (幂等)。已达终态不改写, 超时任务由执行循环置为 timed_out。"""
        self._authorize(requester, task_id)
        run = self._runs.get(task_id)
        if run is None:
            return None
        if run.status in TERMINAL_STATUSES:
            return run
        run.status = "cancelled"
        run.updated_at = int(time.time())
        run.finished_at = run.updated_at
        if self._journal is not None:
            await self._journal.upsert_run(run)
        # TODO(J4): 把取消幂等传播到 Provider 调用、工具调用与子进程。
        return run

    def _effective_policy(self, task: SubAgentTask) -> SubAgentPolicy:
        """生效权限 = 父/全局策略 ∩ 任务策略。

        TODO(J4): 再与 Channel/全局策略求交集, 保证恒为父层子集。
        """
        return self._parent_policy.intersect(task.policy)

    def _authorize(self, requester: AgentContext | None, task_id: str | None) -> None:
        """请求方鉴权占位。

        TODO(J4): 校验 requester 是否有权查询 / 操作该 task_id (跨 Agent 边界); 当前放行。
        """
        return None
