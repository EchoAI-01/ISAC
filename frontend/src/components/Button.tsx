import { type ButtonHTMLAttributes, forwardRef } from "react";

import { cn } from "@/lib/cn";

export type ButtonVariant = "primary" | "secondary" | "danger" | "ghost";
export type ButtonSize = "md" | "sm";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** 进行中: 显示 spinner 并自动 disabled (防止重复提交写操作)。 */
  loading?: boolean;
  /** 图标按钮必须给 accessibleName (WCAG 4.1.2)。 */
  accessibleName?: string;
}

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: "",
  secondary: "btn--secondary",
  danger: "btn--danger",
  ghost: "btn--ghost",
};

/** 按钮 (统一尺寸/变体/加载态; 写操作在 loading 期间禁用防重复提交)。 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", size = "md", loading = false, accessibleName, className, children, disabled, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn("btn", VARIANT_CLASS[variant], size === "sm" && "btn--sm", !children && "btn--icon", className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      aria-label={accessibleName}
      {...rest}
    >
      {loading ? <Spinner className="btn__spinner" /> : null}
      {children}
    </button>
  );
});

/** 内联 spinner (按钮/状态视图共用)。 */
export function Spinner({ className, label }: { className?: string; label?: string }) {
  return (
    <span
      className={cn("spinner", className)}
      role={label ? "status" : undefined}
      aria-label={label}
    >
      {label ? <span className="sr-only">{label}</span> : null}
    </span>
  );
}
