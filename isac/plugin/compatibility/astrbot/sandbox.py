"""AstrBot import 重定向沙箱 (P2 兼容策略, ARCHITECTURE.md 3.8)。

sys.meta_path 自定义查找器: 拦截 astrbot.* 的 import，重定向到 ISAC 兼容层。
使用 Python 3.12 兼容的 importlib.abc.MetaPathFinder.find_spec() 协议。
"""

from __future__ import annotations

import importlib
import sys
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
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

    def find_spec(self, name: str, path: Any = None, target: Any = None) -> ModuleSpec | None:
        if not name.startswith("astrbot."):
            return None
        if name in self.MAPPING:
            target_module = self.MAPPING[name]
            # 预先加载目标模块，确保 Loader 能拿到 module 对象
            importlib.import_module(target_module)
            return ModuleSpec(name, AstrBotModuleLoader(target_module), origin=target_module)
        raise ImportError(f"不支持的 astrbot 模块: {name}。兼容层仅覆盖: {list(self.MAPPING.keys())}")


class AstrBotModuleLoader(Loader):
    def __init__(self, target_module: str):
        self.target = target_module

    def create_module(self, spec: ModuleSpec) -> None:
        return None  # 使用默认模块创建

    def exec_module(self, module: Any) -> None:
        target = importlib.import_module(self.target)
        sys.modules[module.__name__] = target


def install_sandbox() -> None:
    """安装沙箱 (在插件加载前调用)。"""
    sys.meta_path.insert(0, AstrBotImportFinder())
