import { useState } from "react";

import { isRedacted } from "@/api/agents";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Callout } from "@/components/Card";
import { TextField } from "@/components/Form";
import { JsonEditor } from "@/components/Inputs";
import { prettyJson } from "@/lib/format";

/** llm 节去掉 api_key 的其余键 (编辑器只展示这部分, 哨兵永不进输入框)。 */
function restOf(value: Record<string, unknown>): Record<string, unknown> {
  const next = { ...value };
  delete next.api_key;
  return next;
}

/**
 * llm 节编辑器 (Record<string, unknown> | null)。
 *
 * api_key 哨兵规则 (SPEC §8.2 规则 4/5):
 * - GET 回显是 `__ISAC_REDACTED__` 哨兵 → 只显示"已配置" Badge, 永不回显原文;
 * - 回传哨兵 = 未修改 (后端剥离后沿用原值);
 * - "替换" = 输入新值随 PATCH 提交; "清除" = 从 llm 节里移除 api_key 键
 *   (PATCH 对顶层字段整体覆盖, 移除即清除)。
 *
 * 其余键 (model / base_url / temperature …) 用 JSON 编辑器整体维护。
 * 外部基线变化 (冲突重放 / 放弃变更) 由父级用 key 重挂载本组件同步。
 */
export default function LlmConfigEditor({
  value,
  onChange,
}: {
  value: Record<string, unknown> | null;
  onChange: (next: Record<string, unknown> | null) => void;
}) {
  const [replacing, setReplacing] = useState(false);
  const [replacement, setReplacement] = useState("");
  const [text, setText] = useState(() => (value === null ? "{}" : prettyJson(restOf(value))));

  if (value === null) {
    return (
      <div className="stack stack--tight" data-testid="agent-config-llm">
        <Callout tone="info" title="llm = null (继承全局)">
          <span className="small">
            该 Agent 未覆写 LLM 配置, 运行时继承全局 <code className="code-inline">llm</code> 节
            (provider / model / api_key 等)。需要按 Agent 指定模型或凭据时, 点击下方按钮建立覆写。
          </span>
        </Callout>
        <div className="row row--tight">
          <Button variant="secondary" size="sm" onClick={() => onChange({})}>
            建立按 Agent 覆写
          </Button>
        </div>
      </div>
    );
  }

  const apiKey = value.api_key;
  const redacted = isRedacted(apiKey);
  const hasKey = apiKey !== undefined && apiKey !== null && apiKey !== "";

  /** 用编辑器里的其余键 + api_key 现状 (或替换值) 合成新的 llm 节。 */
  const emit = (nextRest: Record<string, unknown>, nextReplacement = replacement) => {
    const next: Record<string, unknown> = { ...nextRest };
    if (nextReplacement.trim() !== "") next.api_key = nextReplacement;
    else if (apiKey !== undefined) next.api_key = apiKey; // 哨兵原样回传 = 未修改
    onChange(next);
  };

  /** 当前编辑器文本能解析成对象则用之, 否则退回服务端键集 (去 api_key)。 */
  const currentRest = (): Record<string, unknown> => {
    try {
      const parsed: unknown = JSON.parse(text);
      if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>;
      }
    } catch {
      // 非法 JSON: 不吞编辑器状态, 用最近一次有效值兜底。
    }
    return restOf(value);
  };

  return (
    <div className="stack" data-testid="agent-config-llm">
      <div className="row row--between" style={{ flexWrap: "wrap", gap: "0.5rem" }}>
        <div className="row row--tight">
          <span className="small muted">api_key:</span>
          {redacted ? (
            <Badge tone="success" title="服务端已配置, 回显为脱敏哨兵">
              已配置
            </Badge>
          ) : hasKey ? (
            <Badge tone="warning" title="本地新填的值, 提交前仅存在于表单状态">
              本次将写入新值
            </Badge>
          ) : (
            <Badge>未配置</Badge>
          )}
        </div>
        <div className="row row--tight">
          {hasKey ? (
            <>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setReplacing((current) => !current);
                  setReplacement("");
                }}
              >
                {replacing ? "取消替换" : "替换"}
              </Button>
              <Button
                variant="danger"
                size="sm"
                data-testid="agent-config-llm-clear-key"
                onClick={() => {
                  setReplacing(false);
                  setReplacement("");
                  onChange(currentRest());
                }}
              >
                清除
              </Button>
            </>
          ) : (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                setReplacing(true);
                setReplacement("");
              }}
            >
              设置 api_key
            </Button>
          )}
        </div>
      </div>

      {replacing ? (
        <TextField
          label="新的 api_key"
          type="password"
          mono
          hint="只写不留: 不会存入 localStorage, 提交后服务端脱敏保存, 页面永不回显原文"
          value={replacement}
          onChange={(event) => {
            const next = event.target.value;
            setReplacement(next);
            emit(currentRest(), next);
          }}
        />
      ) : null}

      <JsonEditor
        label="LLM 参数 (不含 api_key)"
        hint='整个 llm 节的其余键, 如 {"model": "...", "base_url": "...", "temperature": 0.7}; 保存时整节覆盖'
        rows={8}
        value={text}
        onChange={(next) => {
          setText(next);
          try {
            const parsed: unknown = JSON.parse(next);
            if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) {
              emit(parsed as Record<string, unknown>);
            }
          } catch {
            // 语法错误由 JsonEditor 自身提示, 不向草稿传播半成品。
          }
        }}
      />
    </div>
  );
}
