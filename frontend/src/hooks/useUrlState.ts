import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * URL 状态 (CONTROL_PLANE_SPEC §8.5: 筛选/分页写入 URL)。
 *
 * 所有列表页的筛选、分页、tab 都经这里读写 search params:
 * - 可分享 / 可收藏 / 刷新不丢状态;
 * - 浏览器前进后退即筛选历史;
 * - e2e 与手工验收能直接用 URL 复现某个视图。
 */

function useSetter() {
  const [params, setParams] = useSearchParams();
  const set = useCallback(
    (patch: Record<string, string | number | boolean | null | undefined>) => {
      const next = new URLSearchParams(params);
      for (const [key, value] of Object.entries(patch)) {
        if (value === null || value === undefined || value === "") next.delete(key);
        else next.set(key, String(value));
      }
      // replace: 输入框逐字变化不污染历史栈 (下拉/分页用 push 由调用方决定)。
      setParams(next, { replace: true });
    },
    [params, setParams],
  );
  return [params, set] as const;
}

/** 字符串筛选值 (缺省返回 fallback, 不写入 URL)。 */
export function useUrlString(key: string, fallback = ""): [string, (value: string) => void] {
  const [params, set] = useSetter();
  const value = params.get(key) ?? fallback;
  return [value, useCallback((next: string) => set({ [key]: next || null }), [key, set])];
}

/** 整数筛选/分页值 (非法输入回落 fallback)。 */
export function useUrlNumber(key: string, fallback: number): [number, (value: number) => void] {
  const [params, set] = useSetter();
  const raw = params.get(key);
  const parsed = raw === null ? NaN : Number.parseInt(raw, 10);
  const value = Number.isFinite(parsed) ? parsed : fallback;
  return [
    value,
    useCallback(
      (next: number) => set({ [key]: Number.isFinite(next) && next !== fallback ? next : null }),
      [key, fallback, set],
    ),
  ];
}

/** 枚举筛选值 (限定候选, 非法值回落 fallback)。 */
export function useUrlEnum<T extends string>(key: string, allowed: readonly T[], fallback: T): [T, (value: T) => void] {
  const [params, set] = useSetter();
  const raw = params.get(key) as T | null;
  const value = raw !== null && allowed.includes(raw) ? raw : fallback;
  return [
    value,
    useCallback((next: T) => set({ [key]: next === fallback ? null : next }), [key, fallback, set]),
  ];
}

/** 布尔筛选值。 */
export function useUrlBoolean(key: string, fallback = false): [boolean, (value: boolean) => void] {
  const [params, set] = useSetter();
  const raw = params.get(key);
  const value = raw === null ? fallback : raw === "true" || raw === "1";
  return [value, useCallback((next: boolean) => set({ [key]: next === fallback ? null : next }), [key, fallback, set])];
}

/** tab 参数 (?tab=), 限定合法值。 */
export function useUrlTab(allowed: readonly string[], fallback: string): [string, (value: string) => void] {
  return useUrlEnum("tab", allowed, fallback);
}

/** 当前 search params 的稳定快照 (作为 query key 的一部分)。 */
export function useSearchSnapshot(): string {
  const [params] = useSearchParams();
  return useMemo(() => params.toString(), [params]);
}
