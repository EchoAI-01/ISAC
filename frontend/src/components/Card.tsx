import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  title?: ReactNode;
  subtitle?: ReactNode;
  /** 头部右侧操作区 (按钮/筛选)。 */
  actions?: ReactNode;
  /** body 是否去掉内边距 (表格贴边时用)。 */
  flush?: boolean;
  footer?: ReactNode;
}

/** 卡片容器 (十域页面的统一分区单元)。 */
export function Card({ title, subtitle, actions, flush, footer, className, children, ...rest }: CardProps) {
  const hasHeader = title !== undefined || actions !== undefined;
  return (
    <section className={cn("card", className)} {...rest}>
      {hasHeader ? (
        <header className="card__header">
          <div className="grow">
            {title ? <h2 className="card__title">{title}</h2> : null}
            {subtitle ? <p className="card__subtitle">{subtitle}</p> : null}
          </div>
          {actions ? <div className="row row--tight">{actions}</div> : null}
        </header>
      ) : null}
      <div className={cn("card__body", flush && "card__body--flush")}>{children}</div>
      {footer ? <footer className="card__footer">{footer}</footer> : null}
    </section>
  );
}

export interface PageHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}

/** 页面标题区 (十域统一; h1 由 Shell 提供, 这里用 h1 语义)。 */
export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <div className="page-header">
      <div className="page-header__text">
        <h1 className="page-header__title">{title}</h1>
        {description ? <p className="page-header__desc">{description}</p> : null}
      </div>
      {actions ? <div className="page-header__actions">{actions}</div> : null}
    </div>
  );
}

export type CalloutTone = "info" | "warning" | "danger" | "success";

export interface CalloutProps {
  tone?: CalloutTone;
  title?: ReactNode;
  children?: ReactNode;
  className?: string;
}

/** 提示条 (权限说明 / 后端限制说明 / 高影响变更提醒)。 */
export function Callout({ tone = "info", title, children, className }: CalloutProps) {
  return (
    <div className={cn("callout", `callout--${tone}`, className)} role={tone === "danger" ? "alert" : undefined}>
      <div className="callout__body">
        {title ? <div className="callout__title">{title}</div> : null}
        {children}
      </div>
    </div>
  );
}
