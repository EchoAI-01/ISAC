#!/usr/bin/env python3
"""T3-backend 真机验收: 干净目录启动 → 控制面可达 → 首登 setup 流程走通。

零配置启动 (DEFAULT_CONFIG: control.enabled=true + setup_enabled=true, 仅绑
127.0.0.1)。验证:
1. /health 可达 + setup_required=true (首登态)
2. /api/v1/audit 无 Bearer → 428 SETUP_REQUIRED (admin 端点首登封锁)
3. POST /api/v1/setup {password} → 200 (设密码, PBKDF2 哈希, 不落明文)
4. /api/v1/audit 带 Bearer 密码 → 200 (setup 后密码作 Bearer 生效)

退出码 0 = 通过; 非 0 = 失败 (打印诊断)。T3 验收铁律: 真机部署证据。
用法: uv run python scripts/smoke_control_setup.py
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
WAIT_START_SECONDS = 5.0
PASSWORD = "smoke-test-password-1"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _http_json(url: str, method: str = "GET", body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
        try:
            return exc.code, json.loads(exc.read().decode())
        except Exception:  # noqa: BLE001
            return exc.code, {}


def _wait_control_ready(proc: subprocess.Popen, base: str) -> bool:
    """轮询 /health 直到 setup_required=true 或子进程退出或超时。"""
    deadline = time.time() + WAIT_START_SECONDS
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            code, body = _http_json(f"{base}/health")
            if code == 200 and body.get("setup_required") is True:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.3)
    return False


def _run_setup_flow(base: str) -> int:
    """验证 428 首登封锁 → POST /setup 设密码 → Bearer 生效; 返回退出码。"""
    code, body = _http_json(f"{base}/api/v1/audit")
    if code != 428 or body.get("detail", {}).get("code") != "SETUP_REQUIRED":
        print(f"[smoke] FAIL: /api/v1/audit 首登态应 428 SETUP_REQUIRED, 实际 {code} {body}")
        return 3
    print("[smoke] OK: /api/v1/audit → 428 SETUP_REQUIRED (首登封锁)")

    code, body = _http_json(f"{base}/api/v1/setup", method="POST", body={"password": PASSWORD})
    if code != 200:
        print(f"[smoke] FAIL: POST /setup 应 200, 实际 {code} {body}")
        return 4
    print("[smoke] OK: POST /setup 设密码 → 200 (PBKDF2 哈希)")

    code, body = _http_json(f"{base}/api/v1/audit", token=PASSWORD)
    if code != 200:
        print(f"[smoke] FAIL: /api/v1/audit 带 setup 密码应 200, 实际 {code} {body}")
        return 5
    print("[smoke] OK: /api/v1/audit 带 Bearer 密码 → 200 (setup 后密码生效)")
    return 0


def main() -> int:
    port = _free_port()
    tmp = Path(tempfile.mkdtemp(prefix="isac_setup_smoke_"))
    env = dict(os.environ)
    env["ISAC_DATA_DIR"] = str(tmp)
    env["ISAC_CONTROL_PORT"] = str(port)
    env["PYTHONPATH"] = str(ISAC_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    print(f"[smoke] 启动 python -m isac (零配置, control 127.0.0.1:{port}), work_dir={tmp}")
    proc = subprocess.Popen(
        [PYTHON, "-m", "isac"],
        cwd=str(tmp),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        if not _wait_control_ready(proc, base):
            out = proc.stdout.read() if proc.stdout else ""  # type: ignore[union-attr]
            print(f"[smoke] FAIL: control 未在 {WAIT_START_SECONDS}s 内就绪 (setup_required=true)")
            print(out[-2000:])
            return 2
        print("[smoke] OK: /health → setup_required=true (首登态)")
        return _run_setup_flow(base)
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
