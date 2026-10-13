import { describe, expect, it } from "vitest";

import { apiErrorFrom, classify, errorMessage, errorKind, isApiError, networkError } from "./errors";

/**
 * 统一错误模型测试 (CONTROL_PLANE_SPEC §3.6)。
 *
 * 重点覆盖两个前端必须区分的分支:
 * - 404 带业务 code (AGENT_NOT_FOUND) = 资源不存在;
 * - 404 无业务 code (`{"detail":"Not Found"}`) = 可选子系统未启用、路由未挂载
 *   (api.md "条件挂载") → 页面渲染 unavailable 引导, 而不是"暂无数据"。
 */
describe("classify", () => {
  it("把 401/428/403/409/429 归到各自的语义种类", () => {
    expect(classify(401, true)).toBe("unauthorized");
    expect(classify(428, true)).toBe("setup_required");
    expect(classify(403, true)).toBe("forbidden");
    expect(classify(409, true)).toBe("conflict");
    expect(classify(429, true)).toBe("rate_limited");
  });

  it("404 有业务 code = not_found, 无业务 code = unavailable", () => {
    expect(classify(404, true)).toBe("not_found");
    expect(classify(404, false)).toBe("unavailable");
  });

  it("405 视为 unavailable (端点未挂载时的方法不匹配)", () => {
    expect(classify(405, true)).toBe("unavailable");
  });

  it("400/422 是 validation, 5xx 是 server", () => {
    expect(classify(400, true)).toBe("validation");
    expect(classify(422, false)).toBe("validation");
    expect(classify(500, false)).toBe("server");
    expect(classify(503, false)).toBe("server");
  });
});

describe("apiErrorFrom", () => {
  it("解析契约错误体 {detail:{code,message}}", () => {
    const error = apiErrorFrom(404, { detail: { code: "AGENT_NOT_FOUND", message: "tech_agent" } }, "/api/v1/agents/x");
    expect(error.kind).toBe("not_found");
    expect(error.code).toBe("AGENT_NOT_FOUND");
    expect(error.message).toBe("tech_agent");
    expect(error.path).toBe("/api/v1/agents/x");
    expect(isApiError(error)).toBe(true);
  });

  it("409 CONFIG_CONFLICT 带上服务器 current_revision (乐观锁冲突面板要用)", () => {
    const error = apiErrorFrom(
      409,
      { detail: { code: "CONFIG_CONFLICT", message: "revision mismatch", current_revision: 7 } },
      "/api/v1/agents/x",
    );
    expect(error.kind).toBe("conflict");
    expect(error.currentRevision).toBe(7);
  });

  it("FastAPI 未匹配路由的裸字符串 detail → unavailable", () => {
    const error = apiErrorFrom(404, { detail: "Not Found" }, "/api/v1/usage/models/summary");
    expect(error.kind).toBe("unavailable");
    expect(error.isUnavailable).toBe(true);
    expect(error.message).toBe("Not Found");
  });

  it("403 SCOPE_FORBIDDEN → forbidden 且 isPermissionDenied 为真", () => {
    const error = apiErrorFrom(
      403,
      { detail: { code: "SCOPE_FORBIDDEN", message: "缺少 scope: usage:detail" } },
      "/api/v1/usage/models/events",
    );
    expect(error.kind).toBe("forbidden");
    expect(error.isPermissionDenied).toBe(true);
    expect(error.message).toContain("usage:detail");
  });

  it("422 的数组 detail 归一成可读消息 (含字段路径)", () => {
    const error = apiErrorFrom(
      422,
      { detail: [{ loc: ["body", "password"], msg: "String should have at least 8 characters", type: "string_too_short" }] },
      "/api/v1/setup",
    );
    expect(error.kind).toBe("validation");
    expect(error.message).toContain("password");
    expect(error.message).toContain("at least 8");
  });

  it("空响应体也有可读消息, 不抛二次错误", () => {
    const error = apiErrorFrom(500, null, "/api/v1/agents");
    expect(error.kind).toBe("server");
    expect(error.code).toBe("INTERNAL_ERROR");
    expect(error.message.length).toBeGreaterThan(0);
  });

  it("428 SETUP_REQUIRED 消息指引导向 setup", () => {
    const error = apiErrorFrom(428, { detail: { code: "SETUP_REQUIRED", message: "首登未设置密码" } }, "/api/v1/audit");
    expect(error.kind).toBe("setup_required");
    expect(error.code).toBe("SETUP_REQUIRED");
  });
});

describe("networkError / errorMessage / errorKind", () => {
  it("网络层错误归一为 kind=network 且带原因", () => {
    const error = networkError(new TypeError("Failed to fetch"), "/health");
    expect(error.kind).toBe("network");
    expect(error.status).toBe(0);
    expect(error.message).toContain("Failed to fetch");
    expect(error.path).toBe("/health");
  });

  it("errorMessage 对 ApiError / Error / 裸值都能出可读文本", () => {
    expect(errorMessage(apiErrorFrom(403, { detail: { code: "X", message: "禁止" } }, "/p"))).toBe("禁止");
    expect(errorMessage(new Error("boom"))).toBe("boom");
    expect(errorMessage("plain")).toBe("plain");
  });

  it("errorKind 对非 ApiError 归 unknown", () => {
    expect(errorKind(new Error("boom"))).toBe("unknown");
    expect(errorKind(apiErrorFrom(401, {}, "/p"))).toBe("unauthorized");
  });
});
