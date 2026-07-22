"""指标采集 (I5, ARCHITECTURE.md 3.9)。

提供 Counter / Gauge / Histogram 三种指标类型, 内存存储。
可通过 /metrics 端点暴露 Prometheus 文本格式 (生产可接入 Prometheus + Grafana)。

指标命名遵循 Prometheus 约定: isac_<subsystem>_<name>_<unit>
"""

from __future__ import annotations

import threading
from typing import Any

from isac.utils.logger import get_logger

logger = get_logger(__name__)


class Counter:
    """单调递增计数器 (如消息总数、错误次数)。"""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._value: float = 0.0
        self._labels: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def inc(self, value: float = 1.0, **labels: Any) -> None:
        """增加值。labels 区分不同维度 (如 platform/agent_id)。"""
        if value < 0:
            raise ValueError("Counter 只能递增")
        with self._lock:
            if not labels:
                self._value += value
            else:
                key = tuple(sorted(labels.items()))
                self._labels[key] = self._labels.get(key, 0.0) + value

    def value(self, **labels: Any) -> float:
        if not labels:
            return self._value
        key = tuple(sorted(labels.items()))
        return self._labels.get(key, 0.0)

    def to_prometheus(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.description}", f"# TYPE {self.name} counter"]
        if self._value > 0:
            lines.append(f"{self.name} {self._value}")
        for key, val in sorted(self._labels.items()):
            label_str = ",".join(f'{k}="{v}"' for k, v in key)
            lines.append(f"{self.name}{{{label_str}}} {val}")
        return lines


class Gauge:
    """瞬时值 (如活跃 Agent 数、内存占用)。"""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._value: float = 0.0
        self._labels: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def set(self, value: float, **labels: Any) -> None:
        with self._lock:
            if not labels:
                self._value = value
            else:
                key = tuple(sorted(labels.items()))
                self._labels[key] = value

    def inc(self, value: float = 1.0, **labels: Any) -> None:
        with self._lock:
            if not labels:
                self._value += value
            else:
                key = tuple(sorted(labels.items()))
                self._labels[key] = self._labels.get(key, 0.0) + value

    def dec(self, value: float = 1.0, **labels: Any) -> None:
        self.inc(-value, **labels)

    def value(self, **labels: Any) -> float:
        if not labels:
            return self._value
        key = tuple(sorted(labels.items()))
        return self._labels.get(key, 0.0)

    def to_prometheus(self) -> list[str]:
        lines = [f"# HELP {self.name} {self.description}", f"# TYPE {self.name} gauge"]
        if self._labels:
            for key, val in sorted(self._labels.items()):
                label_str = ",".join(f'{k}="{v}"' for k, v in key)
                lines.append(f"{self.name}{{{label_str}}} {val}")
        else:
            lines.append(f"{self.name} {self._value}")
        return lines


class Histogram:
    """直方图 (如 LLM 延迟分布)。默认桶: 0.005/0.01/0.025/0.05/0.1/0.25/0.5/1/2.5/5/10。"""

    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

    def __init__(self, name: str, description: str = "", buckets: tuple | None = None):
        self.name = name
        self.description = description
        self.buckets = buckets or self.DEFAULT_BUCKETS
        self._counts: list[int] = [0] * len(self.buckets)
        self._sum: float = 0.0
        self._count: int = 0
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        """记录一次观察值 (秒)。"""
        with self._lock:
            self._sum += value
            self._count += 1
            for i, bound in enumerate(self.buckets):
                if value <= bound:
                    self._counts[i] += 1

    def to_prometheus(self) -> list[str]:
        lines = [
            f"# HELP {self.name} {self.description}",
            f"# TYPE {self.name} histogram",
        ]
        cumulative = 0
        for i, bound in enumerate(self.buckets):
            cumulative = self._counts[i]
            lines.append(f'{self.name}_bucket{{le="{bound}"}} {cumulative}')
        lines.append(f'{self.name}_bucket{{le="+Inf"}} {self._count}')
        lines.append(f"{self.name}_sum {self._sum}")
        lines.append(f"{self.name}_count {self._count}")
        return lines


class MetricsCollector:
    """指标采集器: 集中管理所有 Counter/Gauge/Histogram。"""

    def __init__(self) -> None:
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}
        self._lock = threading.Lock()

    def counter(self, name: str, description: str = "") -> Counter:
        with self._lock:
            if name not in self._counters:
                self._counters[name] = Counter(name, description)
            return self._counters[name]

    def gauge(self, name: str, description: str = "") -> Gauge:
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = Gauge(name, description)
            return self._gauges[name]

    def histogram(self, name: str, description: str = "", buckets: tuple | None = None) -> Histogram:
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = Histogram(name, description, buckets)
            return self._histograms[name]

    def to_prometheus(self) -> str:
        """导出 Prometheus 文本格式。"""
        lines: list[str] = []
        for counter in list(self._counters.values()):
            lines.extend(counter.to_prometheus())
        for gauge in list(self._gauges.values()):
            lines.extend(gauge.to_prometheus())
        for histogram in list(self._histograms.values()):
            lines.extend(histogram.to_prometheus())
        return "\n".join(lines) + "\n" if lines else ""

    def snapshot(self) -> dict[str, Any]:
        """返回 JSON 友好的指标快照 (供 API 查询)。"""
        return {
            "counters": {name: c.value() for name, c in self._counters.items()},
            "gauges": {name: g.value() for name, g in self._gauges.items()},
            "histograms": {
                name: {"count": h._count, "sum": h._sum}
                for name, h in self._histograms.items()
            },
        }


# ── 全局默认指标 (启动时注册) ─────────────────────────────────

def get_default_metrics() -> MetricsCollector:
    """构造带预定义指标的 MetricsCollector。"""
    collector = MetricsCollector()
    # 消息指标
    collector.counter("isac_messages_received_total", "接收的消息总数")
    collector.counter("isac_messages_processed_total", "处理完成的消息总数")
    collector.counter("isac_messages_dropped_total", "被丢弃的消息数 (路由无匹配/门控拒绝)")
    collector.counter("isac_messages_failed_total", "处理失败的消息数")
    # Agent 指标
    collector.gauge("isac_agents_active", "活跃 Agent 数 (status=running)")
    collector.counter("isac_agent_creates_total", "Agent 创建次数")
    collector.counter("isac_agent_starts_total", "Agent 启动次数")
    collector.counter("isac_agent_stops_total", "Agent 停止次数")
    # LLM 指标
    collector.counter("isac_llm_calls_total", "LLM 调用次数")
    collector.counter("isac_llm_errors_total", "LLM 调用失败次数")
    collector.counter("isac_llm_tokens_total", "LLM Token 消耗总量")
    collector.histogram("isac_llm_latency_seconds", "LLM 调用延迟 (秒)")
    # 工具指标
    collector.counter("isac_tool_calls_total", "工具调用次数")
    collector.counter("isac_tool_errors_total", "工具调用失败次数")
    # 记忆指标
    collector.counter("isac_memory_searches_total", "记忆检索次数")
    collector.counter("isac_memory_stores_total", "记忆存储次数")
    collector.histogram("isac_memory_search_latency_seconds", "记忆检索延迟 (秒)")
    # 控制面指标
    collector.counter("isac_control_requests_total", "控制面 API 请求总数")
    collector.counter("isac_control_errors_total", "控制面 API 错误响应数")
    collector.histogram("isac_control_request_latency_seconds", "控制面 API 请求延迟 (秒)")
    return collector
