import type { ReactNode } from "react";

import { ErrorBoundaryState, LoadingState } from "./StateViews";

/** TanStack Query 结果的最小结构面 (便于测试传替身)。 */
export interface QueryLike<T> {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  data: T | undefined;
  isFetching: boolean;
  refetch: () => unknown;
}

export interface QueryStateProps<T> {
  query: QueryLike<T>;
  children: (data: T) => ReactNode;
  /** 判定"有响应但无内容", 渲染 empty 而不是空白区。 */
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  loadingLabel?: string;
  /** 正在后台刷新且已有旧数据时显示 stale 提示 (SPEC §8.5 stale 态)。 */
  showStale?: boolean;
  staleLabel?: ReactNode;
}

/**
 * 查询态包装器: loading / error(含 permission-denied、unavailable) / empty / stale / data
 * 五态一处收口, 页面不再重复写 `if (isLoading) return …`。
 */
export function QueryState<T>({
  query,
  children,
  isEmpty,
  empty,
  loadingLabel = "加载中…",
  showStale = true,
  staleLabel = "正在刷新…",
}: QueryStateProps<T>) {
  if (query.isPending) {
    return <LoadingState label={loadingLabel} />;
  }

  if (query.isError) {
    return <ErrorBoundaryState error={query.error} onRetry={() => void query.refetch()} retrying={query.isFetching} />;
  }

  const data = query.data as T;
  if (isEmpty?.(data)) {
    return <>{empty ?? null}</>;
  }

  return (
    <div aria-busy={query.isFetching || undefined}>
      {showStale && query.isFetching ? (
        <div className="row row--tight small muted" role="status" style={{ marginBottom: "var(--space-2)" }}>
          <span className="spinner" aria-hidden="true" />
          <span>{staleLabel}</span>
        </div>
      ) : null}
      {children(data)}
    </div>
  );
}
