"""J4 SubAgent 数据契约 (SPECIFICATION.md 2.5)。

子 Agent 是父 Agent 下的临时隔离执行单元, 使用独立上下文与收窄权限, 结果和脱敏日志
通过 task_id 关联。生效权限是父 Agent 权限、Agent SubAgentPolicy、Channel/全局策略和
本次任务限制的交集。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from isac.core.types import TokenUsage

# Fix-5: SubAgentPolicy() 裸默认值 (未显式配置策略时) 使用的安全只读工具子集,
# 不含 bash/write_file/send_* 等有副作用/高风险的工具。_merge_allowlist 改成
# 严格交集后, 如果默认值仍是空列表, 两侧都用默认值时交集恒为空集,
# delegate_task 会变成零工具、功能报废——所以默认值本身就必须是"交集后仍然
# 有效"的安全基线, 而不是依赖 fail-open 隐式继承另一方。
DEFAULT_ALLOWED_TOOLS = ("query_memory", "web_search", "read_file", "fetch_history")


def _merge_allowlist(a: list[str], b: list[str]) -> list[str]:
    """求两个 allow-list 的严格交集 (空集拒绝全部, 无特殊情况; DEVELOPMENT_PLAN.md
    的"空集拒绝全部"承诺)。"""
    return sorted(set(a) & set(b))


@dataclass
class SubAgentPolicy:
    """子 Agent 的权限与资源上限 (SPECIFICATION.md 2.5)。"""

    max_tokens: int = 8_000
    timeout_seconds: int = 120
    max_tool_calls: int = 12
    max_depth: int = 1
    max_log_bytes: int = 256_000
    allowed_tools: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_TOOLS))
    # 记忆访问默认空 (不同于 allowed_tools): "不默认复制主会话...私有记忆正文"
    # 本身就是安全默认值, 不需要一个非空基线才有意义。
    readable_memory_scopes: list[str] = field(default_factory=list)
    allow_memory_write: bool = False
    allow_channel_send: bool = False
    allow_delegate: bool = False

    def intersect(self, other: SubAgentPolicy) -> SubAgentPolicy:
        """求两个策略的交集 (取更严格者), 用于权限收窄。

        数值上限取 min; allow-list 用 _merge_allowlist 合并; 布尔权限取 AND
        (两层都放行才放行), 保证子 Agent 权限恒为父层子集。
        """
        return SubAgentPolicy(
            max_tokens=min(self.max_tokens, other.max_tokens),
            timeout_seconds=min(self.timeout_seconds, other.timeout_seconds),
            max_tool_calls=min(self.max_tool_calls, other.max_tool_calls),
            max_depth=min(self.max_depth, other.max_depth),
            max_log_bytes=min(self.max_log_bytes, other.max_log_bytes),
            allowed_tools=_merge_allowlist(self.allowed_tools, other.allowed_tools),
            readable_memory_scopes=_merge_allowlist(self.readable_memory_scopes, other.readable_memory_scopes),
            allow_memory_write=self.allow_memory_write and other.allow_memory_write,
            allow_channel_send=self.allow_channel_send and other.allow_channel_send,
            allow_delegate=self.allow_delegate and other.allow_delegate,
        )


@dataclass
class ContextEnvelope:
    """传给子 Agent 的最小上下文信封。

    约束 (§2.5.1): 不默认复制主会话全量历史、MoodState、RelationshipState、用户画像
    或私有记忆正文; 只带最小任务摘要与显式授权的引用。
    """

    objective: str
    summary: str = ""  # 主 Agent 提供的最小任务摘要
    authorized_refs: list[str] = field(default_factory=list)  # 显式授权的证据 / 记忆引用
    allowed_memory_scopes: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class SubAgentTask:
    """一次子任务的提交描述 (SPECIFICATION.md 2.5)。"""

    task_id: str
    parent_agent_id: str
    session_id: str
    trace_id: str
    objective: str
    output_schema: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)  # 最小摘要和授权引用
    policy: SubAgentPolicy = field(default_factory=SubAgentPolicy)
    created_at: int = 0


@dataclass
class SubAgentRun:
    """子任务运行状态 (SPECIFICATION.md 2.5)。"""

    task_id: str
    status: str = "queued"  # queued | running | waiting_tool | succeeded | failed | cancelled | timed_out
    phase: str = ""
    started_at: int = 0
    updated_at: int = 0
    finished_at: int = 0
    tokens_used: int = 0
    tool_calls_used: int = 0
    error_code: str = ""
    error_summary: str = ""
    result_summary: str = ""  # J4-2: succeeded 时存 runner 返回的 SubAgentResult.summary
    # Fix-10: 创建该子任务的父 Agent, 用于跨 Agent 鉴权 (_authorize) 与
    # Control API 按 agent_id 过滤 (routes_subagent.py::list_subagent_runs)。
    parent_agent_id: str = ""
    # Q5: 此前 SubAgentResult.usage 与 evidence_refs 在 _run_task 里被丢弃——
    # 只把 result.summary 存进 result_summary, usage/evidence_refs 完全没落
    # 到 run 上, 控制面拿不到 (routes_subagent 只能查到 summary)。现在保留,
    # 控制面 list_subagent_runs / get_status 都能读到。
    usage: TokenUsage = field(default_factory=TokenUsage)
    evidence_refs: list[str] = field(default_factory=list)


@dataclass
class SubAgentEvent:
    """子任务追加式日志事件 (SPECIFICATION.md 2.5); 不记录模型原始 reasoning。"""

    task_id: str
    seq: int
    event_type: str  # status | model | tool | evidence | result | error
    timestamp: int
    summary: str
    tool_name: str = ""
    usage: TokenUsage | None = None
    evidence_refs: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)  # 已脱敏、已截断


@dataclass
class SubAgentResult:
    """子任务结构化结果 (主 Agent 默认只收到本对象)。"""

    task_id: str
    status: str
    summary: str
    data: dict = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    log_cursor: int = 0
    completed_at: int = 0


# 终态状态集合: 到达后不可再被 cancel 改写。
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "timed_out"})
