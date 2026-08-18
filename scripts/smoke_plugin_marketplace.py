#!/usr/bin/env python3
"""T6 真机冒烟: 零配置启动 → 列市场清单 → 安装 → reload → 卸载 全流程。

验证插件市场端点 + 一键安装 (upload zip_b64) + 热重载 + 卸载真实走通 (对标
smoke_webchat 自包含模式)。控制面用 api_token 认证 + setup_enabled=false (smoke
专门配置, 非生产默认; 生产默认首登强制设密码)。

用法: uv run python scripts/smoke_plugin_marketplace.py
退出码 0 = 通过; 非 0 = 失败 (打印诊断)。
"""

from __future__ import annotations

import base64
import io
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
import zipfile
from pathlib import Path

ISAC_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
WAIT_START_SECONDS = 6.0
TOKEN = "smoke-token"
PLUGIN_NAME = "smoke_echo"

# 动态构造的最小 native 插件: on_load 注册一个 echo 工具 (验证激活 + 工具注入)
PLUGIN_PY = '''from isac.agent.tools.base import Tool, ToolContext, ToolResult
from isac.plugin.native.plugin import ISACPlugin, PluginContext


class _EchoTool(Tool):
    @property
    def name(self) -> str:
        return "smoke_echo_tool"

    @property
    def description(self) -> str:
        return "T6 smoke echo"

    async def execute(self, context: ToolContext) -> ToolResult:
        return ToolResult(content=str(context.args))


class SmokeEchoPlugin(ISACPlugin):
    async def on_load(self, context: PluginContext) -> None:
        context.register_tool(_EchoTool())
'''


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


def _make_plugin_zip_b64() -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.jsonc", json.dumps({"name": PLUGIN_NAME, "entry": "plugin.py"}))
        zf.writestr("plugin.py", PLUGIN_PY)
    return base64.b64encode(buf.getvalue()).decode()


def _wait_control_ready(proc: subprocess.Popen, port: int) -> bool:
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


def main() -> int:
    control_port = _free_port()
    webchat_port = _free_port()
    tmp = Path(tempfile.mkdtemp(prefix="isac_smoke_t6_"))
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
            "setup_enabled": False,  # smoke 专门配置绕过首登 (非生产默认)
            "plugins": {"allow_install": True},
        },
        "llm": {"provider": "openai", "api_key": "sk-your-key", "model": "gpt-4o-mini"},
    }
    (data_dir / "config.jsonc").write_text(json.dumps(config), encoding="utf-8")
    # 复制仓库内置市场清单到 tmp/data (PluginInstaller 默认读 data/plugin_marketplace.jsonc, 相对 cwd)
    shutil.copy(ISAC_ROOT / "data" / "plugin_marketplace.jsonc", data_dir / "plugin_marketplace.jsonc")

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ISAC_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    print(f"[smoke] 启动 python -m isac, control_port={control_port}")
    proc = subprocess.Popen(
        [PYTHON, "-m", "isac"],
        cwd=str(tmp),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        if not _wait_control_ready(proc, control_port):
            out = proc.stdout.read() if proc.stdout else ""
            print(f"[smoke] FAIL: control 未在 {WAIT_START_SECONDS}s 内就绪")
            print(out[-2000:])
            return 2

        base = f"http://127.0.0.1:{control_port}/api/v1"

        # 1. 市场清单
        code, data = _http(f"{base}/plugins/marketplace")
        assert code == 200, f"marketplace {code}: {data}"
        names = [p.get("name") for p in data.get("plugins", [])]
        assert "echo_tool" in names, f"市场清单缺 echo_tool: {names}"
        print("[smoke] OK: 市场清单含 echo_tool")

        # 2. 安装 (upload zip_b64)
        b64 = _make_plugin_zip_b64()
        code, data = _http(
            f"{base}/plugins/install",
            method="POST",
            body={"source": {"type": "upload", "zip_b64": b64, "name": PLUGIN_NAME}},
        )
        assert code == 200, f"install {code}: {data}"
        assert "loaded" in str(data), f"install status: {data}"
        print("[smoke] OK: 安装成功")

        # 3. loaded 含
        code, data = _http(f"{base}/plugins/loaded")
        assert code == 200
        loaded = [p.get("name") for p in data.get("plugins", [])]
        assert PLUGIN_NAME in loaded, f"loaded 缺 {PLUGIN_NAME}: {loaded}"
        print(f"[smoke] OK: loaded 含 {PLUGIN_NAME}")

        # 4. 热重载
        code, data = _http(f"{base}/plugins/{PLUGIN_NAME}/reload", method="POST")
        assert code == 200, f"reload {code}: {data}"
        assert "loaded" in str(data), f"reload status: {data}"
        print("[smoke] OK: 热重载成功")

        # 5. 卸载
        code, data = _http(f"{base}/plugins/{PLUGIN_NAME}", method="DELETE")
        assert code == 200, f"uninstall {code}: {data}"
        print("[smoke] OK: 卸载成功")

        # 6. loaded 不含
        code, data = _http(f"{base}/plugins/loaded")
        loaded = [p.get("name") for p in data.get("plugins", [])]
        assert PLUGIN_NAME not in loaded, f"卸载后仍 loaded: {loaded}"
        print(f"[smoke] OK: 卸载后 loaded 不含 {PLUGIN_NAME}")

        print("[smoke] ALL PASS")
        return 0
    except AssertionError as exc:
        print(f"[smoke] FAIL: {exc}")
        return 3
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
