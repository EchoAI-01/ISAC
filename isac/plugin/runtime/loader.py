"""PluginLoader: 插件格式识别与加载。"""

from __future__ import annotations

from enum import Enum
from pathlib import Path


class PluginFormat(Enum):
    ISAC_NATIVE = "isac_native"  # manifest.jsonc (SPECIFICATION.md 2.6)
    ASTRBOT = "astrbot"  # AstrBot Star 插件
    MAIBOT = "maibot"  # MaiBot 插件


class PluginLoader:
    """插件加载器。

    [桩] 按入口特征自动识别三种格式:
    - manifest.jsonc → ISAC 原生
    - AstrBot 特征 (Star 子类 / metadata.yaml) → AstrBot
    - MaiBot 特征 (Plugin 基类 / plugin 配置) → MaiBot
    """

    def detect_format(self, plugin_path: Path) -> PluginFormat:
        raise NotImplementedError("PluginLoader.detect_format 尚未实现")

    async def load(self, plugin_path: Path) -> None:
        raise NotImplementedError("PluginLoader.load 尚未实现")
