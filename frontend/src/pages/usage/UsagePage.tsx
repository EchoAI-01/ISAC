import { Callout, PageHeader } from "@/components/Card";
import { Tabs } from "@/components/Tabs";
import { useUrlTab } from "@/hooks/useUrlState";

import UsageEventsTab from "./components/UsageEventsTab";
import UsageFilters from "./components/UsageFilters";
import UsageSummaryTab from "./components/UsageSummaryTab";
import UsageTrendTab from "./components/UsageTrendTab";

const TABS = ["summary", "events", "trend"] as const;

/**
 * Usage & Cost 域 (§8.1 IA 第 5 行)。
 *
 * 时间范围与全部筛选写 URL (useUsageUrlState), 三个 tab 共享同一份过滤条件:
 * 汇总 (group_by 多选) / 明细 (物理请求 + 分页) / 趋势 (hour|day 桶)。
 * 计量未启用时整组端点不挂载 → QueryState 渲染 unavailable 与配置提示。
 */
export default function UsagePage() {
  const [tab, setTab] = useUrlTab(TABS, "summary");

  return (
    <div className="stack">
      <PageHeader
        title="Usage & Cost"
        description="Token、缓存、推理 Token、音视频时长、图片/视频数量、估算成本"
      />

      <Callout tone="info" title="口径说明 (SPEC §九 Usage + Cost)">
        <span className="small">
          请求数与 Token 为<strong>物理请求</strong>口径, 含重试与回退 (同一逻辑回复可能计多次);
          成本为按 pricing 快照查表的<strong>估算值</strong>, 单位 USD, 价格未知的分组显示 —
          而不伪造成 0; 页面展示的时间一律为浏览器本地时区。
        </span>
      </Callout>

      <UsageFilters />

      <Tabs
        ariaLabel="用量与成本分区"
        value={tab}
        onChange={setTab}
        items={[
          { value: "summary", label: "汇总", content: <UsageSummaryTab /> },
          { value: "events", label: "明细", content: <UsageEventsTab /> },
          { value: "trend", label: "趋势", content: <UsageTrendTab /> },
        ]}
      />
    </div>
  );
}
