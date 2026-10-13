"""MaiBot import 重定向沙箱 (L2, 2026-10-13 review; 同构参照 AstrBot M12)。

sys.meta_path 自定义查找器: 拦截 ``maibot_sdk`` / ``maibot_sdk.types`` 的 import,
重定向到 ISAC 兼容层 shim (sdk_shim / sdk_types)。真实 MaiBot 插件
(pip 包 maibot-plugin-sdk, manifest_version 2) 的 ``from maibot_sdk import
MaiBotPlugin, Tool, Command`` 在 exec_module 时经此走通 —— 此前 MaiBot 兼容层
零 import 重定向 (与 M12 修复前的 AstrBot 同构), 真实插件加载即
ModuleNotFoundError, 兼容层只能服务直接 import ISAC 路径的自写插件。

结构说明: ``maibot_sdk`` 父模块必须是**包** (带 __path__) 否则子模块
``maibot_sdk.types`` 在父解析阶段就失败 —— 父模块用"属性搬运"的包 loader
(sdk_shim 的公开名拷贝到包模块上), 子模块用同名替换 loader (与 AstrBot
AstrBotModuleLoader 同款)。

未覆盖的 ``maibot_sdk.*`` 子模块显式 ImportError (列出覆盖面, 不静默半装载);
旧版 ``src.plugin_system.*`` 体系 (manifest_version 1, register_component 架构)
不在映射面 —— 与新版装饰器架构差异过大, 属另一个兼容目标。
"""

from __future__ import annotations

import importlib
import sys
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
from typing import Any

# maibot_sdk 子模块名 → ISAC shim 模块名 (父模块 maibot_sdk 走包 loader, 见上)
SUBMODULE_MAPPING = {
    "maibot_sdk.types": "isac.plugin.compatibility.maibot.sdk_types",
}
_SHIM_MODULE = "isac.plugin.compatibility.maibot.sdk_shim"


class MaiBotImportFinder(MetaPathFinder):
    """拦截 maibot_sdk / maibot_sdk.* 的 import。"""

    def find_spec(self, name: str, path: Any = None, target: Any = None) -> ModuleSpec | None:
        if not name.startswith("maibot_sdk"):
            return None
        if name == "maibot_sdk":
            # 父模块: 包 spec (is_package) + 属性搬运 loader —— 顶层名字
            # (MaiBotPlugin/Tool/Command/...) 直接可用, 子模块可解析。
            return ModuleSpec(name, MaiBotPkgLoader(), is_package=True)
        if name in SUBMODULE_MAPPING:
            target_module = SUBMODULE_MAPPING[name]
            # 预加载目标模块, 确保 Loader 能拿到 module 对象 (与 AstrBot M12 同款)。
            importlib.import_module(target_module)
            return ModuleSpec(name, MaiBotModuleLoader(target_module), origin=target_module)
        raise ImportError(
            f"不支持的 maibot_sdk 模块: {name}。兼容层仅覆盖: "
            f"{['maibot_sdk', *SUBMODULE_MAPPING.keys()]}"
        )


class MaiBotPkgLoader(Loader):
    """maibot_sdk 父模块加载器: 把 sdk_shim 的公开名搬运到包模块上。

    不替换 sys.modules 条目 (包模块本体保留, 保证 __path__ 语义)。
    """

    def create_module(self, spec: ModuleSpec) -> None:
        return None  # 使用默认模块创建

    def exec_module(self, module: Any) -> None:
        shim = importlib.import_module(_SHIM_MODULE)
        for attr in getattr(shim, "__all__", []):
            setattr(module, attr, getattr(shim, attr))


class MaiBotModuleLoader(Loader):
    """把 maibot_sdk.* 子模块名字绑定到 ISAC shim (sys.modules 双名同对象)。"""

    def __init__(self, target_module: str):
        self.target = target_module

    def create_module(self, spec: ModuleSpec) -> None:
        return None  # 使用默认模块创建

    def exec_module(self, module: Any) -> None:
        target = importlib.import_module(self.target)
        sys.modules[module.__name__] = target


def install_maibot_sandbox() -> None:
    """安装沙箱 (在 MaiBot 插件加载前调用)。幂等: 已安装时不重复插入 finder。"""
    for finder in sys.meta_path:
        if isinstance(finder, MaiBotImportFinder):
            return
    sys.meta_path.insert(0, MaiBotImportFinder())
