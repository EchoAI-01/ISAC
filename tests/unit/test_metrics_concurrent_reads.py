"""指标读取并发安全测试 (CR3 复核)。

此前 Counter/Gauge/Histogram 的 value()/to_prometheus() 与 MetricsCollector.snapshot()/
to_prometheus() 在锁外遍历内部 dict, 高基数 label 写入同时 /metrics 抓取会触发
dict resize → RuntimeError: dictionary changed size during iteration。
"""

from __future__ import annotations

import threading

from isac.observability.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsCollector,
)


def test_counter_concurrent_inc_and_to_prometheus_does_not_raise() -> None:
    counter = Counter("test_counter_concurrent", "concurrent counter")
    stop = threading.Event()
    errors: list[Exception] = []

    def writer() -> None:
        i = 0
        while not stop.is_set():
            counter.inc(1.0, label=f"k{i % 50}")
            i += 1

    def reader() -> None:
        while not stop.is_set():
            try:
                counter.to_prometheus()
                counter.value(label="k0")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

    threads = [threading.Thread(target=writer) for _ in range(4)] + [
        threading.Thread(target=reader) for _ in range(4)
    ]
    for t in threads:
        t.start()
    stop.set()
    for t in threads:
        t.join(timeout=5.0)

    assert errors == []


def test_gauge_concurrent_set_and_snapshot_does_not_raise() -> None:
    gauge = Gauge("test_gauge_concurrent", "concurrent gauge")
    stop = threading.Event()
    errors: list[Exception] = []

    def writer() -> None:
        i = 0
        while not stop.is_set():
            gauge.set(float(i), label=f"g{i % 30}")
            i += 1

    def reader() -> None:
        while not stop.is_set():
            try:
                gauge.to_prometheus()
                gauge.value(label="g0")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

    threads = [threading.Thread(target=writer) for _ in range(4)] + [
        threading.Thread(target=reader) for _ in range(4)
    ]
    for t in threads:
        t.start()
    stop.set()
    for t in threads:
        t.join(timeout=5.0)

    assert errors == []


def test_histogram_concurrent_observe_and_to_prometheus_does_not_raise() -> None:
    histogram = Histogram("test_histogram_concurrent", "concurrent histogram")
    stop = threading.Event()
    errors: list[Exception] = []

    def writer() -> None:
        i = 0
        while not stop.is_set():
            histogram.observe(float(i % 100) / 10.0)
            i += 1

    def reader() -> None:
        while not stop.is_set():
            try:
                histogram.to_prometheus()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

    threads = [threading.Thread(target=writer) for _ in range(4)] + [
        threading.Thread(target=reader) for _ in range(4)
    ]
    for t in threads:
        t.start()
    stop.set()
    for t in threads:
        t.join(timeout=5.0)

    assert errors == []


def test_metrics_collector_concurrent_snapshot_and_to_prometheus() -> None:
    collector = MetricsCollector()
    counter = collector.counter("isac_concurrent_counter_total", "concurrent")
    gauge = collector.gauge("isac_concurrent_gauge", "concurrent")
    histogram = collector.histogram("isac_concurrent_latency_seconds", "concurrent")
    stop = threading.Event()
    errors: list[Exception] = []

    def writer() -> None:
        i = 0
        while not stop.is_set():
            counter.inc(1.0, label=f"c{i % 40}")
            gauge.set(float(i), label=f"g{i % 20}")
            histogram.observe(float(i % 50) / 10.0)
            i += 1

    def reader() -> None:
        while not stop.is_set():
            try:
                collector.snapshot()
                collector.to_prometheus()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

    threads = [threading.Thread(target=writer) for _ in range(4)] + [
        threading.Thread(target=reader) for _ in range(4)
    ]
    for t in threads:
        t.start()
    stop.set()
    for t in threads:
        t.join(timeout=5.0)

    assert errors == []
