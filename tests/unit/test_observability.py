"""I5 监控告警测试 - 指标采集 + 告警规则 + Prometheus 输出。"""

from __future__ import annotations

import pytest

from isac.observability import (
    AlertLevel,
    AlertManager,
    AlertRule,
    MetricsCollector,
    get_default_metrics,
)


class TestCounter:
    def test_inc_increments_value(self) -> None:
        c = MetricsCollector().counter("test_counter", "测试")
        c.inc()
        c.inc(2)
        assert c.value() == 3.0

    def test_inc_with_labels(self) -> None:
        c = MetricsCollector().counter("test_counter", "测试")
        c.inc(agent_id="a")
        c.inc(agent_id="b")
        c.inc(agent_id="a")
        assert c.value(agent_id="a") == 2.0
        assert c.value(agent_id="b") == 1.0

    def test_negative_value_raises(self) -> None:
        c = MetricsCollector().counter("test")
        with pytest.raises(ValueError):
            c.inc(-1)


class TestGauge:
    def test_set_overwrites_value(self) -> None:
        g = MetricsCollector().gauge("test_gauge")
        g.set(10)
        assert g.value() == 10
        g.set(20)
        assert g.value() == 20

    def test_inc_dec(self) -> None:
        g = MetricsCollector().gauge("test_gauge")
        g.set(0)
        g.inc()
        g.inc(2)
        g.dec()
        assert g.value() == 2.0


class TestHistogram:
    def test_observe_updates_count_and_sum(self) -> None:
        h = MetricsCollector().histogram("test_hist")
        h.observe(0.1)
        h.observe(0.5)
        h.observe(2.0)
        assert h._count == 3
        assert abs(h._sum - 2.6) < 1e-9

    def test_buckets_cumulative(self) -> None:
        h = MetricsCollector().histogram("test_hist", buckets=(0.1, 1.0, 10.0))
        h.observe(0.05)  # fits 0.1
        h.observe(0.5)  # fits 1.0 but not 0.1
        h.observe(5)  # fits 10.0 but not 1.0
        # buckets 累积: le=0.1 应包含 1 个, le=1.0 包含 2 个, le=10.0 包含 3 个
        assert h._counts == [1, 2, 3]


class TestMetricsSnapshot:
    def test_snapshot_returns_json_friendly_dict(self) -> None:
        collector = get_default_metrics()
        collector.counter("isac_messages_received_total").inc(5)
        collector.gauge("isac_agents_active").set(3)
        snapshot = collector.snapshot()
        assert snapshot["counters"]["isac_messages_received_total"] == 5.0
        assert snapshot["gauges"]["isac_agents_active"] == 3.0

    def test_to_prometheus_includes_help_and_type(self) -> None:
        collector = MetricsCollector()
        c = collector.counter("test_counter", "描述")
        c.inc(5)
        prom = collector.to_prometheus()
        assert "# HELP test_counter 描述" in prom
        assert "# TYPE test_counter counter" in prom
        assert "test_counter 5.0" in prom


class TestAlertRule:
    def test_condition_true_triggers_alert(self) -> None:
        collector = get_default_metrics()
        # 制造条件: LLM 错误率 > 10%
        for _ in range(20):
            collector.counter("isac_llm_calls_total").inc()
        for _ in range(5):
            collector.counter("isac_llm_errors_total").inc()  # 25% 错误率

        from isac.observability.alerting import get_default_alert_rules

        rules = get_default_alert_rules()
        llm_rule = next(r for r in rules if r.name == "llm_error_rate_high")
        assert llm_rule.condition(collector) is True

    def test_condition_false_does_not_trigger(self) -> None:
        collector = get_default_metrics()
        from isac.observability.alerting import get_default_alert_rules

        rules = get_default_alert_rules()
        llm_rule = next(r for r in rules if r.name == "llm_error_rate_high")
        # 未达 10 次调用阈值
        assert llm_rule.condition(collector) is False


class TestAlertManager:
    @pytest.mark.asyncio
    async def test_check_once_returns_triggered_alerts(self) -> None:
        collector = get_default_metrics()
        # 制造无活跃 Agent 告警
        collector.gauge("isac_agents_active").set(0)
        manager = AlertManager(collector)
        manager.add_rule(
            AlertRule(
                name="no_agents",
                description="无活跃 Agent",
                level=AlertLevel.CRITICAL,
                condition=lambda m: m.gauge("isac_agents_active").value() == 0,
                event_name="alert.no_agents",
                cooldown_seconds=0,
            )
        )
        fired = await manager.check_once()
        assert len(fired) == 1
        assert fired[0]["rule"] == "no_agents"
        assert fired[0]["level"] == "critical"

    @pytest.mark.asyncio
    async def test_cooldown_prevents_repeated_alerts(self) -> None:
        collector = get_default_metrics()
        collector.gauge("isac_agents_active").set(0)
        manager = AlertManager(collector)
        manager.add_rule(
            AlertRule(
                name="no_agents",
                description="无活跃 Agent",
                level=AlertLevel.CRITICAL,
                condition=lambda m: m.gauge("isac_agents_active").value() == 0,
                event_name="alert.no_agents",
                cooldown_seconds=60,  # 1 分钟冷却
            )
        )
        fired1 = await manager.check_once()
        assert len(fired1) == 1
        # 立即再检查, 不应再次触发
        fired2 = await manager.check_once()
        assert len(fired2) == 0

    @pytest.mark.asyncio
    async def test_list_rules_returns_metadata(self) -> None:
        collector = get_default_metrics()
        manager = AlertManager(collector)
        manager.add_rule(
            AlertRule(
                name="test_rule",
                description="测试",
                level=AlertLevel.WARNING,
                condition=lambda m: False,
                event_name="alert.test",
            )
        )
        rules = manager.list_rules()
        assert len(rules) == 1
        assert rules[0]["name"] == "test_rule"
        assert rules[0]["level"] == "warning"
