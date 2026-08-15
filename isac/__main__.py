"""ISAC 入口: `python -m isac` 或 `uv run python -m isac`。

子命令:
- (无) / run       : 启动服务 (默认)
- password reset   : 清除首登密码, 回到首登态 (对标 AstrBot CLI 兜底, T3-backend)
- plugin ...       : 插件管理 (list/marketplace/install/reload/uninstall/failed/retry,
                     经控制面 API 操作, T6)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any


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


def _http_json(
    url: str, *, token: str, method: str = "GET", body: dict | None = None
) -> tuple[int, Any]:
    """经控制面 API 调用, 返回 (status_code, json_or_text)。连接失败返回 (-1, 错误)。"""
    import urllib.error
    import urllib.request

    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(text)
            except json.JSONDecodeError:
                return resp.status, text
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            return exc.code, json.loads(text)
        except json.JSONDecodeError:
            return exc.code, text
    except urllib.error.URLError as exc:
        print(f"[plugin] 控制面连接失败: {exc.reason} (确认 isac 服务已启动, --url 正确)")
        return -1, str(exc)


def _repo_name(url: str) -> str:
    """从 URL 取末段作插件名 (兜底, 优先用 --name 显式指定)。"""
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    for ext in (".git", ".zip"):
        if tail.endswith(ext):
            tail = tail[: -len(ext)]
    return tail or "plugin"


def _parse_install_source(source: str, name: str) -> dict[str, Any]:
    """install 参数 → source dict: 纯名 → market; .git 结尾 → git; .zip 结尾 → url。"""
    if "://" in source:
        kind = "git" if source.endswith(".git") else "url"
        field = "repo_url" if kind == "git" else "url"
        return {"type": kind, field: source, "name": name or _repo_name(source)}
    return {"type": "market", "name": source}


def _cmd_plugin(args) -> int:
    """插件管理: 经控制面 API 操作插件 (T6)。install/reload 需运行中服务做激活+sync。"""
    base = args.url.rstrip("/")
    token = args.token
    cmd = args.plugin_command

    handlers: dict[str, Any] = {
        "list": lambda: _http_json(f"{base}/api/v1/plugins/loaded", token=token),
        "marketplace": lambda: _http_json(
            f"{base}/api/v1/plugins/marketplace" + ("?refresh=true" if args.refresh else ""),
            token=token,
        ),
        "failed": lambda: _http_json(f"{base}/api/v1/plugins/failed", token=token),
        "install": lambda: _http_json(
            f"{base}/api/v1/plugins/install",
            token=token,
            method="POST",
            body={"source": _parse_install_source(args.source, args.name)},
        ),
        "reload": lambda: _http_json(
            f"{base}/api/v1/plugins/{args.name}/reload", token=token, method="POST"
        ),
        "uninstall": lambda: _http_json(
            f"{base}/api/v1/plugins/{args.name}", token=token, method="DELETE"
        ),
        "retry": lambda: _http_json(
            f"{base}/api/v1/plugins/{args.name}/retry", token=token, method="POST"
        ),
    }
    handler = handlers.get(cmd)
    if handler is None:
        print(f"[plugin] 未知子命令: {cmd}")
        return 1
    code, data = handler()
    if code < 0:
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=2) if isinstance(data, (dict, list)) else data)
    return 0 if 200 <= code < 300 else 1


def _add_common_opts(p: Any) -> None:
    """为 plugin 子命令加公共参数 --url/--token。"""
    p.add_argument("--url", default="http://127.0.0.1:8765", help="控制面 URL")
    p.add_argument(
        "--token",
        default=os.environ.get("ISAC_API_TOKEN", ""),
        help="Bearer Token (默认 ISAC_API_TOKEN env)",
    )


def _cmd_secret(args) -> int:
    """密钥管理 (R5): SecretStore (AES-256-GCM) 加密读写。需 env ISAC_SECRET_KEY。"""
    import os

    env_key = os.environ.get("ISAC_SECRET_KEY")
    if not env_key:
        print(
            "[secret] 未配置 ISAC_SECRET_KEY 环境变量 (32 字节 base64)。生成命令:\n"
            "  python -c \"import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())\"\n"
            "设置后重试 (export ISAC_SECRET_KEY=<上面输出>)。"
        )
        return 1
    from isac.utils.security import SecretStore

    store = SecretStore("data/.secrets.enc")
    import asyncio

    if args.secret_command == "set":
        # 不 echo 明文 (getpass); 无 TTY 时退化为 stdin
        try:
            import getpass

            value = getpass.getpass(f"输入 {args.key} 的值 (不回显): ")
        except Exception:  # noqa: BLE001 无 TTY
            value = input(f"输入 {args.key} 的值: ")
        if not value:
            print("[secret] 值为空, 已取消")
            return 1
        asyncio.run(store.set(args.key, value))
        print(f"[secret] 已加密存储 {args.key}")
        return 0
    if args.secret_command == "get":
        fetched: str | None = asyncio.run(store.get(args.key))
        print(fetched if fetched else "[secret] 未找到该密钥")
        return 0 if fetched else 1
    if args.secret_command == "delete":
        ok = asyncio.run(store.delete(args.key))
        print(f"[secret] {'已删除' if ok else '未找到'} {args.key}")
        return 0 if ok else 1
    print(f"[secret] 未知子命令: {args.secret_command}")
    return 1


def main_cli() -> int:
    parser = argparse.ArgumentParser(prog="isac", description="ISAC 命令行入口")
    sub = parser.add_subparsers(dest="command")

    # password (T3-backend)
    pw = sub.add_parser("password", help="首登密码管理 (T3-backend)")
    pw_sub = pw.add_subparsers(dest="password_command", required=False)
    pw_reset = pw_sub.add_parser("reset", help="清除首登密码, 回到首登态")
    pw_reset.add_argument(
        "--state-path",
        default="data/control/setup_state.json",
        help="setup_state.json 路径 (默认 data/control/setup_state.json)",
    )

    # secret (R5)
    sec = sub.add_parser("secret", help="密钥管理 (R5, AES-256-GCM 加密存储)")
    sec_sub = sec.add_subparsers(dest="secret_command", required=True)
    sec_set = sec_sub.add_parser("set", help="加密存储一个密钥")
    sec_set.add_argument("key", help="密钥引用名 (配置中用 secret:<key> 引用)")
    sec_get = sec_sub.add_parser("get", help="读取一个密钥明文")
    sec_get.add_argument("key", help="密钥引用名")
    sec_del = sec_sub.add_parser("delete", help="删除一个密钥")
    sec_del.add_argument("key", help="密钥引用名")

    # plugin (T6)
    plugin = sub.add_parser("plugin", help="插件管理 (T6, 经控制面 API)")
    plugin_sub = plugin.add_subparsers(dest="plugin_command", required=True)
    _add_common_opts(plugin_sub.add_parser("list", help="列出已加载插件"))
    mk = plugin_sub.add_parser("marketplace", help="列出市场清单")
    mk.add_argument("--refresh", action="store_true", help="强制拉取远程清单")
    _add_common_opts(mk)
    p_install = plugin_sub.add_parser("install", help="安装插件 (市场名 / git URL / zip URL)")
    p_install.add_argument("source", help="市场插件名 / git URL / zip URL")
    p_install.add_argument("--name", default="", help="安装后的插件目录名 (默认从 URL 推断)")
    _add_common_opts(p_install)
    p_reload = plugin_sub.add_parser("reload", help="热重载插件")
    p_reload.add_argument("name", help="插件名")
    _add_common_opts(p_reload)
    p_uninstall = plugin_sub.add_parser("uninstall", help="卸载插件 (删目录)")
    p_uninstall.add_argument("name", help="插件名")
    _add_common_opts(p_uninstall)
    _add_common_opts(plugin_sub.add_parser("failed", help="列出失败插件"))
    p_retry = plugin_sub.add_parser("retry", help="重试加载失败插件")
    p_retry.add_argument("name", help="插件名")
    _add_common_opts(p_retry)

    args = parser.parse_args()
    if args.command == "password":
        if args.password_command == "reset":
            return _cmd_password_reset(args.state_path)
        pw.print_help()
        return 1
    if args.command == "plugin":
        return _cmd_plugin(args)
    if args.command == "secret":
        return _cmd_secret(args)

    # 默认: 启动服务
    from isac.main import main

    asyncio.run(main())
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
