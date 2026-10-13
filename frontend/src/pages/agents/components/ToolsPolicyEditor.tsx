import { useState } from "react";

import { Button } from "@/components/Button";
import { TextField } from "@/components/Form";
import { Table, type Column } from "@/components/Table";

/** tools_policy 的合法档位 (其余值后端 400 INVALID_CONFIG)。 */
const POLICIES = ["allow", "restricted", "ask", "deny"] as const;

interface PolicyRow {
  tool: string;
  policy: string;
}

/**
 * tools_policy 编辑器 (Record<工具名, 档位>)。
 *
 * 四档语义: allow = 直接放行; restricted = 受策略限制; ask = 每次调用前走
 * HITL 审批 (Sessions & Tasks 域的"审批" tab 裁决); deny = 拒绝。
 * 前端不复制校验规则 —— 非法档位由后端 POST /config/validate 拒绝并原样回显。
 */
export default function ToolsPolicyEditor({
  value,
  onChange,
}: {
  value: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
}) {
  const [newTool, setNewTool] = useState("");

  const rows: PolicyRow[] = Object.entries(value).map(([tool, policy]) => ({ tool, policy }));

  const setPolicy = (tool: string, policy: string) => {
    onChange({ ...value, [tool]: policy });
  };

  const removeTool = (tool: string) => {
    const next = { ...value };
    delete next[tool];
    onChange(next);
  };

  const addTool = () => {
    const tool = newTool.trim();
    if (tool === "" || tool in value) return;
    onChange({ ...value, [tool]: "deny" });
    setNewTool("");
  };

  const columns: Array<Column<PolicyRow>> = [
    { key: "tool", header: "工具名", label: "工具名", render: (row) => <code className="code-inline">{row.tool}</code> },
    {
      key: "policy",
      header: "档位",
      label: "档位",
      render: (row) => (
        <select
          className="select"
          aria-label={`${row.tool} 的工具策略档位`}
          value={POLICIES.includes(row.policy as (typeof POLICIES)[number]) ? row.policy : ""}
          onChange={(event) => setPolicy(row.tool, event.target.value)}
        >
          {!POLICIES.includes(row.policy as (typeof POLICIES)[number]) ? (
            <option value="" disabled>
              {row.policy} (非法档位, 请重选)
            </option>
          ) : null}
          {POLICIES.map((policy) => (
            <option key={policy} value={policy}>
              {policy}
            </option>
          ))}
        </select>
      ),
    },
    {
      key: "actions",
      header: "操作",
      label: "操作",
      render: (row) => (
        <Button variant="ghost" size="sm" accessibleName={`移除 ${row.tool} 的策略`} onClick={() => removeTool(row.tool)}>
          移除
        </Button>
      ),
    },
  ];

  return (
    <div className="stack stack--tight" data-testid="agent-config-tools-policy">
      <Table
        ariaLabel="tools_policy 工具策略表"
        compact
        columns={columns}
        rows={rows}
        rowKey={(row) => row.tool}
        empty={
          <p className="small muted">
            未配置任何工具策略。未列出的工具按后端默认策略处理; ask 档的工具调用会进入 HITL 审批队列。
          </p>
        }
      />
      <div className="row row--tight">
        <div style={{ minWidth: "16rem" }} className="grow">
          <TextField
            label="添加工具"
            mono
            hint="支持 * 通配 (如 shell_*); 新条目默认 deny 档"
            value={newTool}
            onChange={(event) => setNewTool(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                addTool();
              }
            }}
          />
        </div>
        <Button variant="secondary" size="sm" onClick={addTool} disabled={newTool.trim() === "" || newTool.trim() in value}>
          添加
        </Button>
      </div>
      {newTool.trim() !== "" && newTool.trim() in value ? (
        <p className="small muted">该工具已在列表中, 直接修改其档位即可。</p>
      ) : null}
    </div>
  );
}
