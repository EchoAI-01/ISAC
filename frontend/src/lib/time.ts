/** 渲染安全的"当前时间"读取。
 *
 * react-hooks 编译器规则禁止在渲染期间直接调用 Date.now() (不纯函数,
 * 每次渲染结果漂移会导致 query key / 派生值不稳定)。本 hook 用
 * useSyncExternalStore 把墙上时钟建模为外部数据源:
 * - snapshot 按 30s 粒度量化 —— 同一窗口内多次读取返回同值,
 *   满足 getSnapshot 必须可缓存的要求, 不会造成无限重渲染;
 * - 每 30s 通知一次订阅者, 相对时间标签 (formatRelative) 的误差上限即 30s;
 * - 依赖"当前秒数"的查询 (用量窗口等) 最多每 30s 换一次 query key,
 *   刷新频率有界。
 */

import { useSyncExternalStore } from "react";

const GRANULARITY_SECONDS = 30;

function subscribe(onStoreChange: () => void): () => void {
  const id = window.setInterval(onStoreChange, GRANULARITY_SECONDS * 1000);
  return () => window.clearInterval(id);
}

function getSnapshot(): number {
  return Math.floor(Date.now() / 1000 / GRANULARITY_SECONDS) * GRANULARITY_SECONDS;
}

/** 量化到 30s 粒度的当前 epoch 秒 (用于展示与查询窗口, 不用于精确计时)。 */
export function useNowSeconds(): number {
  return useSyncExternalStore(subscribe, getSnapshot);
}
