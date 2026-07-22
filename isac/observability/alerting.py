"""告警系统 (I5, ARCHITECTURE.md 3.9)。

规则驱动告警: 当指标满足条件时触发告警, 推送到 Webhook (复用 G3 WebhookManager)。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.control.webhooks import WebhookManager
    from isac.observability.metrics import MetricsCollector

logger = get_logger(__name__)


class AlertLevel(StrEnum):
    """告警级别。"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AlertRule:
    """告警规则: 检查指标满足条件时触发。

    condition: callable(metrics: MetricsCollector) -> bool
    event_name: 触发的 Webhook 事件名 (如 alert.llm_error_rate_high)
    cooldown_seconds: 同一规则两次告警最小间隔, 避免告警风暴
    """

    name: str
    description: str
    level: AlertLevel
    condition: Callable[[MetricsCollector], bool]
    event_name: str
    cooldown_seconds: int = 300
    _last_fired: float = field(default=0.0, repr=False)


class AlertManager:
    """告警管理器: 周期性检查规则, 触发的告警推送到 WebhookManager。"""

    def __init__(
        self,
        metrics: MetricsCollector,
        webhook_manager: WebhookManager | None = None,
        *,
        check_interval: int = 30,
    ) -> None:
        self._metrics = metrics
        self._webhook = webhook_manager
        self._rules: list[AlertRule] = []
        self._check_interval = max(5, check_interval)
        self._task: asyncio.Task[Any] | None = None
        self._running = False

    def add_rule(self, rule: AlertRule) -> None:
        """添加告警规则。"""
        self._rules.append(rule)
        logger.info("告警规则已添加", rule=rule.name, level=rule.level.value)

    def list_rules(self) -> list[dict[str, Any]]:
        """列出所有规则 (供 API 查询)。"""
        return [
            {
                "name": r.name,
                "description": r.description,
                "level": r.level.value,
                "event_name": r.event_name,
                "cooldown_seconds": r.cooldown_seconds,
            }
            for r in self._rules
        ]

    async def check_once(self) -> list[dict[str, Any]]:
        """执行一次规则检查, 返回触发的告警列表。"""
        import time

        fired: list[dict[str, Any]] = []
        now = time.time()
        for rule in self._rules:
            try:
                if not rule.condition(self._metrics):
                    continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("告警规则检查异常", rule=rule.name, error=str(exc))
                continue
            if now - rule._last_fired < rule.cooldown_seconds:
                continue
            rule._last_fired = now
            alert = {
                "rule": rule.name,
                "level": rule.level.value,
                "description": rule.description,
                "event": rule.event_name,
                "timestamp": now,
                "metrics_snapshot": self._metrics.snapshot(),
            }
            fired.append(alert)
            logger.warning(
                "告警触发",
                rule=rule.name,
                level=rule.level.value,
                event_name=rule.event_name,
            )
            # 推送到 Webhook (如果有)
            if self._webhook is not None:
                try:
                    await self._webhook.dispatch(
                        rule.event_name,
                        {"alert": alert},
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("告警 Webhook 推送失败", rule=rule.name, error=str(exc))
        return fired

    async def start(self) -> None:
        """启动周期性检查。"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info("告警管理器已启动", interval=self._check_interval)

    async def stop(self) -> None:
        """停止周期性检查。"""
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _check_loop(self) -> None:
        while self._running:
            try:
                await self.check_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("告警检查循环异常", error=str(exc))
            await asyncio.sleep(self._check_interval)


def get_default_alert_rules() -> list[AlertRule]:
    """返回默认告警规则集 (基于默认指标)。"""

    def _llm_error_rate(metrics: MetricsCollector) -> bool:
        total = metrics.counter("isac_llm_calls_total").value()
        errors = metrics.counter("isac_llm_errors_total").value()
        if total < 10:
            return False
        return errors / total > 0.1  # 错误率 > 10%

    def _message_drop_rate(metrics: MetricsCollector) -> bool:
        received = metrics.counter("isac_messages_received_total").value()
        dropped = metrics.counter("isac_messages_dropped_total").value()
        if received < 50:
            return False
        return dropped / received > 0.3  # 丢弃率 > 30%

    def _no_active_agents(metrics: MetricsCollector) -> bool:
        return metrics.gauge("isac_agents_active").value() == 0

    return [
        AlertRule(
            name="llm_error_rate_high",
            description="LLM 错误率超过 10% (至少 10 次调用)",
            level=AlertLevel.ERROR,
            condition=_llm_error_rate,
            event_name="alert.llm_error_rate_high",
            cooldown_seconds=600,
        ),
        AlertRule(
            name="message_drop_rate_high",
            description="消息丢弃率超过 30% (至少 50 条消息)",
            level=AlertLevel.WARNING,
            condition=_message_drop_rate,
            event_name="alert.message_drop_rate_high",
            cooldown_seconds=300,
        ),
        AlertRule(
            name="no_active_agents",
            description="无活跃 Agent (可能导致消息无法处理)",
            level=AlertLevel.CRITICAL,
            condition=_no_active_agents,
            event_name="alert.no_active_agents",
            cooldown_seconds=120,
        ),
    ]
