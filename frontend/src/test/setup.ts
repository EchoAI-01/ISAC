import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

// jsdom 未实现 matchMedia (主题解析与 useSse 之外的响应式判断都依赖它)。
if (typeof window !== "undefined" && !window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
}

// jsdom 未实现 ResizeObserver / IntersectionObserver (部分组件库会探测)。
class ObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords() {
    return [];
  }
}
if (typeof globalThis.ResizeObserver === "undefined") {
  Object.defineProperty(globalThis, "ResizeObserver", { writable: true, value: ObserverStub });
}

// 剪贴板 (CopyButton) 在 jsdom 下不存在。
if (typeof navigator !== "undefined" && !navigator.clipboard) {
  Object.defineProperty(navigator, "clipboard", {
    writable: true,
    value: { writeText: vi.fn(async () => undefined), readText: vi.fn(async () => "") },
  });
}

beforeEach(() => {
  // 每个用例从干净 Cookie / 存储开始 (认证态测试尤其需要)。
  if (typeof document !== "undefined") document.cookie = "";
  if (typeof window !== "undefined") {
    window.localStorage.clear();
    window.sessionStorage.clear();
  }
});

afterEach(() => {
  cleanup();
});
