"""PluginLoader: 插件格式识别与加载。

按入口特征自动识别三种格式:
- manifest.jsonc → ISAC 原生
- AstrBot 特征 (Star 子类 / metadata.yaml) → AstrBot
- MaiBot 特征 (Plugin 基类 / plugin 配置) → MaiBot

加载流程: detect_format → 加载入口文件 → 找到插件类 → 实例化 → on_load。
"""

from __future__ import annotations

import importlib.util
import inspect
import json
from enum import Enum
from pathlib import Path
from typing import Any

from isac.plugin.compatibility.astrbot.star import Star
from isac.plugin.compatibility.maibot.plugin import MaiBotPlugin
from isac.plugin.native.plugin import ISACPlugin
from isac.utils.logger import get_logger

try:
    import json5

    _loads = json5.loads
except ImportError:  # pragma: no cover
    _loads = json.loads

logger = get_logger(__name__)


class PluginFormat(Enum):
    ISAC_NATIVE = "isac_native"  # manifest.jsonc (SPECIFICATION.md 2.6)
    ASTRBOT = "astrbot"  # AstrBot Star 插件
    MAIBOT = "maibot"  # MaiBot 插件


class LoadedPlugin:
    """加载后的插件实例 + 元数据。"""

    def __init__(
        self,
        *,
        name: str,
        format: PluginFormat,
        instance: Any,
        manifest: dict[str, Any] | None = None,
        path: Path | None = None,
    ) -> None:
        self.name = name
        self.format = format
        self.instance = instance
        self.manifest = manifest or {}
        self.path = path

    def is_native(self) -> bool:
        return self.format == PluginFormat.ISAC_NATIVE

    def is_astrbot(self) -> bool:
        return self.format == PluginFormat.ASTRBOT

    def is_maibot(self) -> bool:
        return self.format == PluginFormat.MAIBOT


class PluginLoader:
    """插件加载器。"""

    def detect_format(self, plugin_path: Path) -> PluginFormat:
        """按入口特征自动识别格式。

        优先级: manifest.jsonc > metadata.yaml (AstrBot) > mai_plugin.yaml (MaiBot)。
        都不匹配时抛 ValueError。
        """
        plugin_path = Path(plugin_path)
        if (plugin_path / "manifest.jsonc").exists():
            return PluginFormat.ISAC_NATIVE
        if (plugin_path / "metadata.yaml").exists():
            return PluginFormat.ASTRBOT
        if (plugin_path / "mai_plugin.yaml").exists():
            return PluginFormat.MAIBOT
        raise ValueError(f"无法识别插件格式: {plugin_path} 缺少 manifest.jsonc/metadata.yaml/mai_plugin.yaml")

    async def load(self, plugin_path: Path) -> LoadedPlugin:
        """加载插件, 返回 LoadedPlugin 实例。"""
        fmt = self.detect_format(plugin_path)
        if fmt == PluginFormat.ISAC_NATIVE:
            return await self._load_native(plugin_path)
        if fmt == PluginFormat.ASTRBOT:
            return await self._load_astrbot(plugin_path)
        return await self._load_maibot(plugin_path)

    # ── 各格式加载 ──────────────────────────────────────────

    async def _load_native(self, plugin_path: Path) -> LoadedPlugin:
        """ISAC 原生: 解析 manifest.jsonc, 按 entry 字段加载 plugin.py 找 ISACPlugin 子类。"""
        manifest = _loads((plugin_path / "manifest.jsonc").read_text(encoding="utf-8"))
        entry = manifest.get("entry", "plugin.py")
        entry_path = plugin_path / entry
        if not entry_path.exists():
            raise FileNotFoundError(f"插件入口不存在: {entry_path}")
        instance = self._find_subclass_in_file(entry_path, ISACPlugin)
        if instance is None:
            raise RuntimeError(f"未在 {entry_path} 中找到 ISACPlugin 子类")
        return LoadedPlugin(
            name=manifest.get("name", instance.name),
            format=PluginFormat.ISAC_NATIVE,
            instance=instance,
            manifest=manifest,
            path=plugin_path,
        )

    async def _load_astrbot(self, plugin_path: Path) -> LoadedPlugin:
        """AstrBot: 加载 plugin.py 找 Star 子类。"""
        entry_path = plugin_path / "plugin.py"
        if not entry_path.exists():
            raise FileNotFoundError(f"插件入口不存在: {entry_path}")
        instance = self._find_subclass_in_file(entry_path, Star)
        if instance is None:
            raise RuntimeError(f"未在 {entry_path} 中找到 Star 子类")
        return LoadedPlugin(
            name=type(instance).__name__,
            format=PluginFormat.ASTRBOT,
            instance=instance,
            path=plugin_path,
        )

    async def _load_maibot(self, plugin_path: Path) -> LoadedPlugin:
        """MaiBot: 加载 plugin.py 找 MaiBotPlugin 子类。"""
        entry_path = plugin_path / "plugin.py"
        if not entry_path.exists():
            raise FileNotFoundError(f"插件入口不存在: {entry_path}")
        instance = self._find_subclass_in_file(entry_path, MaiBotPlugin)
        if instance is None:
            raise RuntimeError(f"未在 {entry_path} 中找到 MaiBotPlugin 子类")
        # MaiBotPlugin 构造需要 config, 传空 dict 兜底
        if isinstance(instance, type):
            instance = instance({})
        return LoadedPlugin(
            name=type(instance).__name__,
            format=PluginFormat.MAIBOT,
            instance=instance,
            path=plugin_path,
        )

    # ── 内部 ────────────────────────────────────────────────

    @staticmethod
    def _find_subclass_in_file(entry_path: Path, base_class: type) -> Any:
        """从 entry_path 加载模块, 找第一个 base_class 的非抽象子类并实例化。

        - 类必须是 base_class 的子类 (排除 base_class 本身)
        - 尝试无参构造; 失败时尝试常见签名: (config) / (context)
        """
        spec = importlib.util.spec_from_file_location(entry_path.stem, entry_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"无法加载模块: {entry_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        for attr_name in dir(module):
            if attr_name.startswith("_"):
                continue
            obj = getattr(module, attr_name)
            if not inspect.isclass(obj):
                continue
            if obj is base_class:
                continue
            if not issubclass(obj, base_class):
                continue
            instance = PluginLoader._try_instantiate(obj, attr_name)
            if instance is not None:
                return instance
        return None

    @staticmethod
    def _try_instantiate(obj: type, attr_name: str) -> Any:
        """尝试用多种签名实例化插件类, 失败返回 None。"""
        signatures: list[dict[str, Any]] = [{}, {"config": {}}, {"context": None}]
        for kwargs in signatures:
            try:
                return obj(**kwargs)
            except TypeError:
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("插件类实例化失败", cls=attr_name, error=str(exc))
                return None
        logger.warning("插件类实例化失败 (所有签名均不匹配)", cls=attr_name)
        return None
