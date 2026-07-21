"""PluginLoader: 插件格式识别与加载 (DEVELOPMENT_PLAN.md Day 59-60)。"""

from __future__ import annotations

from enum import Enum
from pathlib import Path


class PluginFormat(Enum):
    ISAC_NATIVE = "isac_native"  # manifest.jsonc (SPECIFICATION.md 2.6)
    ASTRBOT = "astrbot"  # AstrBot Star 插件
    MAIBOT = "maibot"  # MaiBot 插件


class PluginLoader:
    """插件加载器。

    TODO(Day 59): 按入口特征自动识别三种格式:
    - manifest.jsonc → ISAC 原生
    - AstrBot 特征 (Star 子类 / metadata.yaml) → AstrBot
    - MaiBot 特征 (Plugin 基类 / plugin 配置) → MaiBot
    """

    def detect_format(self, plugin_path: Path) -> PluginFormat:
        raise NotImplementedError("TODO(Day 59): 实现格式识别")

    async def load(self, plugin_path: Path) -> None:
        raise NotImplementedError("TODO(Day 59): 实现加载")
