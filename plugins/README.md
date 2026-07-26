# ISAC 插件目录

将插件放在此目录下，支持三种格式（加载器自动识别，见 ARCHITECTURE.md 3.8 / PLUGIN_COMPATIBILITY.md）：

| 格式 | 特征 | 说明 |
|------|------|------|
| ISAC 原生 | `manifest.jsonc` (SPECIFICATION.md 2.6) | 能力最强：Hooks/Injectors/Tools/Commands/互联钩子/Admin Routes(预留) |
| AstrBot | `metadata.yaml` / Star 子类插件 | P0 EventType + FunctionTool 桥接 |
| MaiBot | `config.toml` / Plugin 基类插件 | Action → Tool / Command → ISAC Command |

插件权限遵循最小权限原则（DEVELOP.md 7.2），在 manifest 中声明所需权限。兼容范围、权限模型、生命周期、热重载和测试插件集合见 [../docs/PLUGIN_COMPATIBILITY.md](../docs/PLUGIN_COMPATIBILITY.md)。

## 开发入口

| 需求 | 阅读 |
|------|------|
| 写 ISAC 原生插件 | `PLUGIN_COMPATIBILITY.md` 的 ISAC Native SDK 章节、`SPECIFICATION.md` 2.6 |
| 迁移 AstrBot 插件 | `PLUGIN_COMPATIBILITY.md` 的 AstrBot 兼容层章节 |
| 迁移 MaiBot 插件 | `PLUGIN_COMPATIBILITY.md` 的 MaiBot 兼容层章节 |
| 配置插件权限 | `PLUGIN_COMPATIBILITY.md` 权限模型、`DEVELOP.md` 7.2 |

## ⚠️ 安全护栏（务必先读）

**当前生产加载路径没有进程隔离/沙箱**：放入本目录的插件在 ISAC **宿主进程内**加载执行（`exec_module` 直接运行入口文件顶层代码），拥有与宿主完全相同的文件系统、网络与系统权限。

- **只放置你完全信任、且审阅过源码的插件**；
- 不要加载来源不明的第三方插件；
- `PluginIsolationHost`（子进程隔离宿主）已支持在资源受限的独立进程中真实加载插件（`load_plugin`），但**尚未接管本目录的默认加载路径**——接管前上述警告持续有效（启动日志中也会输出同样的护栏警告）。

## 当前状态

插件目录、兼容层、加载器、启用矩阵已完成；`on_load(context)` 生命周期钩子已在主链路接线（插件可注册事件订阅/Admin Route，工具与命令注册待 per-Agent 接线）。进程级沙箱隔离机制已实现（子进程 + 资源限额 + IPC），默认加载路径的接管仍在推进中。
