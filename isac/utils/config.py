"""配置加载与版本迁移。

加载顺序 (SPECIFICATION.md 3.2): 内置默认值 → data/config.jsonc → 环境变量 → CLI。
多 Agent 分层 (SPECIFICATION.md 3.3): 全局配置 ← Agent 级覆盖。
"""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from isac.utils.config_schema import validate_config
from isac.utils.logger import get_logger

logger = get_logger(__name__)

try:
    import json5

    _HAS_JSON5 = True
except ImportError:  # pragma: no cover
    _HAS_JSON5 = False

CONFIG_VERSION = "1.0.0"

# N1e: 全局配置持久化 + 热重载。data/config.jsonc 带注释 (json5), 控制面整体回写
# 会丢注释, 故控制面写入**独立 override 文件** (机器所有, 纯 JSON, 原子写),
# 加载序变为: 内置默认 ← config.jsonc (用户手编) ← override (控制面写入)
# ← 环境变量 ← CLI。override 中叶值为 null 表示"删除该覆盖项"。
CONFIG_OVERRIDE_FILENAME = "config.override.json"
# override 文件顶层保留键: 乐观锁 revision (J3-2 同构), 合并进有效配置前剔除。
OVERRIDE_REVISION_KEY = "__revision__"


def _to_bool(value: str) -> bool:
    """把环境变量字符串转成真布尔值 (裸字符串 "false"/"0" 不能被当真值)。"""
    return value.strip().lower() in ("1", "true", "yes", "on")


# 环境变量映射 (SPECIFICATION.md 3.2): env var -> (dotted_key, 类型转换函数)
ENV_MAPPING: dict[str, tuple[str, Callable[[str], Any]]] = {
    "ISAC_LLM_PROVIDER": ("llm.provider", str),
    "ISAC_LLM_API_KEY": ("llm.api_key", str),
    "ISAC_LLM_MODEL": ("llm.model", str),
    "ISAC_DEBUG": ("debug", _to_bool),
    "ISAC_LOG_LEVEL": ("log_level", str),
    "ISAC_MEMORY_ENABLED": ("memory.enabled", _to_bool),
    "ISAC_CONTROL_ENABLED": ("control.enabled", _to_bool),
    "ISAC_CONTROL_HOST": ("control.host", str),
    "ISAC_CONTROL_PORT": ("control.port", int),
    "ISAC_API_TOKEN": ("control.api_token", str),
    "ISAC_ONEBOT_ENABLED": ("channels.onebot.enabled", _to_bool),
    "ISAC_ONEBOT_HOST": ("channels.onebot.host", str),
    "ISAC_ONEBOT_PORT": ("channels.onebot.port", int),
}

DEFAULT_CONFIG: dict[str, Any] = {
    "config_version": CONFIG_VERSION,
    "debug": False,
    "log_level": "info",
    # T2: 内置最小可启动默认配置 (对标 AstrBot core/config/default.py)。无 data/config.jsonc
    # 时不再依赖各处 .get(..., {}) 兜底拼凑的隐式行为, 而是一份明确的"未配置模型 →
    # 引导去配"路径。webchat 默认开 (loopback), llm 空 (Stub + 引导), control/memory 默认关
    # (default-off 铁律, 不引入隐式 SQLite/embedding 启动)。config.sample.jsonc 降级为
    # 可选覆盖参考; 用户显式提供任一字段即覆盖默认值 (config.update 语义)。
    "llm": {},
    "control": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8765,
        "api_token": "",
        "setup_enabled": True,
        # T6: 插件市场与热重载。marketplace_url 空 = 仅本地 data/plugin_marketplace.jsonc;
        # allow_install=False 时不注册安装/重载/卸载写端点 (仅 read)。
        "plugins": {"isolated_plugins": [], "marketplace_url": "", "allow_install": True},
    },
    "memory": {"enabled": False},
    "channels": {
        "webchat": {
            "enabled": True,
            "bind_host": "127.0.0.1",
            "bind_port": 8090,
            "max_message_age_seconds": 300,
        }
    },
    "logging": {"level": "info"},
    # R3: 全局 MCP Server 定义 (name → 连接配置 {transport,command,args,env,url,token})。
    # assemble_agent 按 AgentConfig.mcp_servers (允许名列表) 查此表构造 MCPClient。
    # 默认空, 零行为变化; 用户在 config.jsonc 顶层 mcp.servers 下定义 server。
    "mcp": {"servers": {}},
}


def _parse_jsonc(text: str) -> dict[str, Any]:
    if _HAS_JSON5:
        return dict(json5.loads(text))
    return dict(json.loads(text))  # 无 json5 时退化为严格 JSON


def _set_nested(config: dict[str, Any], dotted_key: str, value: Any) -> None:
    keys = dotted_key.split(".")
    node = config
    for key in keys[:-1]:
        node = node.setdefault(key, {})
    node[keys[-1]] = value


def deep_merge_config(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """深合并 patch 到 base (返回新 dict, 不改原对象)。

    - dict × dict: 递归合并;
    - 其他类型 (含 list): patch 整体覆盖 base;
    - patch 叶值为 None: 删除 base 对应键 (override 语义下 = 撤销该覆盖项)。
    """
    result = dict(base)
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge_config(result[key], value)
        else:
            result[key] = value
    return result


def load_config_overrides(path: str | Path) -> tuple[dict[str, Any], int]:
    """读取 override 文件; 返回 (纯配置 dict, revision)。

    文件不存在 → ({}, 0)。文件损坏 (非法 JSON/revision 非整数) 抛 ValueError,
    由调用方决定降级策略 (控制面端点转 400, 启动加载不吞错)。
    """
    file_path = Path(path)
    if not file_path.exists():
        return {}, 0
    raw = _parse_jsonc(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"配置 override 文件顶层必须是对象: {file_path}")
    revision_raw = raw.pop(OVERRIDE_REVISION_KEY, 0)
    try:
        revision = int(revision_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"配置 override 文件 {OVERRIDE_REVISION_KEY} 非整数: {file_path}") from exc
    return raw, revision


def save_config_overrides(path: str | Path, patch: dict[str, Any]) -> int:
    """把 patch 深合并进 override 文件 (read-modify-write), revision +1, 原子写。

    patch 叶值 None = 删除既有覆盖项。返回新 revision (供 If-Match 乐观锁)。
    """
    from isac.utils.fs import atomic_write_text

    current, revision = load_config_overrides(path)
    merged = deep_merge_config(current, patch)
    new_revision = revision + 1
    payload = {**merged, OVERRIDE_REVISION_KEY: new_revision}
    atomic_write_text(Path(path), json.dumps(payload, ensure_ascii=False, indent=2))
    logger.info("全局配置 override 已保存", path=str(path), revision=new_revision)
    return new_revision


def load_config(
    path: str | Path,
    override_path: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """加载配置文件，依次应用默认值、文件、override、环境变量。

    N1e: override 来源二选一 —— ``overrides`` 直接传 dict (控制面 PATCH 校验
    候选用, 不落盘); 否则 ``override_path`` 存在时读文件深合并。两者都给了以
    ``overrides`` 为准。加载序 (SPECIFICATION.md 3.2 + N1e): 内置默认 →
    config.jsonc → override → 环境变量 (部署覆盖仍最高优先级)。
    """
    # T2: 深拷贝 DEFAULT_CONFIG。此前 dict(DEFAULT_CONFIG) 是浅拷贝, 嵌套 dict
    # (control/channels/llm/...) 仍引用全局 DEFAULT_CONFIG 的同一子对象; _set_nested
    # 原地改 config["control"]["enabled"] 会污染全局默认值, 让后续 load_config 调用
    # 拿到被污染的默认 (如 control.enabled 残留 True)。深拷贝隔离每次加载。
    config = copy.deepcopy(DEFAULT_CONFIG)

    file_path = Path(path)
    if file_path.exists():
        config.update(_parse_jsonc(file_path.read_text(encoding="utf-8")))
    else:
        logger.warning("配置文件不存在，使用默认值", path=str(file_path))

    if overrides is None and override_path is not None:
        overrides, _ = load_config_overrides(override_path)
    if overrides:
        config = deep_merge_config(config, overrides)

    for env_key, (config_key, convert) in ENV_MAPPING.items():
        if env_key in os.environ:
            _set_nested(config, config_key, convert(os.environ[env_key]))

    migrator = ConfigMigrator()
    # schema 校验: 非法端口/类型硬失败, control 启用但无认证时 CRITICAL 告警 (不阻断)。
    return validate_config(migrator.migrate(config))


class ConfigMigrator:
    """配置版本迁移器 (ARCHITECTURE.md 4.1)。

    每次配置格式变更时添加迁移函数，版本链式升级到最新。
    """

    MIGRATIONS: dict[str, Callable[[dict], dict]] = {
        # 从缺省/未声明版本升级到 1.0.0：仅补齐 config_version 字段。
        "0.0.0": lambda cfg: {**cfg, "config_version": "1.0.0"},
    }

    def migrate(self, config: dict[str, Any]) -> dict[str, Any]:
        """从当前版本迁移到最新版本。

        配置文件缺失 config_version 时视为 "0.0.0"，触发迁移到最新版本；
        与 ARCHITECTURE.md 4.1 的语义保持一致。
        """
        current_version = config.get("config_version", "0.0.0")
        target_version = self._get_latest_version()

        while current_version != target_version:
            migration = self.MIGRATIONS.get(current_version)
            if migration is None:
                logger.warning("无法找到配置的迁移路径，跳过", version=current_version)
                break
            config = migration(config)
            current_version = config["config_version"]

        return config

    def _get_latest_version(self) -> str:
        return CONFIG_VERSION
