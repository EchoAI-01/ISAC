"""PluginManager: 插件生命周期管理。

加载目录下所有插件, 自动识别格式 (ISAC Native / AstrBot / MaiBot),
实例化后调用 on_load。热重载: 卸载时调用 on_unload 并从 Registry 移除。
错误隔离: 单个插件加载失败不影响其他插件。
启用矩阵: is_enabled_for 调用 EnableMatrix (Agent ∩ Channel ∩ 全局)。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from isac.plugin.runtime.loader import LoadedPlugin, PluginLoader
from isac.utils.logger import get_logger

if TYPE_CHECKING:
    from isac.core.policy import EnableMatrix
    from isac.plugin.isolation.host import PluginIsolationHost
    from isac.plugin.native.plugin import PluginContext

try:
    import json5

    _loads = json5.loads
except ImportError:  # pragma: no cover
    _loads = json.loads

logger = get_logger(__name__)


class PluginManager:
    """插件管理器。

    待实现:
    - 加载/依赖解析/热重载; 插件错误隔离 (SPECIFICATION.md 5.1)
    - 启用矩阵生效 (AgentConfig.plugins_allow/deny ∩ channel_matrix)
    """

    def __init__(
        self,
        config: dict[str, Any],
        enable_matrix: EnableMatrix | None = None,
        plugin_context_factory: Any = None,
    ):
        self.config = config
        self.enable_matrix = enable_matrix
        self._loader = PluginLoader()
        self._loaded: dict[str, LoadedPlugin] = {}  # name -> LoadedPlugin (宿主进程内)
        # H2: name -> PluginIsolationHost (manifest isolated=true 的插件, 跑在子进程)
        self._iso_hosts: dict[str, PluginIsolationHost] = {}
        self._plugin_context_factory = plugin_context_factory

    async def load_all(self, plugin_dir: str | Path) -> dict[str, Any]:
        """加载目录下全部插件 (自动识别 AstrBot / MaiBot / ISAC 原生格式)。

        H2: manifest 声明 isolated=true 的原生插件经 PluginIsolationHost 在**子进程**
        加载 (顶层代码不进宿主, 资源受限); 其余插件仍在宿主进程内加载。错误隔离:
        单个插件加载失败记录日志, 不影响其他插件。返回 {name: 状态} 报告。
        """
        plugin_dir = Path(plugin_dir)
        if not plugin_dir.exists():
            logger.info("插件目录不存在, 跳过加载", plugin_dir=str(plugin_dir))
            return {}
        entries = [entry for entry in sorted(plugin_dir.iterdir()) if entry.is_dir()]
        in_process = [entry for entry in entries if not self._is_isolated_native(entry)]
        if in_process:
            # H2: 隔离插件已改走子进程; 宿主进程内加载路径仍无沙箱, 只对非隔离插件告警。
            logger.warning(
                "部分插件在宿主进程内加载执行, 无进程隔离 —— 仅加载完全可信的插件 "
                "(需隔离的插件请在 manifest.jsonc 声明 isolated: true)",
                plugin_dir=str(plugin_dir),
                count=len(in_process),
            )
        report: dict[str, str] = {}
        for entry in entries:
            await self._load_entry(entry, report)
        return report

    async def _load_entry(self, entry: Path, report: dict[str, str]) -> None:
        """加载单个插件目录 (isolated=true → 子进程, 否则宿主进程内)。错误隔离。"""
        try:
            if self._is_isolated_native(entry):
                await self._load_isolated(entry, report)
                return
            loaded = await self._loader.load(entry)
            self._loaded[loaded.name] = loaded
            report[entry.name] = f"loaded ({loaded.format.value})"
            logger.info("插件已加载", name=loaded.name, format=loaded.format.value, path=str(entry))
        except Exception as exc:  # noqa: BLE001 错误隔离
            logger.warning("插件加载失败", path=str(entry), error=str(exc))
            report[entry.name] = f"failed: {exc}"

    @staticmethod
    def _is_isolated_native(entry: Path) -> bool:
        """原生插件 manifest 是否声明 isolated=true (只有 ISAC 原生格式支持隔离标志)。"""
        manifest_path = entry / "manifest.jsonc"
        if not manifest_path.exists():
            return False
        try:
            manifest = _loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 manifest 解析失败交给常规加载路径报错
            return False
        return bool(manifest.get("isolated", False))

    async def _load_isolated(self, entry: Path, report: dict[str, str]) -> None:
        """H2: 经 PluginIsolationHost 在子进程加载插件 (顶层代码不进宿主进程)。"""
        from isac.plugin.isolation.host import PluginIsolationHost

        manifest = _loads((entry / "manifest.jsonc").read_text(encoding="utf-8"))
        name = str(manifest.get("name") or entry.name)
        host = PluginIsolationHost(plugin_id=name)
        await host.spawn()
        try:
            result = await host.load_plugin(str(entry))
        except Exception:
            await host.kill()
            raise
        if result.kind == "result":
            self._iso_hosts[name] = host
            report[entry.name] = "loaded (isolated)"
            logger.info("插件已隔离加载 (子进程)", name=name, path=str(entry))
        else:
            await host.kill()
            error = str(result.payload.get("error", "unknown"))
            report[entry.name] = f"failed: {error}"
            logger.warning("隔离插件加载失败", name=name, error=error)

    async def unload(self, name: str) -> bool:
        """卸载插件: 隔离插件终止其子进程; 宿主内插件调用 on_unload 并移除。"""
        host = self._iso_hosts.pop(name, None)
        if host is not None:
            await host.kill()
            logger.info("隔离插件已卸载 (子进程终止)", name=name)
            return True
        loaded = self._loaded.get(name)
        if loaded is None:
            return False
        try:
            if hasattr(loaded.instance, "on_unload"):
                await loaded.instance.on_unload()
        except Exception as exc:  # noqa: BLE001
            logger.warning("插件 on_unload 失败", name=name, error=str(exc))
        del self._loaded[name]
        logger.info("插件已卸载", name=name)
        return True

    def is_isolated(self, name: str) -> bool:
        """该插件是否以进程隔离方式 (子进程) 加载 (H2)。"""
        return name in self._iso_hosts

    async def call_isolated(self, name: str, method: str, **args: Any) -> Any:
        """调用隔离插件的一个方法 (经 IPC 送到子进程执行; H2)。

        私有方法 (下划线开头) 与未加载方法由子进程 worker 拒绝并回 kind=error,
        这里转成 RuntimeError 抛出。
        """
        host = self._iso_hosts.get(name)
        if host is None:
            raise KeyError(f"隔离插件未加载: {name}")
        from isac.plugin.isolation.protocol import IPCEnvelope

        result = await host.call(
            IPCEnvelope(kind="call", plugin_id=name, payload={"method": method, "args": args})
        )
        if result.kind == "error":
            raise RuntimeError(str(result.payload.get("error", "isolated call failed")))
        return result.payload.get("result")

    async def shutdown(self) -> None:
        """优雅关闭: 终止全部隔离插件子进程 (供生命周期停止钩子调用)。"""
        for name, host in list(self._iso_hosts.items()):
            try:
                await host.kill()
            except Exception as exc:  # noqa: BLE001
                logger.warning("隔离插件子进程终止失败, 已忽略", name=name, error=str(exc))
        self._iso_hosts.clear()

    def list_loaded(self) -> list[str]:
        return [*self._loaded.keys(), *self._iso_hosts.keys()]

    def get(self, name: str) -> LoadedPlugin | None:
        return self._loaded.get(name)

    def is_enabled_for(self, plugin_name: str, agent_id: str, platform: str) -> bool:
        """启用矩阵检查: Agent 允许 ∩ Channel 允许。

        EnableMatrix 未注入时默认放行; 否则按 plugins_allow/deny + Channel 矩阵计算。
        """
        if self.enable_matrix is None:
            return True
        # Agent 的 plugins_allow/deny 由调用方提供, 这里退化为 "*" + []
        # 真实场景: 调用方应基于 AgentConfig.is_enabled_for 调用, 见 E4 测试。
        return self.enable_matrix.is_plugin_enabled(plugin_name, ["*"], [], agent_id=agent_id, platform=platform)

    async def call_on_load(self, context: PluginContext) -> dict[str, str]:
        """对每个已加载的 Native 插件调用 on_load (传入 PluginContext)。

        AstrBot/MaiBot 兼容层由适配器单独处理, 不在此调用。
        """
        report: dict[str, str] = {}
        for name, loaded in list(self._loaded.items()):
            if not loaded.is_native():
                continue
            try:
                if hasattr(loaded.instance, "on_load"):
                    await loaded.instance.on_load(context)
                report[name] = "on_load ok"
            except Exception as exc:  # noqa: BLE001 错误隔离
                logger.warning("插件 on_load 失败", name=name, error=str(exc))
                report[name] = f"failed: {exc}"
        return report
