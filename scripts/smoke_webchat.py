#!/usr/bin/env python3
"""T1 真机冒烟脚本: 部署 → 发消息 → 收到回复 这条最短路径无条件走通。

复现 2026-07-31 真机冒烟实证的部署路径 (干净目录 + 默认配置启动 → POST /webchat/send
"你好" → GET /webchat/poll), 断言能收到非空回复。修复前 (门控私聊需 has_mention +
占位符 key 被 401) 这里收不到任何回复。

用法:
    uv run python scripts/smoke_webchat.py

退出码 0 = 冒烟通过; 非 0 = 失败 (打印诊断)。
该脚本是 T1 验收铁律 ("真机部署证据") 的可重复执行载体, 也供 CI 调用。
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
import urllib.request
from pathlib import Path

ISAC_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
WAIT_START_SECONDS = 4.0
WAIT_REPLY_SECONDS = 6.0


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


def _wait_webchat_ready(proc: subprocess.Popen, port: int) -> bool:
    """轮询 /webchat/poll 直到服务就绪 (返回 200/401) 或子进程退出或超时。"""
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
    """轮询 /webchat/poll 直到拿到非空 replies 或超时。"""
    deadline = time.time() + WAIT_REPLY_SECONDS
    while time.time() < deadline:
        code, resp = _http_json(f"http://127.0.0.1:{port}/webchat/poll?session_id={session_id}")
        if code == 200:
            replies = resp.get("replies", [])
            if replies:
                return replies
        time.sleep(0.3)
    return []


def main() -> int:
    port = _free_port()
    tmp = Path(tempfile.mkdtemp(prefix="isac_smoke_"))
    data_dir = tmp / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    # 最小可启动配置: webchat 开 + llm 占位符 key (T1 修复后占位符 → Stub + 引导回复)
    config = {
        "config_version": "1.0.0",
        "channels": {
            "webchat": {"enabled": True, "bind_host": "127.0.0.1", "bind_port": port},
        },
        "llm": {"provider": "openai", "api_key": "sk-your-key", "model": "gpt-4o-mini"},
    }
    (data_dir / "config.jsonc").write_text(json.dumps(config), encoding="utf-8")

    env = dict(os.environ)
    env["ISAC_DATA_DIR"] = str(tmp)
    env["PYTHONPATH"] = str(ISAC_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    print(f"[smoke] 启动 python -m isac, work_dir={tmp}, webchat_port={port}")
    proc = subprocess.Popen(
        [PYTHON, "-m", "isac"],
        cwd=str(tmp),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        if not _wait_webchat_ready(proc, port):
            out = proc.stdout.read() if proc.stdout else ""  # type: ignore[union-attr]
            print(f"[smoke] FAIL: webchat 未在 {WAIT_START_SECONDS}s 内就绪")
            print(out[-2000:])
            return 2

        # 发消息 "你好" (私聊, session_id 模拟客户端)
        print("[smoke] POST /webchat/send '你好'")
        code, _ = _http_json(
            f"http://127.0.0.1:{port}/webchat/send",
            method="POST",
            body={"session_id": "s1", "user_id": "u1", "content": "你好"},
        )
        if code != 200:
            print(f"[smoke] FAIL: /webchat/send 返回 {code}")
            return 3

        # poll 回复 (Stub 回复同步入队, 立即可取; 真实 LLM 也应数秒内)
        replies = _poll_replies(port, "s1")
        if not replies:
            print(f"[smoke] FAIL: {WAIT_REPLY_SECONDS}s 内未收到回复 (修复前症状: 静默 WAIT)")
            return 4

        content = replies[0].get("content", "")
        print(f"[smoke] OK: 收到回复 -> {content[:80]}")
        if not content.strip():
            print("[smoke] FAIL: 回复内容为空")
            return 5
        return 0
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
