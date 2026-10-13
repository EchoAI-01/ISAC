import { useState } from "react";

import { CheckboxField } from "@/components/Form";
import { ConfirmDialog } from "@/components/Tabs";
import { useAgentLifecycle } from "@/hooks/mutations";

interface DestroyDialogProps {
  agentId: string | null;
  onClose: () => void;
  /** 销毁成功后的额外动作 (详情页用于跳回列表)。 */
  onDestroyed?: () => void;
}

/**
 * 销毁 Agent 二次确认 (不可逆 → requireText = agent_id)。
 *
 * keep_memory 语义 (SPEC §3.1):
 * - true (默认): 只销毁运行时实例与注册表条目, 记忆数据保留;
 * - false: 一并清理该 Agent 命名空间下的 episodes / profiles / jargon、
 *   向量库条目与 graph 边; `memory_namespace=shared` 时后端**拒绝**清理
 *   (共享命名空间不属于单个 Agent)。
 *
 * 外层按 agentId 用 key 重挂载内层: 换一个目标 Agent 时 keep_memory
 * 自动回到保守默认 true (React 官方"以 key 重置状态"模式, 不在 effect 里 setState)。
 */
export default function AgentDestroyDialog(props: DestroyDialogProps) {
  return <DestroyDialogInner key={props.agentId ?? "none"} {...props} />;
}

function DestroyDialogInner({ agentId, onClose, onDestroyed }: DestroyDialogProps) {
  const [keepMemory, setKeepMemory] = useState(true);
  const lifecycle = useAgentLifecycle();

  return (
    <ConfirmDialog
      open={agentId !== null}
      title={agentId ? `销毁 Agent: ${agentId}` : "销毁 Agent"}
      tone="danger"
      requireText={agentId ?? ""}
      confirmLabel="销毁 Agent"
      loading={lifecycle.destroy.isPending}
      impact={
        <div className="stack stack--tight">
          <p style={{ margin: 0 }}>
            销毁会移除该 Agent 的运行时实例与注册表条目, <strong>不可撤销</strong>;
            路由规则里指向它的绑定将失效, 进行中的会话与 SubAgent 任务会被终止。
          </p>
          <p style={{ margin: 0 }}>
            不保留记忆时还会清理该命名空间下的 episodes / 人物画像 / 行话、向量库条目与记忆图 (graph) 边;
            若该 Agent 使用共享命名空间 (<code className="code-inline">memory_namespace=shared</code>),
            后端会<strong>拒绝</strong>清理共享记忆 (只销毁实例)。
          </p>
        </div>
      }
      onConfirm={() => {
        if (!agentId) return;
        lifecycle.destroy.mutate(
          { id: agentId, keepMemory },
          {
            onSuccess: () => {
              onClose();
              onDestroyed?.();
            },
          },
        );
      }}
      onCancel={onClose}
    >
      <CheckboxField
        label="保留记忆数据 (keep_memory=true)"
        hint="取消勾选 = 销毁时一并清理该 Agent 命名空间的记忆 (共享命名空间除外, 后端拒绝清理)"
        checked={keepMemory}
        onChange={(event) => setKeepMemory(event.target.checked)}
      />
    </ConfirmDialog>
  );
}
