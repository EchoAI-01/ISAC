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

# 环境变量映射 (SPECIFICATION.md 3.2)
ENV_MAPPING: dict[str, str] = {
    "ISAC_LLM_PROVIDER": "llm.provider",
    "ISAC_LLM_API_KEY": "llm.api_key",
    "ISAC_DEBUG": "debug",
    "ISAC_LOG_LEVEL": "log_level",
    "ISAC_MEMORY_ENABLED": "memory.enabled",
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
    """加载配置文件，依次应用默认值、文件、环境变量。

    TODO(Day 8): CLI 参数覆盖；API Key 加密读取 (utils/security.py)。
    """
    config = dict(DEFAULT_CONFIG)

    file_path = Path(path)
    if file_path.exists():
        config.update(_parse_jsonc(file_path.read_text(encoding="utf-8")))
    else:
        logger.warning("配置文件不存在，使用默认值", path=str(file_path))

    for env_key, config_key in ENV_MAPPING.items():
        if env_key in os.environ:
            _set_nested(config, config_key, os.environ[env_key])

    migrator = ConfigMigrator()
    return migrator.migrate(config)


class ConfigMigrator:
    """配置版本迁移器 (ARCHITECTURE.md 4.1)。

    每次配置格式变更时添加迁移函数，版本链式升级到最新。
    """

    MIGRATIONS: dict[str, Callable[[dict], dict]] = {
        # "1.0.0": migrate_from_1_0_to_1_1,
    }

    def migrate(self, config: dict[str, Any]) -> dict[str, Any]:
        """从当前版本迁移到最新版本。"""
        current_version = config.get("config_version", CONFIG_VERSION)
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
