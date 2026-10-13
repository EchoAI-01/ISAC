import { Badge, statusTone } from "@/components/Badge";
import { Callout, Card } from "@/components/Card";
import { KeyValue, Stat, StatGrid } from "@/components/DataDisplay";
import { QueryState } from "@/components/QueryState";
import { useGlobalConfig, useHealth, useSetupStatus } from "@/hooks/queries";

/**
 * 概览 tab: /health 全字段 + setup_required + 控制面 host/port。
 *
 * 版本口径 (契约 §4 System): health 无版本字段; 仅当全局配置里真实存在
 * version 键才显示, 否则明确注明"后端未暴露版本号" —— 不硬编码假版本。
 */
export default function SystemOverviewTab() {
  const health = useHealth();
  const setup = useSetupStatus();
  const config = useGlobalConfig();

  const versionValue = (config.data?.config ?? {}).version;
  const version = typeof versionValue === "string" && versionValue !== "" ? versionValue : null;

  return (
    <div className="stack" data-testid="system-overview">
      <QueryState query={health}>
        {(h) => (
          <div className="stack">
            <StatGrid>
              <Stat
                label="整体状态"
                value={h.status}
                meta={h.status === "ok" ? "全部子系统正常" : "存在降级子系统 (见下)"}
                tone={h.status === "ok" ? "success" : "warning"}
                testId="system-stat-status"
              />
              <Stat
                label="Agents"
                value={`${h.subsystems.agents.running} / ${h.subsystems.agents.total}`}
                meta="运行中 / 已注册"
                tone={h.subsystems.agents.running > 0 ? "success" : "warning"}
                testId="system-stat-agents"
              />
              <Stat
                label="LLM"
                value={h.subsystems.llm}
                meta={
                  h.subsystems.llm === "configured"
                    ? "已配置真实 Provider"
                    : h.subsystems.llm === "stub"
                      ? "stub 模式 (未配置真实 LLM)"
                      : "见 /health.subsystems.llm"
                }
                tone={h.subsystems.llm === "configured" ? "success" : "warning"}
                testId="system-stat-llm"
              />
              <Stat
                label="Channels"
                value={String(h.subsystems.channels.length)}
                meta={h.subsystems.channels.join(", ") || "未注册任何平台"}
                testId="system-stat-channels"
              />
              <Stat
                label="控制面"
                value={h.subsystems.control.enabled ? "已启用" : "未启用"}
                meta={h.subsystems.control.enabled ? `${h.subsystems.control.host}:${h.subsystems.control.port}` : "control.enabled = false"}
                tone={h.subsystems.control.enabled ? "success" : "warning"}
                testId="system-stat-control"
              />
              <Stat
                label="首登向导"
                value={h.setup_required ? "待完成" : "已完成"}
                meta={setup.data ? `setup_required = ${String(setup.data.setup_required)}` : "探测中"}
                tone={h.setup_required ? "warning" : "success"}
                testId="system-stat-setup"
              />
            </StatGrid>

            <Card title="/health 原始字段" subtitle="GET /api/v1/health · 15s 自动刷新">
              <KeyValue
                items={[
                  {
                    term: "status",
                    value: <Badge tone={statusTone(h.status)} dot>{h.status}</Badge>,
                  },
                  { term: "subsystems.agents", value: `total=${h.subsystems.agents.total}, running=${h.subsystems.agents.running}` },
                  { term: "subsystems.llm", value: <code className="code-inline">{h.subsystems.llm}</code> },
                  {
                    term: "subsystems.channels",
                    value:
                      h.subsystems.channels.length > 0 ? (
                        <span className="row row--tight" style={{ flexWrap: "wrap" }}>
                          {h.subsystems.channels.map((platform) => (
                            <Badge key={platform} tone="info">{platform}</Badge>
                          ))}
                        </span>
                      ) : (
                        "(空)"
                      ),
                  },
                  {
                    term: "subsystems.control",
                    value: `enabled=${String(h.subsystems.control.enabled)}, host=${h.subsystems.control.host}, port=${h.subsystems.control.port}`,
                  },
                  { term: "setup_required", value: String(h.setup_required) },
                ]}
              />
            </Card>

            <Card title="版本" subtitle="不硬编码: 只显示后端真实暴露的值">
              {version ? (
                <KeyValue items={[{ term: "version (来自全局配置)", value: <code className="code-inline">{version}</code> }]} />
              ) : (
                <Callout tone="info" title="后端未暴露版本号">
                  <span className="small">
                    /health 响应没有版本字段, 当前全局配置里也没有 version 键 —— 本页不伪造 "1.0.0"
                    之类的占位版本 (v1 内置 WebUI 的缺陷)。部署版本请以镜像标签 / git commit 为准。
                  </span>
                </Callout>
              )}
            </Card>
          </div>
        )}
      </QueryState>
    </div>
  );
}
