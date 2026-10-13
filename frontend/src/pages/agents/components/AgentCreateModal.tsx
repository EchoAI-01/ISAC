import { useState } from "react";

import { Button } from "@/components/Button";
import { Callout } from "@/components/Card";
import { TextField } from "@/components/Form";
import { TagInput } from "@/components/Inputs";
import { Modal } from "@/components/Tabs";
import { useCreateAgent } from "@/hooks/mutations";

/**
 * 创建 Agent 对话框。
 *
 * 只收集 agent_id / display_name / trigger_words —— 后端创建路径强制套用
 * 受限默认模板 (routes_agents `restricted_config_from_payload`, CR3-L1):
 * payload 里夹带的能力字段会被丢弃, 必须创建后在详情页配置 tab 显式授予。
 * 这一点在表单里明示, 避免用户以为创建时能直接配能力。
 */
export default function AgentCreateModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [agentId, setAgentId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [triggerWords, setTriggerWords] = useState<string[]>([]);
  const create = useCreateAgent();

  const idTrimmed = agentId.trim();
  const ok = idTrimmed !== "";

  const reset = () => {
    setAgentId("");
    setDisplayName("");
    setTriggerWords([]);
  };

  const submit = () => {
    if (!ok) return;
    create.mutate(
      {
        agent_id: idTrimmed,
        ...(displayName.trim() !== "" ? { display_name: displayName.trim() } : {}),
        ...(triggerWords.length > 0 ? { trigger_words: triggerWords } : {}),
      },
      {
        onSuccess: () => {
          reset();
          onClose();
        },
      },
    );
  };

  return (
    <Modal
      open={open}
      title="创建 Agent"
      description="新 Agent 以后端受限默认模板创建; 能力 (工具 / 插件 / MCP / 命令) 一律默认最小化, 创建后再显式授予。"
      onClose={() => {
        if (create.isPending) return;
        reset();
        onClose();
      }}
      footer={
        <>
          <Button variant="secondary" onClick={() => { reset(); onClose(); }} disabled={create.isPending}>
            取消
          </Button>
          <Button variant="primary" data-testid="agents-create-submit" onClick={submit} disabled={!ok} loading={create.isPending}>
            创建
          </Button>
        </>
      }
    >
      <div className="stack">
        <Callout tone="warning" title="创建走受限默认模板 (后端强制)">
          <div className="stack stack--tight small">
            <p style={{ margin: 0 }}>
              即使在请求里携带 <code className="code-inline">tools_policy</code> /{" "}
              <code className="code-inline">plugins_allow</code> / <code className="code-inline">plugins_deny</code> /{" "}
              <code className="code-inline">commands_allow</code> / <code className="code-inline">mcp_servers</code>,
              后端也会<strong>丢弃这些能力字段</strong>并按最小权限模板落盘。
            </p>
            <p style={{ margin: 0 }}>
              需要放开能力时, 请创建完成后进入 <em>详情 → 配置</em> tab, 走"校验 → Diff → 确认 → PATCH"事务显式授予。
            </p>
          </div>
        </Callout>

        <TextField
          label="agent_id"
          required
          mono
          hint="唯一标识, 创建后不可改 (也是默认的记忆命名空间)"
          value={agentId}
          onChange={(event) => setAgentId(event.target.value)}
        />
        <TextField
          label="display_name"
          hint="展示名; 留空则使用 agent_id"
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
        />
        <div>
          <span className="field__label" id="create-trigger-words-label">
            trigger_words
          </span>
          <TagInput
            values={triggerWords}
            onChange={setTriggerWords}
            ariaLabel="触发词"
            allowWildcard={false}
            placeholder="群聊里触发该 Agent 的关键词, 回车添加"
          />
          <span className="field__hint">留空 = 不配置触发词 (私聊仍可直接对话)。</span>
        </div>
      </div>
    </Modal>
  );
}
