"""AstrBot import 重定向沙箱 (P2 兼容策略, ARCHITECTURE.md 3.8)。

sys.meta_path 自定义查找器: 拦截 astrbot.* 的 import，重定向到 ISAC 兼容层。
"""

from __future__ import annotations

import importlib
import sys
from importlib.abc import MetaPathFinder
from typing import Any


class AstrBotImportFinder(MetaPathFinder):
    """拦截 astrbot.* 的 import"""

    # 兼容层覆盖的 astrbot 模块清单
    MAPPING = {
        "astrbot.api.star": "isac.plugin.compatibility.astrbot.star",
        "astrbot.api.event": "isac.plugin.compatibility.astrbot.events",
        "astrbot.api.provider": "isac.plugin.compatibility.astrbot.context",
        "astrbot.api.platform": "isac.plugin.compatibility.astrbot.context",
    }

    def find_module(self, name: str, path: Any = None) -> Any:
        if not name.startswith("astrbot."):
            return None
        if name in self.MAPPING:
            return AstrBotModuleLoader(self.MAPPING[name])
        raise ImportError(f"不支持的 astrbot 模块: {name}。兼容层仅覆盖: {list(self.MAPPING.keys())}")


class AstrBotModuleLoader:
    def __init__(self, target_module: str):
        self.target = target_module

    def load_module(self, name: str) -> Any:
        module = importlib.import_module(self.target)
        sys.modules[name] = module
        return module


def install_sandbox() -> None:
    """安装沙箱 (在插件加载前调用)。"""
    sys.meta_path.insert(0, AstrBotImportFinder())
