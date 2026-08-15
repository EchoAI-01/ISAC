"""ISAC 入口: `python -m isac` 或 `uv run python -m isac`。

子命令 (T3-backend):
- (无) / run    : 启动服务 (默认)
- password reset : 清除首登密码, 回到首登态 (对标 AstrBot CLI 兜底)
"""

from __future__ import annotations

import argparse
import asyncio
import sys


def _cmd_password_reset(state_path: str) -> int:
    """清除首登密码 (删 setup_state.json), 控制面回到首登待设置态。"""
    from isac.control.setup import SetupManager

    mgr = SetupManager(state_path)
    if mgr.is_setup_required:
        print(f"[password reset] 首登密码未设置 ({state_path} 不存在), 无需重置")
        return 0
    mgr.reset()
    print(f"[password reset] 已清除首登密码 ({state_path}), 控制面回到首登态")
    return 0


def main_cli() -> int:
    parser = argparse.ArgumentParser(prog="isac", description="ISAC 命令行入口")
    sub = parser.add_subparsers(dest="command")

    pw = sub.add_parser("password", help="首登密码管理 (T3-backend)")
    pw_sub = pw.add_subparsers(dest="password_command", required=False)
    pw_reset = pw_sub.add_parser("reset", help="清除首登密码, 回到首登态")
    pw_reset.add_argument(
        "--state-path",
        default="data/control/setup_state.json",
        help="setup_state.json 路径 (默认 data/control/setup_state.json)",
    )

    args = parser.parse_args()
    if args.command == "password":
        if args.password_command == "reset":
            return _cmd_password_reset(args.state_path)
        pw.print_help()
        return 1

    # 默认: 启动服务
    from isac.main import main

    asyncio.run(main())
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
