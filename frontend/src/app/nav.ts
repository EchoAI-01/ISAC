/** 十域信息架构 (CONTROL_PLANE_SPEC §8.1)。
 *
 * 页面与路由一一对应; 序号即侧栏顺序与键盘快捷键 (Alt+1..Alt+0)。
 * 每个域的"核心内容/主要操作"来自 §8.1 表格, 用于页面副标题与 e2e 断言。
 */

export interface NavItem {
  /** 路由路径。 */
  to: string;
  /** 侧栏文本。 */
  label: string;
  /** §8.1 的核心内容摘要 (页面副标题)。 */
  description: string;
  /** 快捷键序号 (1-10 → Alt+1..Alt+9, Alt+0)。 */
  index: number;
}

export const NAV_ITEMS: NavItem[] = [
  {
    to: "/",
    label: "Dashboard",
    description: "Agent / Channel / Provider 健康、消息与任务、Token 与成本、错误与告警趋势",
    index: 1,
  },
  {
    to: "/agents",
    label: "Agents",
    description: "状态、人格、门控、模型能力、工具/插件/MCP、记忆命名空间",
    index: 2,
  },
  {
    to: "/channels",
    label: "Channels & Routing",
    description: "连接状态、绑定、默认 Agent、触发词、primary/observer/candidate",
    index: 3,
  },
  {
    to: "/providers",
    label: "Providers & Models",
    description: "Provider 健康、模型能力、模态、限制、成本/延迟层级",
    index: 4,
  },
  {
    to: "/usage",
    label: "Usage & Cost",
    description: "Token、缓存、推理 Token、音视频时长、图片/视频数量、估算成本",
    index: 5,
  },
  {
    to: "/extensions",
    label: "Extensions",
    description: "插件、MCP Server、工具、命令及 Agent × Channel 启用矩阵",
    index: 6,
  },
  {
    to: "/memory",
    label: "Memory",
    description: "命名空间、Episode、人物画像、行话、索引健康和容量",
    index: 7,
  },
  {
    to: "/sessions",
    label: "Sessions & Tasks",
    description: "活跃会话、Agent 状态、工具链、ProgressEvent、中断与错误",
    index: 8,
  },
  {
    to: "/logs",
    label: "Logs & Audit",
    description: "结构化日志、告警、审计、Webhook 发送结果",
    index: 9,
  },
  {
    to: "/system",
    label: "System",
    description: "全局配置、存储、备份、版本、运行环境",
    index: 10,
  },
];

/** 路径 → 导航项 (含详情页回落到所属域)。 */
export function navItemForPath(pathname: string): NavItem {
  const exact = NAV_ITEMS.find((item) => item.to === pathname);
  if (exact) return exact;
  const prefixMatch = NAV_ITEMS.filter((item) => item.to !== "/" && pathname.startsWith(item.to)).sort(
    (a, b) => b.to.length - a.to.length,
  )[0];
  return prefixMatch ?? NAV_ITEMS[0]!;
}

/** 快捷键标签 (Alt+数字)。 */
export function shortcutLabel(index: number): string {
  return `Alt+${index % 10}`;
}
