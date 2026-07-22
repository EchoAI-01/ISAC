"""数据迁移脚本: AstrBot / MaiBot → ISAC。

把 AstrBot / MaiBot 的配置与记忆数据转换为 ISAC 格式。

用法:
    uv run python scripts/migrate.py --from astrbot --src /path/to/astrbot/data --dst data/
    uv run python scripts/migrate.py --from maibot --src /path/to/maibot/data --dst data/

迁移内容:
- AstrBot 配置 (config.json) → ISAC data/config.jsonc 的 channels/llm 段
- AstrBot 插件目录 → ISAC plugins/ (不动, 直接复用兼容层)
- MaiBot 配置 (config.toml) → ISAC data/config.jsonc
- 两者的人设 / 记忆 / 用户数据 → ISAC data/agents/<id>/config.jsonc + data/memory/
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from isac.utils.logger import get_logger

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="ISAC 数据迁移工具")
    parser.add_argument(
        "--from", dest="source", choices=["astrbot", "maibot"], required=True
    )
    parser.add_argument("--src", required=True, help="源数据目录")
    parser.add_argument("--dst", default="data/", help="目标数据目录")
    parser.add_argument(
        "--dry-run", action="store_true", help="只打印将要执行的操作, 不实际写文件"
    )
    args = parser.parse_args()

    src_path = Path(args.src)
    dst_path = Path(args.dst)
    if not src_path.exists():
        raise SystemExit(f"源目录不存在: {src_path}")

    dst_path.mkdir(parents=True, exist_ok=True)

    if args.source == "astrbot":
        report = migrate_from_astrbot(src_path, dst_path, dry_run=args.dry_run)
    else:
        report = migrate_from_maibot(src_path, dst_path, dry_run=args.dry_run)

    print(json.dumps(report, ensure_ascii=False, indent=2))


def migrate_from_astrbot(
    src: Path, dst: Path, *, dry_run: bool = False
) -> dict[str, Any]:
    """从 AstrBot 数据目录迁移到 ISAC。"""
    report: dict[str, Any] = {"source": "astrbot", "dry_run": dry_run, "actions": []}
    llm_config = _parse_astrbot_llm(src, report)
    _copy_astrbot_plugins(src, dst, dry_run=dry_run, report=report)
    _write_astrbot_config(dst, llm_config, dry_run=dry_run, report=report)
    report["ok"] = True
    return report


def _parse_astrbot_llm(src: Path, report: dict[str, Any]) -> dict[str, Any]:
    """从 AstrBot 配置解析 LLM 字段。"""
    for config_path in [src / "cmd_config.json", src / "data" / "llm_model.json"]:
        if not config_path.exists():
            continue
        try:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            report["actions"].append(f"{config_path.name} 解析失败: {exc}")
            continue
        if "provider_llm" in raw:
            pl = raw["provider_llm"]
            if pl.get("key"):
                report["actions"].append(f"LLM 配置已解析 (provider={pl.get('type')})")
                return {
                    "provider": "openai_compat",
                    "api_key": pl.get("key", ""),
                    "model": pl.get("model") or "gpt-3.5-turbo",
                    "base_url": pl.get("api_base") or "https://api.openai.com/v1",
                }
        if "key" in raw:
            report["actions"].append("LLM 配置从 llm_model.json 解析")
            return {
                "provider": "openai_compat",
                "api_key": raw.get("key", ""),
                "model": raw.get("model", ""),
                "base_url": raw.get("api_base", ""),
            }
    return {}


def _copy_astrbot_plugins(
    src: Path, dst: Path, *, dry_run: bool, report: dict[str, Any]
) -> None:
    """复制 AstrBot 插件目录到 ISAC plugins/。"""
    src_plugins = src / "data" / "plugin"
    dst_plugins = dst.parent / "plugins"
    if not src_plugins.exists() or not src_plugins.is_dir():
        report["actions"].append("未发现 AstrBot 插件目录, 跳过")
        return
    report["actions"].append(
        f"插件目录复制: {src_plugins} → {dst_plugins} ({len(list(src_plugins.iterdir()))} 项)"
    )
    if dry_run:
        return
    dst_plugins.mkdir(parents=True, exist_ok=True)
    for entry in src_plugins.iterdir():
        target = dst_plugins / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True)
        else:
            shutil.copy2(entry, target)


def _write_astrbot_config(
    dst: Path, llm_config: dict[str, Any], *, dry_run: bool, report: dict[str, Any]
) -> None:
    """写出 ISAC 全局配置。"""
    isac_config = {
        "debug": False,
        "llm": llm_config or {"provider": "stub"},
        "memory": {"enabled": False},
        "channels": {"onebot": {"enabled": False}},
        "control": {"enabled": False, "host": "127.0.0.1", "port": 8765},
    }
    config_path = dst / "config.jsonc"
    report["actions"].append(f"写出 ISAC 配置: {config_path}")
    if dry_run:
        return
    dst.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(isac_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def migrate_from_maibot(
    src: Path, dst: Path, *, dry_run: bool = False
) -> dict[str, Any]:
    """从 MaiBot 数据目录迁移到 ISAC。

    MaiBot 配置位置:
    - config.toml: 全局配置
    - bot_: Bot 配置
    - memory/: 记忆数据

    ISAC 等价:
    - data/config.jsonc: 全局配置
    - data/agents/<id>/config.jsonc: 单 Agent 配置
    - data/memory/: 记忆目录 (元数据迁移)
    """
    report: dict[str, Any] = {"source": "maibot", "dry_run": dry_run, "actions": []}

    config_toml = src / "config.toml"
    bot_config: dict[str, Any] = {}
    if config_toml.exists():
        try:
            try:
                import tomllib
            except ImportError:
                import tomli as tomllib  # type: ignore[no-redef]
            with config_toml.open("rb") as fp:
                bot_config = tomllib.load(fp)
            report["actions"].append("config.toml 解析成功")
        except Exception as exc:  # noqa: BLE001
            report["actions"].append(f"config.toml 解析失败: {exc}")

    # 转换 LLM 配置
    llm_config: dict[str, Any] = {}
    llm_section = bot_config.get("LLM", {})
    if llm_section.get("api_key"):
        llm_config = {
            "provider": "openai_compat",
            "api_key": llm_section.get("api_key", ""),
            "model": llm_section.get("model", ""),
            "base_url": llm_section.get("base_url", ""),
        }
        report["actions"].append("LLM 配置已转换")

    # 迁移记忆目录 (元数据, 不做内容转换, MaiBot 格式与 ISAC 不同)
    src_memory = src / "memory"
    dst_memory = dst / "memory" / "maibot_backup"
    if src_memory.exists():
        report["actions"].append(
            f"记忆目录备份: {src_memory} → {dst_memory} (MaiBot 格式保留, 不自动转换)"
        )
        if not dry_run:
            dst_memory.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src_memory, dst_memory, dirs_exist_ok=True)

    # 创建默认 Agent (单 Agent 模式)
    agents_dir = dst / "agents" / "default"
    agent_config = {
        "agent_id": "default",
        "display_name": bot_config.get("bot", {}).get("nickname", "MaiBot"),
        "trigger_words": bot_config.get("bot", {}).get("alias_names", []),
        "tools_policy": {},
        "commands_allow": ["*"],
        "plugins_allow": ["*"],
        "plugins_deny": [],
        "mcp_servers": [],
    }
    agent_config_path = agents_dir / "config.jsonc"
    report["actions"].append(f"创建默认 Agent 配置: {agent_config_path}")
    if not dry_run:
        agents_dir.mkdir(parents=True, exist_ok=True)
        agent_config_path.write_text(
            json.dumps(agent_config, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # 写出 ISAC 全局配置
    isac_config = {
        "debug": False,
        "bot_id": bot_config.get("bot", {}).get("bot_qq", ""),
        "llm": llm_config or {"provider": "stub"},
        "memory": {"enabled": True, "embedding": {"provider": "fastembed"}},
        "channels": {"onebot": {"enabled": True, "host": "0.0.0.0", "port": 8080}},
        "control": {"enabled": False, "host": "127.0.0.1", "port": 8765},
    }
    config_path = dst / "config.jsonc"
    report["actions"].append(f"写出 ISAC 全局配置: {config_path}")
    if not dry_run:
        config_path.write_text(
            json.dumps(isac_config, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    report["ok"] = True
    return report
