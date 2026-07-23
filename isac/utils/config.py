"""配置加载与版本迁移。

加载顺序 (SPECIFICATION.md 3.2): 内置默认值 → data/config.jsonc → 环境变量 → CLI。
多 Agent 分层 (SPECIFICATION.md 3.3): 全局配置 ← Agent 级覆盖。
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from isac.utils.logger import get_logger

logger = get_logger(__name__)

try:
    import json5

    _HAS_JSON5 = True
except ImportError:  # pragma: no cover
    _HAS_JSON5 = False

CONFIG_VERSION = "1.0.0"


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


def load_config(path: str | Path) -> dict[str, Any]:
    """加载配置文件，依次应用默认值、文件、环境变量。"""
    config = dict(DEFAULT_CONFIG)

    file_path = Path(path)
    if file_path.exists():
        config.update(_parse_jsonc(file_path.read_text(encoding="utf-8")))
    else:
        logger.warning("配置文件不存在，使用默认值", path=str(file_path))

    for env_key, (config_key, convert) in ENV_MAPPING.items():
        if env_key in os.environ:
            _set_nested(config, config_key, convert(os.environ[env_key]))

    migrator = ConfigMigrator()
    return migrator.migrate(config)


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
