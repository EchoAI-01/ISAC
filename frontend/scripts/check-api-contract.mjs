// API 契约自检 (CI 常驻): 前端引用的每个 (method, path) 都必须存在于
// docs/api/openapi.json 契约基线里 —— 防止前端调用后端已删除/从未存在的端点
// (v1 内置 WebUI 就有过把 /usage/models/events 的数组当对象读的口径漂移)。
//
// 用法: npm run contract:check   (退出码非 0 = 契约漂移)
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("..", import.meta.url));
const repoRoot = fileURLToPath(new URL("../..", import.meta.url));
const spec = JSON.parse(readFileSync(join(repoRoot, "docs/api/openapi.json"), "utf8"));

/** 契约基线里的 (method, path) 集合。 */
const baseline = new Set();
for (const [path, methods] of Object.entries(spec.paths)) {
  for (const method of Object.keys(methods)) {
    if (["get", "post", "put", "patch", "delete"].includes(method)) {
      baseline.add(`${method.toUpperCase()} ${path}`);
    }
  }
}

/** 递归收集 src 下的 .ts/.tsx (跳过生成文件与测试)。 */
function collectSources(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...collectSources(full));
      continue;
    }
    if (!/\.(ts|tsx)$/.test(full)) continue;
    if (full.endsWith(".d.ts") || full.includes("/test/") || full.endsWith(".test.ts") || full.endsWith(".test.tsx")) continue;
    out.push(full);
  }
  return out;
}

// ① openapi-fetch 的类型化调用: client.GET("/api/v1/xxx", ...)
const clientCallPattern = /client\s*\.\s*(GET|POST|PUT|PATCH|DELETE)\s*\(\s*"([^"]+)"/g;
// ② SSE 路径: connectSse/tailLogs/streamEvents 的 `path: "/api/v1/..."`
//    (只认 /api/ 前缀, 避免误抓 React Router 的 path: "/login" 一类路由声明)
const ssePathPattern = /path\s*:\s*"(\/api\/[^"]+)"/g;
const rawRequestPattern = /rawRequest\s*\(\s*"([A-Z]+)"\s*,\s*"(\/[^"]+)"/g;

const referenced = new Map(); // "METHOD path" -> [file:line]

function record(key, file, line) {
  if (!referenced.has(key)) referenced.set(key, []);
  referenced.get(key).push(`${relative(frontendRoot, file)}:${line}`);
}

function scan(file, pattern, makeKey) {
  const text = readFileSync(file, "utf8");
  const lines = text.split("\n");
  let match;
  pattern.lastIndex = 0;
  while ((match = pattern.exec(text)) !== null) {
    const line = text.slice(0, match.index).split("\n").length;
    record(makeKey(match), file, line);
  }
  // lines 仅用于让 lint 不误报未使用变量; 行号由 match.index 反推。
  void lines;
}

for (const file of collectSources(join(frontendRoot, "src"))) {
  scan(file, clientCallPattern, (m) => `${m[1].toUpperCase()} ${m[2]}`);
  scan(file, rawRequestPattern, (m) => `${m[1]} ${m[2]}`);
  // SSE: 只有 GET 流式端点。
  scan(file, ssePathPattern, (m) => `GET ${m[1]}`);
}

const unknown = [...referenced.keys()].filter((key) => !baseline.has(key)).sort();

console.log(`[contract] 基线路径数: ${Object.keys(spec.paths).length} | 前端引用端点数: ${referenced.size}`);

if (unknown.length > 0) {
  console.error("[contract] FAIL: 前端引用了契约基线中不存在的端点:");
  for (const key of unknown) {
    console.error(`  - ${key}  ← ${referenced.get(key).join(", ")}`);
  }
  console.error(
    "\n处理: 若后端确有该端点, 先按 docs/api.md 的契约变更流程更新 CONTROL_PLANE_SPEC.md,\n" +
      "再跑 `uv run python scripts/export_openapi.py` 刷新基线, 最后在 frontend 跑 `npm run gen:api`。",
  );
  process.exit(1);
}

// 反向提示 (不失败): 基线里前端尚未消费的端点, 帮助发现漏做的域。
const unused = [...baseline].filter((key) => !referenced.has(key)).sort();
if (unused.length > 0) {
  console.log(`[contract] 提示: 基线中前端尚未消费的端点 ${unused.length} 个:`);
  for (const key of unused) console.log(`  · ${key}`);
}

console.log("[contract] OK: 前端引用的端点全部命中契约基线");
