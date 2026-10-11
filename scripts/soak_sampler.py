#!/usr/bin/env python3
"""N2-4 24h soak 采样工具: 负载发生器 + 进程资源采样器。

设计 (DEVELOPMENT_PLAN §三之三 N2-4 / §三之四 Phase 1 维度 8):

- **负载发生器**: 向运行中 ISAC 的 WebChat HTTP API (POST /webchat/send) 按可配
  节奏注入消息 (默认 3 会话 × 每 20s 一条轮换话题), 模拟真实对话负载;
- **资源采样器**: 每个采样周期记录宿主进程 RSS/线程数/FD 数 + `/health` 聚合
  (agents/uptime) + 会话事件表行数 (无界增长检测), 追加 JSONL;
- **泄漏判定**: 结束时对比首/末样本 —— RSS 增幅、FD 增幅、线程增幅超阈值即
  EXIT 非 0 (输出告警行), 供 release_checklist §六 直接消费。

安全: 只打 loopback (WebChat 默认 127.0.0.1:8090); 不落任何凭据; 输出目录
evidence/<date>-soak/ (scripts/new_evidence_dir.py 规范)。

用法 (先在另一终端跑起 ISAC 并配好真实 LLM key):
    # 24h 标准跑法
    uv run python scripts/soak_sampler.py --duration 24h --out evidence/2026-xx-xx-soak
    # 快速验证 (2 分钟, 无真实 LLM 也可跑通采集链路)
    uv run python scripts/soak_sampler.py --duration 2m --out /tmp/soak-quick

退出码: 0 = 采样完成且无泄漏告警; 1 = 采样完成但有泄漏告警; 2 = 采样器自身故障。
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ── 采样阈值 (泄漏判定; RSS 用 30% 防弹性波动, FD/线程用绝对增量) ─────
RSS_GROWTH_RATIO_LIMIT = 1.30      # 末样本 RSS ≤ 首样本 × 1.30
FD_GROWTH_ABS_LIMIT = 200          # FD 增量 ≤ 200 (连接/文件泄漏敏感)
THREAD_GROWTH_ABS_LIMIT = 50       # 线程增量 ≤ 50
SAMPLE_INTERVAL_SECONDS = 60.0     # 采样周期 (负载节奏独立于采样)

# 负载话术池 (轮换, 模拟多话题对话; 中文短句触发记忆写入回路)
_TOPICS = [
    "随便聊聊, 今天过得怎么样?",
    "帮我记住一件事: 我下周三要体检。",
    "还记得我上次说的事吗?",
    "推荐一部适合周末看的电影。",
    "我最近在学 Rust, 有什么建议?",
    "总结一下我们聊过的内容。",
]


def parse_duration(raw: str) -> float:
    """解析 "24h" / "30m" / "90s" / "3600" (秒) 形式的时长。"""
    raw = raw.strip().lower()
    units = {"h": 3600.0, "m": 60.0, "s": 1.0}
    if raw and raw[-1] in units:
        return float(raw[:-1]) * units[raw[-1]]
    return float(raw)


def _http_json(method: str, url: str, body: dict | None = None, timeout: float = 10.0):
    """小工具: urllib JSON 请求 (不引依赖); 返回 (status, parsed_or_text)。"""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(text)
            except Exception:  # noqa: BLE001
                return resp.status, text
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return -1, str(exc)


def _proc_stat(pid: int) -> dict:
    """采样 ISAC 进程资源 (RSS KB / 线程数 / FD 数); 进程不在返回空。"""
    out: dict = {"pid": pid}
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as fp:
            for line in fp:
                if line.startswith("VmRSS:"):
                    out["rss_kb"] = int(line.split()[1])
                elif line.startswith("Threads:"):
                    out["threads"] = int(line.split()[1])
        out["fds"] = len(os.listdir(f"/proc/{pid}/fd"))
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        # macOS 无 /proc —— 经 ps 降级采样 RSS (FD/线程不可得, 记 None)
        try:
            import subprocess

            res = subprocess.run(
                ["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, timeout=5
            )
            rss = int(res.stdout.strip().split()[0]) if res.stdout.strip() else None
            out["rss_kb"] = rss
            out["threads"] = None
            out["fds"] = None
        except Exception:  # noqa: BLE001
            out.update({"rss_kb": None, "threads": None, "fds": None})
    return out


def _find_isac_pid() -> int | None:
    """找 ISAC 宿主进程 (python -m isac / uv run python -m isac); 找不到 None。"""
    import subprocess

    try:
        res = subprocess.run(
            ["ps", "-eo", "pid,args"], capture_output=True, text=True, timeout=10
        )
    except Exception:  # noqa: BLE001
        return None
    for line in res.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) < 2:
            continue
        pid_s, args = parts
        # 匹配承载 isac 主模块的进程 (python -m isac); 排除自身与 grep
        if ("-m isac" in args or "python -m isac" in args) and "soak_sampler" not in args:
            try:
                return int(pid_s)
            except ValueError:
                continue
    return None


def _session_event_count(data_dir: Path) -> int | None:
    """会话事件表行数 (无界增长检测); 无库返回 None (只读打开, 不写)。"""
    db = data_dir / "gateway" / "session_events.db"
    if not db.exists():
        return None
    try:
        import sqlite3

        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        try:
            row = con.execute("SELECT COUNT(*) FROM session_events").fetchone()
            return int(row[0]) if row else 0
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="ISAC 24h soak 采样器 (N2-4)")
    parser.add_argument("--duration", default="24h", help="总时长 (24h/30m/90s/秒数)")
    parser.add_argument("--webchat-url", default="http://127.0.0.1:8090", help="WebChat 基址")
    parser.add_argument("--control-url", default="http://127.0.0.1:8765", help="控制面基址 (/health)")
    parser.add_argument("--data-dir", default="data", help="ISAC data 目录 (事件表采样)")
    parser.add_argument("--out", default="evidence/soak", help="输出目录 (samples.jsonl + summary.json)")
    parser.add_argument("--sessions", type=int, default=3, help="并发模拟会话数")
    parser.add_argument("--msg-interval", type=float, default=20.0, help="每会话发消息间隔秒数")
    parser.add_argument("--pid", type=int, default=0, help="显式指定 ISAC 进程 PID (0=自动发现)")
    args = parser.parse_args()

    duration = parse_duration(args.duration)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    samples_path = out_dir / "samples.jsonl"
    data_dir = Path(args.data_dir)

    pid = args.pid or _find_isac_pid()
    if pid is None:
        print("[soak] ⚠️ 未发现 ISAC 进程 (python -m isac) —— 仅采样 /health 与事件表, 无进程资源项", file=sys.stderr)

    started = time.time()
    print(f"[soak] 开始: duration={args.duration} pid={pid} out={out_dir}")
    stopped = False

    def _stop(signum, _frame):  # noqa: ANN001
        nonlocal stopped
        stopped = True
        print(f"[soak] 收到信号 {signum}, 优雅收尾…", file=sys.stderr)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    first: dict | None = None
    last: dict | None = None
    sent = replies = errors = 0
    msg_idx = 0

    while not stopped and (time.time() - started) < duration:
        cycle_start = time.time()
        # ── 负载: 轮会话发消息 (不阻塞采样节奏) ──
        sent, errors = _send_round(args, msg_idx, sent, errors)
        msg_idx += 1

        # ── 采样 ──
        sample = _take_sample(args, pid, data_dir, sent, errors)
        with samples_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(sample, ensure_ascii=False) + "\n")
        if first is None:
            first = sample
        last = sample

        # 等到下一采样点, 但不超过剩余时长 (短跑模式下最后一轮不等满周期)
        elapsed = time.time() - cycle_start
        remaining = duration - (time.time() - started)
        wait = min(SAMPLE_INTERVAL_SECONDS - elapsed, remaining)
        if wait > 0 and not stopped:
            time.sleep(wait)

    # ── 收尾: 回复统计 (轮询各会话一次) + 泄漏判定 + summary ──
    for s in range(args.sessions):
        status, payload = _http_json(
            "GET", f"{args.webchat_url}/webchat/poll?session_id=soak-s{s}"
        )
        if status == 200 and isinstance(payload, dict) and payload.get("replies"):
            replies += len(payload["replies"])
    alarms = _leak_alarms(first, last)
    summary = {
        "duration_seconds": round(time.time() - started, 1),
        "pid": pid,
        "messages_sent": sent,
        "send_errors": errors,
        "replies_polled_final": replies,
        "samples": (out_dir / "samples.jsonl").stat().st_size,
        "first": first,
        "last": last,
        "alarms": alarms,
        "verdict": "PASS" if not alarms else "LEAK_SUSPECTED",
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[soak] 完成: sent={sent} errors={errors} verdict={summary['verdict']}")
    for alarm in alarms:
        print(f"[soak] ⚠️ {alarm}", file=sys.stderr)
    return 0 if not alarms else 1


def _take_sample(args: argparse.Namespace, pid: int | None, data_dir: Path, sent: int, errors: int) -> dict:
    """单次采样: 进程资源 + /health 聚合 + 事件表行数 + 负载计数快照。"""
    started_t = time.time()
    sample: dict = {"t": started_t, "ts": started_t}
    if pid:
        sample.update(_proc_stat(pid))
    hs, health = _http_json("GET", f"{args.control_url}/health")
    sample["health_status"] = hs
    if isinstance(health, dict):
        sample["agents_total"] = (health.get("agents") or {}).get("total")
        sample["uptime_seconds"] = health.get("uptime_seconds")
    sample["session_events"] = _session_event_count(data_dir)
    sample["sent"] = sent
    sample["send_errors"] = errors
    return sample


def _send_round(args: argparse.Namespace, round_idx: int, sent: int, errors: int) -> tuple[int, int]:
    """一轮负载: 各会话发一条轮换话题消息, 返回累计 (sent, errors)。"""
    for s in range(args.sessions):
        topic = _TOPICS[(round_idx + s) % len(_TOPICS)]
        status, _ = _http_json(
            "POST",
            f"{args.webchat_url}/webchat/send",
            {"session_id": f"soak-s{s}", "user_id": f"soak-user-{s}", "content": topic},
        )
        if status in (200, 201, 202):
            sent += 1
        else:
            errors += 1
    return sent, errors


def _leak_alarms(first: dict | None, last: dict | None) -> list[str]:
    """首末样本对比的泄漏判定 (RSS 比例 / FD / 线程绝对增量)。"""
    alarms: list[str] = []
    if not (first and last):
        return alarms
    if first.get("rss_kb") and last.get("rss_kb"):
        ratio = last["rss_kb"] / max(1, first["rss_kb"])
        if ratio > RSS_GROWTH_RATIO_LIMIT:
            alarms.append(f"RSS 增长 {ratio:.2f}x 超阈值 {RSS_GROWTH_RATIO_LIMIT}x")
    if first.get("fds") is not None and last.get("fds") is not None:
        growth = last["fds"] - first["fds"]
        if growth > FD_GROWTH_ABS_LIMIT:
            alarms.append(f"FD 增量 {growth} 超阈值 {FD_GROWTH_ABS_LIMIT}")
    if first.get("threads") is not None and last.get("threads") is not None:
        growth = last["threads"] - first["threads"]
        if growth > THREAD_GROWTH_ABS_LIMIT:
            alarms.append(f"线程增量 {growth} 超阈值 {THREAD_GROWTH_ABS_LIMIT}")
    return alarms


if __name__ == "__main__":
    raise SystemExit(main())
