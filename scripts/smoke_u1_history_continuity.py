#!/usr/bin/env python3
"""U1 真机冒烟: "隔天回到同一群聊仍保持上下文" 留档载体。

验收 (DEVELOPMENT_PLAN §四 U1): 事件溯源会话内核让会话历史跨进程重启存续 ——
第一天启动实例 A 与某会话对话 → SIGTERM 停止 → 第二天同一 data 目录启动实例 B,
回到同一会话继续对话, 事件流 (session_events.db) 中该会话分区同时含有两天的
message.user / turn.completed 事件, 且第二天事件 seq 接续第一天 —— 第二回合的
滑动窗口历史即从该事件流派生 (派生链路另由 tests/integration/test_u1_event_sourcing_flow.py
在进程内逐环节断言)。

用法:
    uv run python scripts/smoke_u1_history_continuity.py

退出码 0 = 冒烟通过; 非 0 = 失败 (打印诊断)。
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ISAC_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
WAIT_START_SECONDS = 6.0
WAIT_REPLY_SECONDS = 8.0

DAY1_MSG = "昨天我们聊了项目进度"
DAY2_MSG = "今天接着昨天的聊"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http_json(url: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
        return exc.code, {}


def _wait_webchat_ready(proc: subprocess.Popen, port: int) -> bool:  # type: ignore[type-arg]
    deadline = time.time() + WAIT_START_SECONDS
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            code, _ = _http_json(f"http://127.0.0.1:{port}/webchat/poll?session_id=probe")
            if code in (200, 401):
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def _poll_replies(port: int, session_id: str) -> list:
    deadline = time.time() + WAIT_REPLY_SECONDS
    while time.time() < deadline:
        code, resp = _http_json(f"http://127.0.0.1:{port}/webchat/poll?session_id={session_id}")
        if code == 200 and resp.get("replies"):
            return resp["replies"]
        time.sleep(0.3)
    return []


def _start_isac(work_dir: Path, port: int) -> subprocess.Popen:  # type: ignore[type-arg]
    """启动 python -m isac (cwd=work_dir, DATA_DIR 相对解析为 work_dir/data)。"""
    config = {
        "config_version": "1.0.0",
        "channels": {"webchat": {"enabled": True, "bind_host": "127.0.0.1", "bind_port": port}},
        "llm": {"provider": "openai", "api_key": "sk-your-key", "model": "gpt-4o-mini"},
        "session": {"history": {"enabled": True, "window_turns": 10}},
    }
    data_dir = work_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "config.jsonc").write_text(json.dumps(config), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ISAC_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.Popen(
        [PYTHON, "-m", "isac"],
        cwd=str(work_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _stop_and_dump(proc: subprocess.Popen) -> str:
    """SIGTERM 停止并取回输出 (先停进程再读管道, 避免对活进程 read 阻塞)。"""
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
    try:
        out, _ = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate(timeout=5)
    return out or ""


def _one_day(work_dir: Path, content: str, day_label: str) -> int:
    """启动一个实例, 向同一会话发一条消息并等回复; 返回退出码 (0=成功)。"""
    port = _free_port()
    proc = _start_isac(work_dir, port)
    try:
        if not _wait_webchat_ready(proc, port):
            out = _stop_and_dump(proc)
            print(f"[smoke] FAIL({day_label}): webchat 未就绪\n{out[-1500:]}")
            return 2
        code, _ = _http_json(
            f"http://127.0.0.1:{port}/webchat/send",
            method="POST",
            body={"session_id": "s1", "user_id": "u1", "content": content},
        )
        if code != 200:
            print(f"[smoke] FAIL({day_label}): /webchat/send 返回 {code}")
            return 3
        replies = _poll_replies(port, "s1")
        if not replies or not str(replies[0].get("content", "")).strip():
            print(f"[smoke] FAIL({day_label}): {WAIT_REPLY_SECONDS}s 内未收到非空回复")
            return 4
        print(f"[smoke] {day_label} OK: 发送 '{content}' -> 回复 '{str(replies[0]['content'])[:60]}'")
        return 0
    finally:
        _stop_and_dump(proc)


def _verify_event_continuity(work_dir: Path) -> int:
    """校验事件流跨重启连续: 同一 session_key 分区含两天的 user 消息, seq 接续。"""
    events_db = work_dir / "data" / "gateway" / "session_events.db"
    if not events_db.exists():
        print("[smoke] FAIL: session_events.db 不存在 (事件表未落盘)")
        return 5
    conn = sqlite3.connect(events_db)
    try:
        rows = conn.execute(
            "SELECT session_key, seq, event_type, payload FROM session_events ORDER BY session_key, seq"
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        print("[smoke] FAIL: 事件表为空")
        return 6

    by_key: dict[str, list] = {}
    for session_key, seq, event_type, payload in rows:
        by_key.setdefault(session_key, []).append((seq, event_type, payload))
    for session_key, events in by_key.items():
        contents = [json.loads(p).get("content", "") for _, t, p in events if t == "message.user"]
        has_day1 = any(DAY1_MSG in c for c in contents)
        has_day2 = any(DAY2_MSG in c for c in contents)
        if has_day1 and has_day2:
            seq_day1 = next(
                s for s, t, p in events
                if t == "message.user" and DAY1_MSG in json.loads(p).get("content", "")
            )
            seq_day2 = next(
                s for s, t, p in events
                if t == "message.user" and DAY2_MSG in json.loads(p).get("content", "")
            )
            turns = sum(1 for _, t, _p in events if t == "turn.completed")
            if seq_day2 > seq_day1 and turns >= 2:
                print(
                    f"[smoke] 事件流连续性 OK: session_key={session_key}, "
                    f"day1 seq={seq_day1} → day2 seq={seq_day2}, turn.completed x{turns}"
                )
                return 0
            print(f"[smoke] FAIL: 事件 seq 未接续 (day1={seq_day1}, day2={seq_day2}, turns={turns})")
            return 7
    print("[smoke] FAIL: 未找到同时含两天消息的会话分区")
    return 8


def main() -> int:
    work_dir = Path(tempfile.mkdtemp(prefix="isac_u1_smoke_"))
    print(f"[smoke] U1 历史连续性冒烟, work_dir={work_dir}", flush=True)
    try:
        rc = _one_day(work_dir, DAY1_MSG, "第一天")
        if rc != 0:
            return rc
        rc = _one_day(work_dir, DAY2_MSG, "第二天(重启后)")
        if rc != 0:
            return rc
        rc = _verify_event_continuity(work_dir)
        if rc != 0:
            return rc
        print("[smoke] PASS: 隔天回到同一会话, 事件流连续, 历史窗口可从事件派生", flush=True)
        return 0
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
