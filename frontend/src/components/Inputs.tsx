import { useState, type ReactNode } from "react";

import { cn } from "@/lib/cn";
import { Button } from "./Button";
import { useToast } from "./Toast";

/** 工具条 (筛选/分页/操作按钮的横向容器)。 */
export function Toolbar({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("toolbar", className)}>{children}</div>;
}

export interface ToolbarGroupProps {
  label: string;
  children: ReactNode;
  htmlFor?: string;
}

/** 工具条里的一个带标签控件组。 */
export function ToolbarGroup({ label, children, htmlFor }: ToolbarGroupProps) {
  return (
    <div className="toolbar__group">
      <label className="toolbar__label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
    </div>
  );
}

/** 分段控件 (时间范围 / 桶粒度等少量互斥选项)。 */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: Array<{ value: T; label: string }>;
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={ariaLabel}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** 字符串数组编辑器 (trigger_words / plugins_allow / permissions 等)。 */
export function TagInput({
  values,
  onChange,
  placeholder = "输入后回车添加",
  ariaLabel,
  allowWildcard = true,
  suggestions,
}: {
  values: string[];
  onChange: (next: string[]) => void;
  placeholder?: string;
  ariaLabel: string;
  /** 是否允许 `*` 通配 (plugins_allow / commands_allow 语义需要)。 */
  allowWildcard?: boolean;
  suggestions?: string[];
}) {
  const [draft, setDraft] = useState("");
  const inputId = `tag-input-${ariaLabel.replace(/\s+/g, "-").toLowerCase()}`;

  const add = (raw: string) => {
    const value = raw.trim();
    if (!value) return;
    if (value === "*" && !allowWildcard) return;
    if (values.includes(value)) {
      setDraft("");
      return;
    }
    onChange([...values, value]);
    setDraft("");
  };

  const remove = (value: string) => onChange(values.filter((item) => item !== value));

  const missingSuggestions = (suggestions ?? []).filter((item) => !values.includes(item));

  return (
    <div className="stack stack--tight">
      <div className="chip-list" role="list" aria-label={`${ariaLabel} (已选 ${values.length} 项)`}>
        {values.length === 0 ? <span className="small muted">空 (= 不限制或全部拒绝, 见字段说明)</span> : null}
        {values.map((value) => (
          <span className="chip" key={value} role="listitem">
            <span className="mono">{value}</span>
            <button
              type="button"
              onClick={() => remove(value)}
              aria-label={`移除 ${value}`}
              title={`移除 ${value}`}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <div className="row row--tight">
        <input
          id={inputId}
          className="input input--mono grow"
          value={draft}
          placeholder={placeholder}
          aria-label={ariaLabel}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === ",") {
              event.preventDefault();
              add(draft);
            } else if (event.key === "Backspace" && draft === "" && values.length > 0) {
              remove(values[values.length - 1]!);
            }
          }}
        />
        <Button variant="secondary" size="sm" onClick={() => add(draft)} disabled={!draft.trim()}>
          添加
        </Button>
      </div>
      {missingSuggestions.length > 0 ? (
        <div className="row row--tight xs">
          <span className="muted">常用:</span>
          {missingSuggestions.slice(0, 8).map((item) => (
            <button key={item} type="button" className="btn btn--ghost btn--sm" onClick={() => add(item)}>
              + {item}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export interface PaginationProps {
  offset: number;
  limit: number;
  /** 服务端返回的总数; 未知时按"本页是否满"判断有无下一页。 */
  total?: number;
  hasMore?: boolean;
  onChange: (offset: number) => void;
  pageSizeOptions?: number[];
  onPageSizeChange?: (limit: number) => void;
  ariaLabel?: string;
}

/** 分页 (offset/limit 写进 URL, 由页面通过 useUrlState 管理)。 */
export function Pagination({
  offset,
  limit,
  total,
  hasMore,
  onChange,
  pageSizeOptions,
  onPageSizeChange,
  ariaLabel = "分页",
}: PaginationProps) {
  const page = Math.floor(offset / Math.max(1, limit)) + 1;
  const nextAvailable = total !== undefined ? offset + limit < total : (hasMore ?? false);
  return (
    <nav className="pagination" aria-label={ariaLabel}>
      <Button
        variant="secondary"
        size="sm"
        onClick={() => onChange(Math.max(0, offset - limit))}
        disabled={offset <= 0}
      >
        上一页
      </Button>
      <span aria-live="polite">
        第 {page} 页
        {total !== undefined ? ` / 共 ${Math.max(1, Math.ceil(total / Math.max(1, limit)))} 页 (${total} 条)` : ""}
      </span>
      <Button variant="secondary" size="sm" onClick={() => onChange(offset + limit)} disabled={!nextAvailable}>
        下一页
      </Button>
      {pageSizeOptions && onPageSizeChange ? (
        <label className="row row--tight small">
          <span className="muted">每页</span>
          <select
            className="select"
            style={{ width: "auto", minHeight: "1.75rem", padding: "0.15rem 1.6rem 0.15rem 0.4rem" }}
            value={limit}
            onChange={(event) => onPageSizeChange(Number(event.target.value))}
          >
            {pageSizeOptions.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
      ) : null}
    </nav>
  );
}

/** 复制按钮 (审计 id / trace id / 端点路径)。 */
export function CopyButton({ value, label = "复制" }: { value: string; label?: string }) {
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          toast.success("已复制到剪贴板");
          setTimeout(() => setCopied(false), 1500);
        } catch {
          toast.error("复制失败", "浏览器拒绝了剪贴板访问, 请手动选择文本复制。");
        }
      }}
      aria-label={`${label}: ${value}`}
    >
      {copied ? "已复制" : label}
    </Button>
  );
}

export interface JsonEditorProps {
  value: string;
  onChange: (next: string) => void;
  onError?: (message: string | null) => void;
  label: string;
  hint?: ReactNode;
  rows?: number;
  id?: string;
}

/**
 * JSON 编辑器 (深节配置 / persona / gating 等自由结构)。
 *
 * 前端只做**语法**校验, 业务校验一律交给后端 `POST /config/validate`
 * (SPEC §8.2 规则 1: 前端不能复制一套独立校验规则作为唯一真相)。
 */
export function JsonEditor({ value, onChange, onError, label, hint, rows = 10, id }: JsonEditorProps) {
  const [syntaxError, setSyntaxError] = useState<string | null>(null);
  const editorId = id ?? `json-editor-${label.replace(/\s+/g, "-").toLowerCase()}`;

  return (
    <div className="field">
      <label className="field__label" htmlFor={editorId}>
        {label}
      </label>
      {hint ? <span className="field__hint">{hint}</span> : null}
      <textarea
        id={editorId}
        className="textarea textarea--mono"
        rows={rows}
        value={value}
        aria-invalid={syntaxError ? true : undefined}
        aria-describedby={syntaxError ? `${editorId}-error` : undefined}
        spellCheck={false}
        onChange={(event) => {
          const next = event.target.value;
          onChange(next);
          let message: string | null = null;
          if (next.trim() !== "") {
            try {
              JSON.parse(next);
            } catch (error) {
              message = error instanceof Error ? error.message : "JSON 语法错误";
            }
          }
          setSyntaxError(message);
          onError?.(message);
        }}
      />
      {syntaxError ? (
        <span className="field__error" id={`${editorId}-error`} role="alert">
          JSON 语法错误: {syntaxError}
        </span>
      ) : null}
    </div>
  );
}
