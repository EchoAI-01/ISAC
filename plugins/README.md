# ISAC 插件目录

将插件放在此目录下，支持三种格式（加载器自动识别，见 ARCHITECTURE.md 3.8）：

| 格式 | 特征 | 说明 |
|------|------|------|
| ISAC 原生 | `manifest.jsonc` (SPECIFICATION.md 2.6) | 能力最强：Hooks/Injectors/Tools/Commands/互联钩子/Admin Routes(预留) |
| AstrBot | Star 子类插件 | P0 EventType + FunctionTool 桥接 |
| MaiBot | Plugin 基类插件 | Action → Tool / Command → ISAC Command |

插件权限遵循最小权限原则（DEVELOP.md 7.2），在 manifest 中声明所需权限。
