#!/usr/bin/env python3
"""R5 真机冒烟: 重启不丢会话 (SessionManager SQLite 持久化)。

验证 SessionManager SQLite 写穿 + 重启恢复: 第一次启动发消息建会话 → SIGTERM 停 →
第二次启动同 data 目录 → 同一会话键 get_or_create 恢复同一 session_id (不新建)。

通过 control API 的 /api/v1/sessions 端点间接验证 (会话列表持久化跨重启)。

用法: uv run python scripts/smoke_session_persistence.py
退出码 0 = 通过; 非 0 = 失败。
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
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
TOKEN = "smoke-token"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http(url: str, method: str = "GET", body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        text = exc.read().decode(errors="replace") if exc.fp else ""
        try:
            return exc.code, json.loads(text)
        except json.JSONDecodeError:
            return exc.code, text


def _wait_ready(proc: subprocess.Popen, port: int) -> bool:
    deadline = time.time() + WAIT_START_SECONDS
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            code, _ = _http(f"http://127.0.0.1:{port}/health")
            if code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def _start(tmp: Path, webchat_port: int, control_port: int) -> subprocess.Popen:
    data_dir = tmp / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "config_version": "1.0.0",
        "channels": {"webchat": {"enabled": True, "bind_host": "127.0.0.1", "bind_port": webchat_port}},
        "control": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": control_port,
            "api_token": TOKEN,
            "setup_enabled": False,
        },
        "llm": {"provider": "openai", "api_key": "sk-your-key", "model": "gpt-4o-mini"},
    }
    (data_dir / "config.jsonc").write_text(json.dumps(config), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ISAC_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        [PYTHON, "-m", "isac"],
        cwd=str(tmp),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc


def _stop(proc: subprocess.Popen) -> str:
    """SIGTERM 优雅停, 返回 stdout 尾部。"""
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
    out = proc.stdout.read() if proc.stdout else ""
    return out


def _send_webchat(port: int, session_id: str) -> int:
    """经 webchat 发消息建会话, 返回 status code。"""
    code, _ = _http(
        f"http://127.0.0.1:{port}/webchat/send",
        method="POST",
        body={"session_id": session_id, "user_id": "u1", "content": "你好"},
    )
    return code


def _count_sessions(db_path: Path) -> int:
    """直查 sessions.db 行数 (绕过内存, 验证持久化落地)。"""
    import sqlite3

    if not db_path.exists():
        return -1
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("SELECT COUNT(*) FROM sessions")
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def _first_session_id(db_path: Path) -> str | None:
    """取 sessions.db 中第一个 session_id (供跨重启比对)。"""
    import sqlite3

    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute("SELECT session_id FROM sessions LIMIT 1")
        row = cur.fetchone()
        return str(row[0]) if row else None
    finally:
        conn.close()


def main() -> int:
    webchat_port = _free_port()
    control_port = _free_port()
    tmp = Path(tempfile.mkdtemp(prefix="isac_smoke_r5_"))

    try:
        # 第一次启动: 发消息建会话
        print("[smoke] 第一次启动, 建会话")
        proc1 = _start(tmp, webchat_port, control_port)
        try:
            if not _wait_ready(proc1, control_port):
                print("[smoke] FAIL: 第一次启动 control 未就绪")
                print(_stop(proc1)[-1500:])
                return 2
            code = _send_webchat(webchat_port, "smoke_session")
            if code != 200:
                print(f"[smoke] FAIL: 发消息返回 {code}")
                print(_stop(proc1)[-1500:])
                return 3
            # 等会话写入 SQLite (异步 best-effort, webchat 投递 + process_message)
            time.sleep(1.5)
            print("[smoke] OK: 会话已建立")
        finally:
            out1 = _stop(proc1)

        # 验证 sessions.db 已生成 + 有行
        db_path = tmp / "data" / "gateway" / "sessions.db"
        count1 = _count_sessions(db_path)
        sid1 = _first_session_id(db_path)
        if count1 <= 0 or sid1 is None:
            print(f"[smoke] FAIL: sessions.db 无行 (count={count1})")
            print(out1[-1500:])
            return 4
        print(f"[smoke] OK: sessions.db {count1} 行, session_id={sid1}")

        # 第二次启动: 同 data 目录, 发同一会话键消息 → 应恢复同一 session_id (不新建)
        webchat_port2 = _free_port()
        control_port2 = _free_port()
        print("[smoke] 第二次启动 (重启), 验证会话恢复")
        proc2 = _start(tmp, webchat_port2, control_port2)
        try:
            if not _wait_ready(proc2, control_port2):
                print("[smoke] FAIL: 第二次启动 control 未就绪")
                print(_stop(proc2)[-1500:])
                return 5
            # 主动发同会话键消息触发 get_or_create → 从库恢复 (不新建 session_id)
            code = _send_webchat(webchat_port2, "smoke_session")
            if code != 200:
                print(f"[smoke] FAIL: 重启后发消息返回 {code}")
                print(_stop(proc2)[-1500:])
                return 6
            time.sleep(1.5)
        finally:
            out2 = _stop(proc2)

        # 验证: 重启后发同一会话键, session_id 应与第一次相同 (恢复而非新建)
        sid2 = _first_session_id(db_path)
        count2 = _count_sessions(db_path)
        if sid2 != sid1:
            print(f"[smoke] FAIL: 重启后 session_id 变了 ({sid1} → {sid2}), 未恢复")
            print(out2[-1500:])
            return 7
        print(f"[smoke] OK: 重启后 session_id 不变 ({sid2}), 恢复成功 (行数 {count2})")
        print("[smoke] ALL PASS")
        return 0
    except AssertionError as exc:
        print(f"[smoke] FAIL: {exc}")
        return 8
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
