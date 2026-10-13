import { useState } from "react";

import { Button } from "@/components/Button";
import { TextField } from "@/components/Form";

/** 表单态: group_id / user_id 用空串表示 null (提交时再转回 null)。 */
export interface BindingDraft {
  platform: string;
  agent_id: string;
  group_id: string;
  user_id: string;
}

export interface DefaultDraft {
  platform: string;
  agent_id: string;
}

/** 绑定规则条目编辑 (添加 / 编辑共用)。 */
export function BindingModalBody({
  initial,
  onSave,
  onClose,
}: {
  initial: BindingDraft;
  onSave: (row: BindingDraft) => void;
  onClose: () => void;
}) {
  const [row, setRow] = useState<BindingDraft>(initial);
  const ok = row.platform.trim() !== "" && row.agent_id.trim() !== "";
  return (
    <div className="stack">
      <TextField
        label="platform"
        hint="渠道平台名, 如 feishu / telegram (与后端注册的 Channel 平台一致)"
        value={row.platform}
        onChange={(e) => setRow({ ...row, platform: e.target.value })}
        mono
      />
      <TextField
        label="agent_id"
        hint="入站消息路由到的 Agent id"
        value={row.agent_id}
        onChange={(e) => setRow({ ...row, agent_id: e.target.value })}
        mono
      />
      <TextField
        label="group_id"
        hint="群组 ID;留空 = 不限群组"
        value={row.group_id}
        onChange={(e) => setRow({ ...row, group_id: e.target.value })}
        mono
      />
      <TextField
        label="user_id"
        hint="用户 ID;留空 = 不限用户"
        value={row.user_id}
        onChange={(e) => setRow({ ...row, user_id: e.target.value })}
        mono
      />
      <div className="row row--tight">
        <Button variant="primary" disabled={!ok} onClick={() => onSave(row)}>
          保存条目
        </Button>
        <Button variant="ghost" onClick={onClose}>
          取消
        </Button>
        {!ok && <span className="small muted">platform 与 agent_id 必填。</span>}
      </div>
    </div>
  );
}

/** 平台默认 Agent 条目编辑 (添加 / 编辑共用)。 */
export function DefaultModalBody({
  initial,
  onSave,
  onClose,
}: {
  initial: DefaultDraft;
  onSave: (row: DefaultDraft) => void;
  onClose: () => void;
}) {
  const [row, setRow] = useState<DefaultDraft>(initial);
  const ok = row.platform.trim() !== "" && row.agent_id.trim() !== "";
  return (
    <div className="stack">
      <TextField
        label="platform"
        hint="渠道平台名;同一平台重复提交时以最后一次编辑为准 (字典键唯一)"
        value={row.platform}
        onChange={(e) => setRow({ ...row, platform: e.target.value })}
        mono
      />
      <TextField
        label="agent_id"
        hint="该平台无匹配绑定时兜底路由的 Agent id"
        value={row.agent_id}
        onChange={(e) => setRow({ ...row, agent_id: e.target.value })}
        mono
      />
      <div className="row row--tight">
        <Button variant="primary" disabled={!ok} onClick={() => onSave(row)}>
          保存条目
        </Button>
        <Button variant="ghost" onClick={onClose}>
          取消
        </Button>
        {!ok && <span className="small muted">platform 与 agent_id 必填。</span>}
      </div>
    </div>
  );
}
