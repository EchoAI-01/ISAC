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
        # M12: 父包 (astrbot / astrbot.api) 提供空命名空间包 —— 否则导入
        # astrbot.api.star 时父包解析失败 (真实 astrbot 未安装 → ModuleNotFoundError),
        # 子模块映射永远走不到。
        if name in ("astrbot", "astrbot.api"):
            return ModuleSpec(name, AstrBotNamespaceLoader(), is_package=True)
        if not name.startswith("astrbot."):
            return None
        if name in self.MAPPING:
            target_module = self.MAPPING[name]
            # 预先加载目标模块，确保 Loader 能拿到 module 对象
            importlib.import_module(target_module)
            return ModuleSpec(name, AstrBotModuleLoader(target_module), origin=target_module)
        raise ImportError(f"不支持的 astrbot 模块: {name}。兼容层仅覆盖: {list(self.MAPPING.keys())}")


class AstrBotNamespaceLoader(Loader):
    """M12: astrbot / astrbot.api 父包的空加载器 (仅提供命名空间, 无实际代码)。"""

    def create_module(self, spec: ModuleSpec) -> None:
        return None  # 使用默认模块创建

    def exec_module(self, module: Any) -> None:
        # is_package=True 的 spec 已带 __path__=[], 空包体无需执行任何代码
        return None


class AstrBotModuleLoader(Loader):
    def __init__(self, target_module: str):
        self.target = target_module

    def create_module(self, spec: ModuleSpec) -> None:
        return None  # 使用默认模块创建

    def exec_module(self, module: Any) -> None:
        target = importlib.import_module(self.target)
        sys.modules[module.__name__] = target


def install_sandbox() -> None:
    """安装沙箱 (在插件加载前调用)。幂等: 已安装时不重复插入 finder。"""
    for finder in sys.meta_path:
        if isinstance(finder, AstrBotImportFinder):
            return
    sys.meta_path.insert(0, AstrBotImportFinder())
