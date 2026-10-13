import { useState, type FormEvent } from "react";

import { Button } from "@/components/Button";
import { TextField } from "@/components/Form";
import { SegmentedControl } from "@/components/Inputs";

import { fromLocalInputValue, RANGE_OPTIONS, toLocalInputValue, useUsageUrlState } from "../useUsageUrlState";

interface TextFilters {
  provider: string;
  model: string;
  agent: string;
  modality: string;
  status: string;
}

const EMPTY: TextFilters = { provider: "", model: "", agent: "", modality: "", status: "" };

/**
 * 文本筛选表单 (草稿态)。
 *
 * 父级以 key=当前 URL 值挂载: URL 被外部改动 (提交 / 重置 / 回退 / 分享链接)
 * 时重挂载并以新值初始化草稿 —— 用 React 官方"以 key 重置状态"模式替代
 * effect 里同步 setState (react-hooks/set-state-in-effect)。
 */
function TextFiltersForm({ initial, onApply }: { initial: TextFilters; onApply: (next: TextFilters) => void }) {
  const [draft, setDraft] = useState<TextFilters>(initial);
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    onApply(draft);
  };

  return (
    <form className="row row--wrap" onSubmit={onSubmit} aria-label="用量筛选条件">
      <div style={{ minWidth: "10rem", flex: "1 1 10rem" }}>
        <TextField label="provider" mono value={draft.provider} onChange={(event) => setDraft({ ...draft, provider: event.target.value })} />
      </div>
      <div style={{ minWidth: "10rem", flex: "1 1 10rem" }}>
        <TextField label="model" mono value={draft.model} onChange={(event) => setDraft({ ...draft, model: event.target.value })} />
      </div>
      <div style={{ minWidth: "10rem", flex: "1 1 10rem" }}>
        <TextField label="agent_id" mono value={draft.agent} onChange={(event) => setDraft({ ...draft, agent: event.target.value })} />
      </div>
      <div style={{ minWidth: "10rem", flex: "1 1 10rem" }}>
        <TextField label="modality" mono hint="text / audio / image / video" value={draft.modality} onChange={(event) => setDraft({ ...draft, modality: event.target.value })} />
      </div>
      <div style={{ minWidth: "10rem", flex: "1 1 10rem" }}>
        <TextField label="status" mono hint="ok / error / fallback 等" value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })} />
      </div>
      <div className="row row--tight" style={{ alignItems: "flex-end" }}>
        <Button variant="primary" size="sm" type="submit" data-testid="usage-filters-apply" disabled={!dirty}>
          应用筛选
        </Button>
        <Button variant="ghost" size="sm" type="button" onClick={() => onApply(EMPTY)} disabled={JSON.stringify(initial) === JSON.stringify(EMPTY) && !dirty}>
          重置
        </Button>
      </div>
    </form>
  );
}

/**
 * 时间范围 + 五个文本筛选 (provider / model / agent_id / modality / status)。
 *
 * 全部写 URL。时间范围是离散选择, 直接写; 文本筛选用草稿态, 提交才写回 URL ——
 * 避免每次按键都改 query key 打一次后端 (与 AuditExplorer 同一模式)。
 */
export default function UsageFilters() {
  const state = useUsageUrlState();

  const initial: TextFilters = {
    provider: state.provider,
    model: state.model,
    agent: state.agent,
    modality: state.modality,
    status: state.status,
  };

  return (
    <div className="stack" data-testid="usage-filters">
      <div className="row row--tight" style={{ flexWrap: "wrap" }}>
        <span className="toolbar__label" id="usage-range-label">
          时间范围
        </span>
        <SegmentedControl
          ariaLabel="用量时间范围"
          options={RANGE_OPTIONS.map((value) => ({ value, label: value === "custom" ? "自定义" : value }))}
          value={state.range}
          onChange={state.setRange}
        />
        {state.range === "custom" ? (
          <span className="row row--tight">
            <input
              type="datetime-local"
              className="input"
              aria-label="起始时间"
              value={toLocalInputValue(state.from)}
              max={toLocalInputValue(state.to)}
              onChange={(event) => {
                const sec = fromLocalInputValue(event.target.value);
                if (sec !== null) state.setCustomFrom(sec);
              }}
            />
            <span aria-hidden>→</span>
            <input
              type="datetime-local"
              className="input"
              aria-label="结束时间"
              value={toLocalInputValue(state.to)}
              min={toLocalInputValue(state.from)}
              onChange={(event) => {
                const sec = fromLocalInputValue(event.target.value);
                if (sec !== null) state.setCustomTo(sec);
              }}
            />
          </span>
        ) : null}
      </div>

      <TextFiltersForm
        key={`${initial.provider}|${initial.model}|${initial.agent}|${initial.modality}|${initial.status}`}
        initial={initial}
        onApply={state.applyTextFilters}
      />
    </div>
  );
}
