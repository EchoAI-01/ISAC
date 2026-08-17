"""U5 ApprovalGate: ask 档工具的人工审批门 (HITL)。

四段管线中 ask 档的落地: 工具策略判定为 ask 时, 执行前向会话投递审批卡片
(经注入的 send_card 通道), 等待人工"同意/拒绝"回复, 超时 fail-closed 按拒绝。

审批回流两条路 (都汇到 ``decide``):
- **IM 回复**: 用户在原会话回复 ``同意 <审批码>`` / ``拒绝 <审批码>``
  (process_message 入口经 ``parse_reply`` 拦截, 不触发常规对话回合);
- **控制面**: ``POST /api/v1/approvals/{id}/decide`` (运维侧审批)。

卡片形态: 各 Channel 适配器均无交互按钮能力 (侦察认定), 卡片为结构化文本 +
审批码, 机制与渠道解耦; 未来适配器支持按钮回调时只需把回调接到 decide()。
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from isac.utils.logger import get_logger

logger = get_logger(__name__)

# 审批结果三态 (request 返回值)。
VERDICT_APPROVED = "approved"
VERDICT_REJECTED = "rejected"
VERDICT_TIMEOUT = "timeout"

# IM 回复解析: "同意 ab12cd34" / "approve ab12cd34" ...
_APPROVE_PATTERN = re.compile(
    r"^\s*(同意|批准|允许|approve|approved|agree|yes)\s+([a-z0-9]{4,16})\s*$", re.IGNORECASE
)
_REJECT_PATTERN = re.compile(
    r"^\s*(拒绝|不同意|deny|denied|reject|rejected|no)\s+([a-z0-9]{4,16})\s*$", re.IGNORECASE
)


@dataclass
class ApprovalRequest:
    """一次待审批请求 (pending 期间驻留 ApprovalGate._pending)。"""

    approval_id: str
    session_key: str
    tool_name: str
    args_summary: str
    created_at: float
    future: asyncio.Future
    decider: str = ""  # decide 时回填 (human:<来源>)
    _meta: dict[str, Any] = field(default_factory=dict)


class ApprovalGate:
    """ask 档审批门 (进程级单例, services['approval_gate'])。"""

    def __init__(self, timeout_seconds: float = 300.0) -> None:
        self._timeout_seconds = max(5.0, float(timeout_seconds or 300.0))
        self._pending: dict[str, ApprovalRequest] = {}

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    def render_card(self, req: ApprovalRequest) -> str:
        """审批卡片文本 (结构化, 渠道无关)。"""
        return "\n".join(
            [
                "⚠️ 工具执行审批请求",
                f"审批码: {req.approval_id}",
                f"工具: {req.tool_name}",
                f"参数摘要: {req.args_summary or '(无)'}",
                f"请在 {int(self._timeout_seconds)} 秒内回复:",
                f"  同意 {req.approval_id}  ← 批准执行",
                f"  拒绝 {req.approval_id}  ← 拒绝执行",
                "超时未回复将自动拒绝 (fail-closed)。",
            ]
        )

    async def request(
        self,
        session_key: str,
        tool_name: str,
        args_summary: str = "",
        send_card: Any = None,
    ) -> tuple[str, ApprovalRequest]:
        """发起一次审批等待, 返回 (verdict, request)。

        verdict ∈ approved/rejected/timeout。send_card: 可选 async callable(card_text),
        投递失败不阻塞等待 (卡片发不出时人仍可能经控制面审批)。
        """
        loop = asyncio.get_running_loop()
        req = ApprovalRequest(
            approval_id=uuid.uuid4().hex[:8],
            session_key=session_key,
            tool_name=tool_name,
            args_summary=args_summary[:500],
            created_at=time.time(),
            future=loop.create_future(),
        )
        self._pending[req.approval_id] = req
        logger.info(
            "工具审批请求已创建", approval_id=req.approval_id, tool=tool_name, session=session_key
        )
        try:
            if send_card is not None:
                try:
                    await send_card(self.render_card(req))
                except Exception as exc:  # noqa: BLE001 卡片投递失败不阻塞审批等待
                    logger.warning("审批卡片投递失败, 仍可经控制面审批", error=str(exc))
            verdict = await asyncio.wait_for(req.future, timeout=self._timeout_seconds)
            return verdict, req
        except TimeoutError:
            logger.info("工具审批超时, fail-closed 拒绝", approval_id=req.approval_id, tool=tool_name)
            return VERDICT_TIMEOUT, req
        finally:
            self._pending.pop(req.approval_id, None)

    def decide(self, approval_id: str, verdict: str, decider: str = "") -> bool:
        """对 pending 审批做出决定 (approved/rejected)。

        未知/已过期/已决定的审批码返回 False (调用方据此判定是否按普通消息处理)。
        """
        req = self._pending.get(str(approval_id or "").strip())
        if req is None or req.future.done():
            return False
        if verdict not in (VERDICT_APPROVED, VERDICT_REJECTED):
            return False
        req.decider = decider or "human"
        req.future.set_result(verdict)
        logger.info(
            "工具审批已决定", approval_id=req.approval_id, verdict=verdict, decider=req.decider
        )
        return True

    @staticmethod
    def parse_reply(content: str) -> tuple[str, str] | None:
        """解析 IM 审批回复 → (approval_id, verdict); 非审批回复返回 None。"""
        text = str(content or "").strip()
        if not text:
            return None
        m = _APPROVE_PATTERN.match(text)
        if m:
            return m.group(2).lower(), VERDICT_APPROVED
        m = _REJECT_PATTERN.match(text)
        if m:
            return m.group(2).lower(), VERDICT_REJECTED
        return None

    def pending_requests(self) -> list[dict[str, Any]]:
        """当前 pending 审批列表 (控制面 GET /approvals 用)。"""
        now = time.time()
        return [
            {
                "approval_id": r.approval_id,
                "session_key": r.session_key,
                "tool_name": r.tool_name,
                "args_summary": r.args_summary,
                "created_at": r.created_at,
                "elapsed_seconds": round(now - r.created_at, 1),
            }
            for r in self._pending.values()
            if not r.future.done()
        ]
