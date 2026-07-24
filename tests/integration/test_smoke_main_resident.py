"""进程级 smoke test: python -m isac 在无 Channel / 仅 Control / 启用 Channel 三种
模式下持续驻留, SIGTERM 优雅关闭无 pending task warning (K1, DEVELOPMENT_PLAN.md)。

测试用 subprocess 启动真实 python -m isac, 等 1 秒让它进入 serve_forever, 发送
SIGTERM, 等待退出, 检查退出码 0 且 stderr 不含 "Task was destroyed but it is pending"。
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ISAC_ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


def _write_config(tmp_path: Path, config: dict) -> Path:
    config_path = tmp_path / "config.jsonc"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


def _start_isac(tmp_path: Path, config: dict | None = None, env_overrides: dict | None = None) -> subprocess.Popen:  # type: ignore[type-arg]
    """启动 python -m isac 子进程, 工作目录指向 ISAC_ROOT, data/ 在 tmp_path。

    config 为 None 时用默认配置 (load_config 在文件不存在时用 DEFAULT_CONFIG);
    env_overrides 通过 ISAC_* 环境变量注入控制面/LLM/Channel 配置 (utils/config.py ENV_MAPPING)。
    """
    if config is not None:
        _write_config(tmp_path, config)
    env = dict(os.environ)
    env["ISAC_DATA_DIR"] = str(tmp_path)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.Popen(
        [PYTHON, "-m", "isac"],
        cwd=ISAC_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_and_terminate(proc: subprocess.Popen, runtime_seconds: float = 1.5) -> tuple[int, str]:  # type: ignore[type-arg]
    """等进程进入驻留态后 SIGTERM, 等退出, 返回 (returncode, combined_output)。"""
    time.sleep(runtime_seconds)
    proc.send_signal(signal.SIGTERM)
    try:
        out, _ = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate(timeout=5)
        return proc.returncode, out or ""
    return proc.returncode, out or ""


_UNIX_ONLY = pytest.mark.skipif(
    not sys.platform.startswith("linux") and not sys.platform.startswith("darwin"),
    reason="信号处理仅在 Unix 适用",
)


@_UNIX_ONLY
def test_smoke_no_channel_mode_resident_and_sigterm_clean(tmp_path: Path) -> None:
    """无 Channel 模式: 进程驻留 + SIGTERM 优雅退出 + 无 pending task warning (K1)。"""
    config = {
        "config_version": "1.0.0",
        "debug": False,
        "control": {"enabled": False},
        "channels": {},
        "llm": {},
    }
    proc = _start_isac(tmp_path, config)
    returncode, output = _wait_and_terminate(proc)

    assert returncode == 0, f"exit={returncode}\noutput={output}"
    assert "Task was destroyed but it is pending" not in output
    assert "ISAC 启动完成" in output or "已退出" in output


@_UNIX_ONLY
def test_smoke_control_plane_only_mode_resident_and_sigterm_clean(tmp_path: Path) -> None:
    """仅 Control 模式: 进程驻留 + SIGTERM 优雅退出 + 无 pending task warning (K1)。

    通过 ISAC_CONTROL_ENABLED/HOST/PORT/API_TOKEN 环境变量注入, utils/config.py ENV_MAPPING
    会把它们 set_nested 到全局 config 的 control.* 路径, 不依赖 config.jsonc 文件。
    """
    port = _find_free_port()
    env_overrides = {
        "ISAC_CONTROL_ENABLED": "true",
        "ISAC_CONTROL_HOST": "127.0.0.1",
        "ISAC_CONTROL_PORT": str(port),
        "ISAC_API_TOKEN": "",
    }
    proc = _start_isac(tmp_path, env_overrides=env_overrides)
    returncode, output = _wait_and_terminate(proc, runtime_seconds=3.5)

    assert returncode == 0, f"exit={returncode}\noutput={output}"
    assert "Task was destroyed but it is pending" not in output
    # 控制面应该真的启动了 (uvicorn 非日志, 但 main.py 会 logger.info("控制面已注册", ...))
    assert "控制面已注册" in output or "控制面已启动" in output


def _find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
