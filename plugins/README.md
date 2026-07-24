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

## 当前状态

插件目录和兼容层设计已完成，加载器、启用矩阵、兼容桥接和沙箱隔离仍在 F 节点实现中。
