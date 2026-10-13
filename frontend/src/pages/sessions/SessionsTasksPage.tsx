import { PageHeader } from "@/components/Card";
import { Tabs } from "@/components/Tabs";
import { useApprovals } from "@/hooks/queries";
import { useUrlTab } from "@/hooks/useUrlState";

import ApprovalsTab from "./components/ApprovalsTab";
import SessionsTab from "./components/SessionsTab";
import SubAgentsTab from "./components/SubAgentsTab";

const TABS = ["sessions", "subagents", "approvals"] as const;

/**
 * Sessions & Tasks 域 (§8.1 IA 第 8 行 + §8.4 SubAgent 隐私边界)。
 *
 * 会话 (消息历史) / SubAgent 任务 (清单 + 事件时间线 + 取消) / 审批 HITL
 * (待决裁决 + 决策留痕)。?tab= 与 ?task= 都写 URL —— 从 Agent 详情页
 * "子任务" tab 跳转 (/sessions?tab=subagents&task=…) 可直达单个任务详情。
 */
export default function SessionsTasksPage() {
  const [tab, setTab] = useUrlTab(TABS, "sessions");
  // 待审批数角标 (与审批 tab 共享查询缓存; 端点未挂载时为 undefined, 不显示角标)。
  const approvals = useApprovals();
  const pendingCount = approvals.data ? approvals.data.approvals.length : undefined;

  return (
    <div className="stack">
      <PageHeader
        title="Sessions & Tasks"
        description="活跃会话、Agent 状态、工具链、ProgressEvent、中断与错误"
      />

      <Tabs
        ariaLabel="会话与任务分区"
        value={tab}
        onChange={setTab}
        items={[
          { value: "sessions", label: "会话", content: <SessionsTab /> },
          { value: "subagents", label: "SubAgent 任务", content: <SubAgentsTab /> },
          {
            value: "approvals",
            label: "审批 (HITL)",
            count: pendingCount,
            content: <ApprovalsTab />,
          },
        ]}
      />
    </div>
  );
}
