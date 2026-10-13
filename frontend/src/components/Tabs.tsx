import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";

import { cn } from "@/lib/cn";

export interface TabItem {
  /** URL 里出现的 tab 值 (?tab=)。 */
  value: string;
  label: ReactNode;
  /** 可选计数徽标 (如待审批数)。 */
  count?: number;
  /** 面板内容 (懒渲染: 仅激活时挂载, 避免十个域同时打请求)。 */
  content: ReactNode;
  /** 该 tab 是否可用 (子系统未启用时禁用并说明)。 */
  disabled?: boolean;
  disabledReason?: string;
}

export interface TabsProps {
  items: TabItem[];
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
  className?: string;
}

/**
 * 标签页 (WAI-ARIA Tabs 模式)。
 *
 * - roving tabindex: 只有激活 tab 可 Tab 聚焦, 左右/Home/End 在 tab 间移动;
 * - 激活即聚焦 (manual activation 会让键盘用户多按一次 Enter, 这里用 automatic);
 * - 面板 role="tabpanel" + aria-labelledby, 未激活面板不渲染 (懒加载请求)。
 */
export function Tabs({ items, value, onChange, ariaLabel, className }: TabsProps) {
  const enabled = items.filter((item) => !item.disabled);
  const active = items.find((item) => item.value === value) ?? enabled[0];
  const tabRefs = useRef(new Map<string, HTMLButtonElement>());

  const move = useCallback(
    (fromIndex: number, delta: number) => {
      if (enabled.length === 0) return;
      const next = (fromIndex + delta + enabled.length) % enabled.length;
      const target = enabled[next];
      if (!target) return;
      onChange(target.value);
      tabRefs.current.get(target.value)?.focus();
    },
    [enabled, onChange],
  );

  const onKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
    switch (event.key) {
      case "ArrowRight":
        event.preventDefault();
        move(index, 1);
        break;
      case "ArrowLeft":
        event.preventDefault();
        move(index, -1);
        break;
      case "Home":
        event.preventDefault();
        move(index, -index);
        break;
      case "End":
        event.preventDefault();
        move(index, enabled.length - 1 - index);
        break;
      default:
        break;
    }
  };

  if (!active) return null;

  return (
    <div className={cn("stack", className)}>
      <div className="tabs" role="tablist" aria-label={ariaLabel}>
        {items.map((item) => {
          const index = enabled.findIndex((candidate) => candidate.value === item.value);
          const selected = item.value === active.value;
          return (
            <button
              key={item.value}
              ref={(node) => {
                if (node) tabRefs.current.set(item.value, node);
                else tabRefs.current.delete(item.value);
              }}
              type="button"
              role="tab"
              id={`tab-${item.value}`}
              aria-selected={selected}
              aria-controls={`tabpanel-${item.value}`}
              tabIndex={selected ? 0 : -1}
              className="tab"
              disabled={item.disabled}
              title={item.disabled ? item.disabledReason : undefined}
              onClick={() => onChange(item.value)}
              onKeyDown={(event) => (index >= 0 ? onKeyDown(event, index) : undefined)}
            >
              {item.label}
              {typeof item.count === "number" ? <span className="tab__count">({item.count})</span> : null}
            </button>
          );
        })}
      </div>
      <div
        role="tabpanel"
        id={`tabpanel-${active.value}`}
        aria-labelledby={`tab-${active.value}`}
        tabIndex={0}
        className="stack"
      >
        {active.content}
      </div>
    </div>
  );
}

/** 受控可见性 + 焦点陷阱 + Esc 关闭的模态框 (WCAG 2.1.2 / 2.4.3)。 */
export interface ModalProps {
  open: boolean;
  title: ReactNode;
  description?: ReactNode;
  onClose: () => void;
  footer?: ReactNode;
  wide?: boolean;
  children: ReactNode;
  /** 初次打开时聚焦的元素选择器 (默认第一个可聚焦元素)。 */
  initialFocus?: string;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function Modal({ open, title, description, onClose, footer, wide, children, initialFocus }: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const restoreFocus = useRef<HTMLElement | null>(null);
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    restoreFocus.current = document.activeElement as HTMLElement | null;
    const node = dialogRef.current;
    if (node) {
      const target = initialFocus ? node.querySelector<HTMLElement>(initialFocus) : null;
      (target ?? node.querySelector<HTMLElement>(FOCUSABLE) ?? node).focus();
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !node) return;
      const focusables = Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (element) => element.offsetParent !== null || element === document.activeElement,
      );
      if (focusables.length === 0) {
        event.preventDefault();
        node.focus();
        return;
      }
      const first = focusables[0]!;
      const last = focusables[focusables.length - 1]!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      restoreFocus.current?.focus?.();
    };
  }, [open, onClose, initialFocus]);

  if (!open) return null;

  return (
    <div className="modal-backdrop" onMouseDown={(event) => (event.target === event.currentTarget ? onClose() : undefined)}>
      <div
        className={cn("modal", wide && "modal--wide")}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? `${titleId}-desc` : undefined}
        ref={dialogRef}
        tabIndex={-1}
      >
        <div className="modal__header">
          <h2 className="modal__title" id={titleId}>
            {title}
          </h2>
          <button type="button" className="btn btn--ghost btn--sm" onClick={onClose} aria-label="关闭对话框">
            ×
          </button>
        </div>
        {description ? (
          <div className="modal__body" id={`${titleId}-desc`} style={{ paddingBottom: 0 }}>
            <p className="small muted">{description}</p>
          </div>
        ) : null}
        <div className="modal__body">{children}</div>
        {footer ? <div className="modal__footer">{footer}</div> : null}
      </div>
    </div>
  );
}

/** 高影响操作二次确认 (SPEC §8.2 规则 2: 删除/停机/解绑/清空记忆/替换 Provider/批量权限)。 */
export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  /** 影响范围说明 (必须具体到会发生什么, 不能只写"确认?")。 */
  impact: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "danger" | "primary";
  /** 要求输入指定文本才能确认 (删除 Agent/租户等不可逆操作)。 */
  requireText?: string;
  onConfirm: () => void;
  onCancel: () => void;
  loading?: boolean;
  children?: ReactNode;
}

export function ConfirmDialog(props: ConfirmDialogProps) {
  // 以 key 重挂载重置 requireText 输入态 (open/title 变化即回到空输入),
  // 替代 effect 里 setState (react-hooks/set-state-in-effect)。
  return <ConfirmDialogInner key={props.open ? `open:${props.title}` : "closed"} {...props} />;
}

function ConfirmDialogInner({
  open,
  title,
  impact,
  confirmLabel = "确认执行",
  cancelLabel = "取消",
  tone = "danger",
  requireText,
  onConfirm,
  onCancel,
  loading,
  children,
}: ConfirmDialogProps) {
  const [typed, setTyped] = useState("");

  const blocked = Boolean(requireText) && typed !== requireText;

  return (
    <Modal
      open={open}
      title={title}
      onClose={onCancel}
      initialFocus={requireText ? "#confirm-text-input" : undefined}
      footer={
        <>
          <button type="button" className="btn btn--secondary" onClick={onCancel} disabled={loading}>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={cn("btn", tone === "danger" && "btn--danger")}
            onClick={onConfirm}
            disabled={blocked || loading}
            aria-disabled={blocked || loading}
          >
            {loading ? "执行中…" : confirmLabel}
          </button>
        </>
      }
    >
      <div className="stack">
        <div className="callout callout--warning">
          <div className="callout__body">
            <div className="callout__title">影响范围</div>
            <div>{impact}</div>
          </div>
        </div>
        {children}
        {requireText ? (
          <label className="field" htmlFor="confirm-text-input">
            <span className="field__label">
              输入 <code className="code-inline">{requireText}</code> 以确认
            </span>
            <input
              id="confirm-text-input"
              className="input input--mono"
              value={typed}
              autoComplete="off"
              onChange={(event) => setTyped(event.target.value)}
              aria-describedby="confirm-text-hint"
            />
            <span className="field__hint" id="confirm-text-hint">
              不可逆操作需要显式确认, 防止误触。
            </span>
          </label>
        ) : null}
      </div>
    </Modal>
  );
}
