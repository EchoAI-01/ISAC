import { PageHeader } from "@/components/Card";
import { Tabs } from "@/components/Tabs";
import { useUrlTab } from "@/hooks/useUrlState";

import AppearanceTab from "./components/AppearanceTab";
import GlobalConfigTab from "./components/GlobalConfigTab";
import IdentityTab from "./components/IdentityTab";
import MetricsTab from "./components/MetricsTab";
import SystemOverviewTab from "./components/SystemOverviewTab";
import TenantsTab from "./components/TenantsTab";

const TABS = ["overview", "config", "metrics", "tenants", "identity", "appearance"] as const;

/**
 * System 域 (§8.1 IA 第 10 行)。
 *
 * 概览 (/health 全字段 + 版本口径不造假) / 全局配置 (F2 配置编辑事务 +
 * restart_required 分区呈现) / 指标 (快照三表 + Prometheus 文本) /
 * 多租户 (增删 + 成员管理) / 身份归一 (冲突裁决 + 手动绑定) / 外观 (主题偏好)。
 */
export default function SystemPage() {
  const [tab, setTab] = useUrlTab(TABS, "overview");

  return (
    <div className="stack">
      <PageHeader
        title="System"
        description="全局配置、存储、备份、版本、运行环境"
      />

      <Tabs
        ariaLabel="系统分区"
        value={tab}
        onChange={setTab}
        items={[
          { value: "overview", label: "概览", content: <SystemOverviewTab /> },
          { value: "config", label: "全局配置", content: <GlobalConfigTab /> },
          { value: "metrics", label: "指标", content: <MetricsTab /> },
          { value: "tenants", label: "多租户", content: <TenantsTab /> },
          { value: "identity", label: "身份归一", content: <IdentityTab /> },
          { value: "appearance", label: "外观", content: <AppearanceTab /> },
        ]}
      />
    </div>
  );
}
