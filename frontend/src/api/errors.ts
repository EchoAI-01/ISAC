/** 统一错误模型 (CONTROL_PLANE_SPEC §3.6: `{"detail": {"code", "message"}}`)。
 *
 * 前端把 HTTP 状态 + 业务 code 归一成 `ApiErrorKind`, 页面据此渲染五种状态之一:
 * loading / empty / error / permission-denied / unavailable (子系统未启用),
 * 而不是各自解析 detail 字符串。
 */

/** 结构化错误体 (契约形状)。 */
export interface ApiErrorDetail {
  code?: string;
  message?: string;
  /** 409 CONFIG_CONFLICT 附带服务器当前 revision (乐观锁冲突面板要用)。 */
  current_revision?: number;
  [key: string]: unknown;
}

export type ApiErrorKind =
  /** 401: 未认证 / 凭据失效 → 跳登录。 */
  | "unauthorized"
  /** 403 SCOPE_FORBIDDEN / CSRF_REQUIRED / TENANT_FORBIDDEN → permission-denied 状态。 */
  | "forbidden"
  /** 428 SETUP_REQUIRED → 跳首登向导。 */
  | "setup_required"
  /** 409 CONFIG_CONFLICT → 冲突面板 (服务器版本 vs 本地变更), 不静默覆盖。 */
  | "conflict"
  /** 404 且带业务 code (AGENT_NOT_FOUND 等) → 资源不存在。 */
  | "not_found"
  /** 404 无业务 code / 405: 可选子系统未启用, 路由未挂载 → unavailable 状态。 */
  | "unavailable"
  /** 400 / 422: 入参或配置校验失败。 */
  | "validation"
  /** 429 / TOO_MANY_CONNECTIONS: 限流。 */
  | "rate_limited"
  /** 5xx。 */
  | "server"
  /** 网络不可达 / 解析失败。 */
  | "network"
  | "unknown";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly kind: ApiErrorKind;
  readonly detail: ApiErrorDetail | string | null;
  readonly path: string;

  constructor(opts: {
    status: number;
    kind: ApiErrorKind;
    code: string;
    message: string;
    detail?: ApiErrorDetail | string | null;
    path?: string;
  }) {
    super(opts.message);
    this.name = "ApiError";
    this.status = opts.status;
    this.kind = opts.kind;
    this.code = opts.code;
    this.detail = opts.detail ?? null;
    this.path = opts.path ?? "";
  }

  /** 冲突时服务器当前 revision (PATCH If-Match 409 携带)。 */
  get currentRevision(): number | undefined {
    const detail = this.detail;
    if (detail && typeof detail === "object") {
      const value = detail.current_revision;
      return typeof value === "number" ? value : undefined;
    }
    return undefined;
  }

  /** 权限类错误 (页面渲染 permission-denied 而非通用 error)。 */
  get isPermissionDenied(): boolean {
    return this.kind === "forbidden";
  }

  /** 子系统未启用 (可选路由未挂载), 页面渲染 unavailable 引导而非报错。 */
  get isUnavailable(): boolean {
    return this.kind === "unavailable";
  }
}

/** 422 (FastAPI 请求体校验) 的 detail 是数组, 归一成可读消息。 */
function stringifyFastApiValidation(detail: unknown): string {
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === "object") {
          const record = item as { loc?: unknown[]; msg?: string };
          const loc = Array.isArray(record.loc)
            ? record.loc.filter((part) => part !== "body").join(".")
            : "";
          return loc ? `${loc}: ${record.msg ?? "校验失败"}` : (record.msg ?? "校验失败");
        }
        return String(item);
      })
      .join("; ");
  }
  if (detail && typeof detail === "object") {
    const record = detail as ApiErrorDetail;
    if (typeof record.message === "string" && record.message) return record.message;
  }
  return typeof detail === "string" && detail ? detail : "";
}

/** 按 status + 是否带业务 code 归类错误种类。 */
export function classify(status: number, hasBusinessCode: boolean): ApiErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 428) return "setup_required";
  if (status === 403) return "forbidden";
  if (status === 409) return "conflict";
  if (status === 429) return "rate_limited";
  if (status === 404) return hasBusinessCode ? "not_found" : "unavailable";
  if (status === 405) return "unavailable";
  if (status === 400 || status === 422) return "validation";
  if (status >= 500) return "server";
  return "unknown";
}

/** 从响应体构造 ApiError。body 为已解析 JSON (或 null)。 */
export function apiErrorFrom(status: number, body: unknown, path: string): ApiError {
  let detail: ApiErrorDetail | string | null = null;
  let code = "";
  let message = "";

  if (body && typeof body === "object") {
    const record = body as { detail?: unknown };
    const raw = record.detail !== undefined ? record.detail : body;
    if (typeof raw === "string") {
      detail = raw;
      message = raw;
    } else if (raw && typeof raw === "object") {
      const structured = raw as ApiErrorDetail;
      detail = structured;
      code = typeof structured.code === "string" ? structured.code : "";
      message = stringifyFastApiValidation(structured) || code;
    } else if (Array.isArray(raw)) {
      message = stringifyFastApiValidation(raw);
      detail = raw as unknown as ApiErrorDetail;
    }
  }

  // FastAPI 未匹配路由返回 {"detail": "Not Found"} (无业务 code) —— 与"资源不存在"
  // (AGENT_NOT_FOUND 等) 区分: 前者是可选子系统未启用 (api.md "条件挂载")。
  const hasBusinessCode = Boolean(code);
  const kind = classify(status, hasBusinessCode);
  if (!message) {
    message = defaultMessageFor(status, kind);
  }

  return new ApiError({
    status,
    kind,
    code: code || httpStatusName(status),
    message,
    detail,
    path,
  });
}

function httpStatusName(status: number): string {
  switch (status) {
    case 400:
      return "BAD_REQUEST";
    case 401:
      return "UNAUTHORIZED";
    case 403:
      return "FORBIDDEN";
    case 404:
      return "NOT_FOUND";
    case 405:
      return "METHOD_NOT_ALLOWED";
    case 409:
      return "CONFLICT";
    case 422:
      return "VALIDATION_ERROR";
    case 428:
      return "SETUP_REQUIRED";
    case 429:
      return "TOO_MANY_REQUESTS";
    default:
      return status >= 500 ? "INTERNAL_ERROR" : `HTTP_${status}`;
  }
}

function defaultMessageFor(status: number, kind: ApiErrorKind): string {
  switch (kind) {
    case "unauthorized":
      return "登录状态已失效, 请重新登录";
    case "setup_required":
      return "控制面处于首登待设置态, 请先设置管理密码";
    case "forbidden":
      return "当前凭据权限不足 (缺少对应 scope)";
    case "conflict":
      return "配置已被他人修改 (revision 冲突)";
    case "unavailable":
      return "该子系统未启用, 端点未挂载";
    case "rate_limited":
      return "请求过于频繁或连接数已达上限, 请稍后重试";
    case "validation":
      return "请求参数或配置校验失败";
    case "server":
      return `服务端错误 (HTTP ${status})`;
    default:
      return `请求失败 (HTTP ${status})`;
  }
}

/** 网络层错误 (fetch reject) 归一。 */
export function networkError(cause: unknown, path: string): ApiError {
  const message = cause instanceof Error ? cause.message : String(cause);
  return new ApiError({
    status: 0,
    kind: "network",
    code: "NETWORK_ERROR",
    message: `无法连接控制面: ${message}`,
    path,
  });
}

/** 类型守卫。 */
export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

/** 从任意 throw 值提取可展示消息。 */
export function errorMessage(value: unknown): string {
  if (isApiError(value)) return value.message;
  if (value instanceof Error) return value.message;
  return String(value);
}

/** 从任意 throw 值提取 ApiErrorKind (非 ApiError 归 unknown)。 */
export function errorKind(value: unknown): ApiErrorKind {
  return isApiError(value) ? value.kind : "unknown";
}
