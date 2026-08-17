"""U5 工具权限决策理由规范词汇表 (drift 防护)。

四段管线 (pre-execute → 单调 guard → 执行 → post 审计) 落事件表的
decision/decider/reason 字段必须取自本模块的规范值 —— 审计才能按词汇聚合查询;
自由文本理由会造成同义漂移 (denied/deny/DENY/被拒...)。

drift test (tests/unit/test_u5_permission_pipeline.py): 断言管线代码实际产出的
全部理由都在 ``DECISION_REASONS`` 内, 且每个规范值都有产出点 (无死词汇)。
"""

from __future__ import annotations

# ── decision (四段管线的最终决策) ────────────────────────────
DECISION_ALLOW = "allow"            # 直接放行
DECISION_DENY = "deny"              # 直接拒绝
DECISION_ASK_APPROVED = "ask_approved"   # ask 档人工批准
DECISION_ASK_REJECTED = "ask_rejected"   # ask 档人工拒绝
DECISION_ASK_TIMEOUT = "ask_timeout"     # ask 档超时 fail-closed

DECISIONS: frozenset[str] = frozenset(
    {DECISION_ALLOW, DECISION_DENY, DECISION_ASK_APPROVED, DECISION_ASK_REJECTED, DECISION_ASK_TIMEOUT}
)

# ── decider (决策者) ─────────────────────────────────────────
DECIDER_POLICY = "policy"    # 策略表 (ToolPermission/EnableMatrix/tools_policy)
DECIDER_SYSTEM = "system"    # 系统机制 (服务门/未知工具/guard)
DECIDER_HUMAN = "human"      # 人工 (IM 审批回复 / 控制面审批端点)

DECIDERS: frozenset[str] = frozenset({DECIDER_POLICY, DECIDER_SYSTEM, DECIDER_HUMAN})

# ── reason (规范理由词汇) ────────────────────────────────────
REASON_POLICY_ALLOW = "policy_allow"            # 策略表判定放行
REASON_POLICY_DENY = "policy_deny"              # 策略表判定禁用
REASON_SERVICE_MISSING = "service_missing"      # restricted 工具后端服务未注入
REASON_UNKNOWN_TOOL = "unknown_tool"            # 未注册的工具名
REASON_ASK_UNAVAILABLE = "ask_unavailable"      # ask 档但审批门未接线 (fail-closed)
REASON_HUMAN_APPROVED = "human_approved"        # 人工批准
REASON_HUMAN_REJECTED = "human_rejected"        # 人工拒绝
REASON_ASK_TIMEOUT = "ask_timeout"              # 审批超时, fail-closed 拒绝
REASON_PRIOR_DENIAL = "prior_denial"            # 单调 guard: 本会话已被拒绝, 不可翻回
REASON_EXECUTED = "executed"                    # 执行完成 (post 审计的通过理由)

DECISION_REASONS: frozenset[str] = frozenset(
    {
        REASON_POLICY_ALLOW,
        REASON_POLICY_DENY,
        REASON_SERVICE_MISSING,
        REASON_UNKNOWN_TOOL,
        REASON_ASK_UNAVAILABLE,
        REASON_HUMAN_APPROVED,
        REASON_HUMAN_REJECTED,
        REASON_ASK_TIMEOUT,
        REASON_PRIOR_DENIAL,
        REASON_EXECUTED,
    }
)


def validate_reason(reason: str) -> str:
    """校验理由在规范词汇表内; 越表 raise ValueError (防 drift, fail-fast)。"""
    if reason not in DECISION_REASONS:
        raise ValueError(f"决策理由越出规范词汇表: {reason!r} (见 decision_reasons.DECISION_REASONS)")
    return reason
