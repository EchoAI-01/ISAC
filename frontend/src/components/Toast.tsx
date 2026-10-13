import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { cn } from "@/lib/cn";
import { Button } from "./Button";

export type ToastTone = "info" | "success" | "warning" | "error";

export interface ToastItem {
  id: number;
  tone: ToastTone;
  title: string;
  description?: string;
  /** 0 = 不自动关闭 (错误类默认停留, 由用户关闭)。 */
  duration: number;
}

export interface ToastInput {
  tone?: ToastTone;
  title: string;
  description?: string;
  duration?: number;
}

interface ToastContextValue {
  push: (toast: ToastInput) => number;
  dismiss: (id: number) => void;
  success: (title: string, description?: string) => number;
  error: (title: string, description?: string) => number;
  info: (title: string, description?: string) => number;
  warning: (title: string, description?: string) => number;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const DEFAULT_DURATION: Record<ToastTone, number> = {
  info: 4000,
  success: 3200,
  warning: 8000,
  // 错误必须停留: 写操作失败需要用户读完原因 (自动消失会导致重复提交)。
  error: 0,
};

/** Toast 提供者 (全局写操作反馈; role=status 播报, 错误用 role=alert)。 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const push = useCallback(
    (input: ToastInput) => {
      const tone = input.tone ?? "info";
      const id = nextId.current++;
      const duration = input.duration ?? DEFAULT_DURATION[tone];
      setToasts((current) => [...current.slice(-4), { id, tone, title: input.title, description: input.description, duration }]);
      if (duration > 0) {
        timers.current.set(
          id,
          setTimeout(() => dismiss(id), duration),
        );
      }
      return id;
    },
    [dismiss],
  );

  useEffect(() => {
    const map = timers.current;
    return () => {
      for (const timer of map.values()) clearTimeout(timer);
      map.clear();
    };
  }, []);

  const value = useMemo<ToastContextValue>(
    () => ({
      push,
      dismiss,
      success: (title, description) => push({ tone: "success", title, description }),
      error: (title, description) => push({ tone: "error", title, description }),
      info: (title, description) => push({ tone: "info", title, description }),
      warning: (title, description) => push({ tone: "warning", title, description }),
    }),
    [push, dismiss],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" aria-live="polite" aria-relevant="additions text">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cn("toast", `toast--${toast.tone}`)}
            role={toast.tone === "error" ? "alert" : "status"}
            data-testid={`toast-${toast.tone}`}
          >
            <div className="toast__body">
              <div className="toast__title">{toast.title}</div>
              {toast.description ? <div className="toast__desc">{toast.description}</div> : null}
            </div>
            <Button variant="ghost" size="sm" accessibleName="关闭提示" onClick={() => dismiss(toast.id)}>
              ×
            </Button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

/** 取用 Toast (未在 Provider 内时返回静默实现, 便于单元测试)。 */
export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (context) return context;
  return {
    push: () => 0,
    dismiss: () => undefined,
    success: () => 0,
    error: () => 0,
    info: () => 0,
    warning: () => 0,
  };
}
