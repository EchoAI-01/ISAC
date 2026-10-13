import { useState } from "react";

import type { PluginMatrix } from "@/api/types";
import { Button } from "@/components/Button";
import { Callout, Card } from "@/components/Card";
import { TagInput } from "@/components/Inputs";
import { QueryState } from "@/components/QueryState";
import { ConfirmDialog } from "@/components/Tabs";
import { usePutPluginMatrix } from "@/hooks/mutations";
import { useLoadedPlugins, usePluginMatrix } from "@/hooks/queries";

function MatrixEditor({ agentId, initial }: { agentId: string; initial: PluginMatrix }) {
  const [allow, setAllow] = useState<string[]>(initial.plugins_allow);
  const [deny, setDeny] = useState<string[]>(initial.plugins_deny);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const put = usePutPluginMatrix(agentId);
  const loaded = useLoadedPlugins();

  const suggestions = (loaded.data?.plugins ?? []).map((plugin) => plugin.name);
  const dirty =
    JSON.stringify(allow) !== JSON.stringify(initial.plugins_allow) ||
    JSON.stringify(deny) !== JSON.stringify(initial.plugins_deny);

  return (
    <div className="stack" data-testid="agent-plugin-matrix">
      <Callout tone="warning" title="插件矩阵是高影响能力变更">
        <span className="small">
          保存走 <code className="code-inline">PUT /agents/{agentId}/plugins</code> (整体覆盖),
          并立即按新矩阵同步运行中实例的工具 / 命令 / 注入器 (D5: 绕过 allow/deny
          的旁路已封堵)。allow 决定可见上限, deny 在其上再排除; <code className="code-inline">*</code> 为通配。
        </span>
      </Callout>

      <Card title="plugins_allow" subtitle="允许该 Agent 加载的插件白名单">
        <TagInput
          values={allow}
          onChange={setAllow}
          ariaLabel="插件白名单"
          suggestions={suggestions}
          placeholder="插件名回车添加, * = 全部允许"
        />
      </Card>

      <Card title="plugins_deny" subtitle="在白名单之上再排除的黑名单">
        <TagInput
          values={deny}
          onChange={setDeny}
          ariaLabel="插件黑名单"
          suggestions={suggestions}
          placeholder="插件名回车添加, * = 全部禁止"
        />
      </Card>

      <div className="row row--tight">
        <Button
          variant="primary"
          data-testid="agent-plugin-matrix-save"
          disabled={!dirty || put.isPending}
          loading={put.isPending}
          onClick={() => setConfirmOpen(true)}
        >
          保存插件矩阵
        </Button>
        <Button
          variant="ghost"
          disabled={!dirty}
          onClick={() => {
            setAllow(initial.plugins_allow);
            setDeny(initial.plugins_deny);
          }}
        >
          放弃本地修改
        </Button>
        <span className="small muted">
          {dirty ? "有未保存的修改。" : "与服务端当前矩阵一致。"}
          {loaded.isError ? " (已加载插件清单不可读, 无输入建议)" : ""}
        </span>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title="保存插件矩阵 (整体覆盖)"
        tone="danger"
        impact={
          <span>
            将把 Agent <code className="code-inline">{agentId}</code> 的插件矩阵覆盖为 allow=[
            {allow.join(", ") || "空"}] / deny=[{deny.join(", ") || "空"}],
            并热同步到运行中实例 —— 被移出白名单的插件工具会立即从该 Agent 消失, 进行中的调用不受影响。
          </span>
        }
        confirmLabel="确认覆盖保存"
        loading={put.isPending}
        onConfirm={() => put.mutate({ plugins_allow: allow, plugins_deny: deny }, { onSuccess: () => setConfirmOpen(false) })}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}

/**
 * 插件矩阵 tab: GET /agents/{id}/plugins → 本地编辑 → 覆盖式 PUT (二次确认)。
 * key=服务端形状序列化, 保存成功缓存失效后自动以新值重挂载。
 */
export default function PluginMatrixPanel({ agentId }: { agentId: string }) {
  const matrix = usePluginMatrix(agentId);
  return (
    <QueryState query={matrix}>
      {(data) => <MatrixEditor key={JSON.stringify(data)} agentId={agentId} initial={data} />}
    </QueryState>
  );
}
