// F1/FE0: 从后端契约基线 docs/api/openapi.json 生成 TypeScript 类型。
//
// 契约是唯一事实源 (AGENTS.md 硬性规则 1 + docs/api.md "API 契约基线"):
// 前端不手写端点签名, 一律由本脚本生成的 `src/api/openapi.d.ts` 驱动,
// 配合 openapi-fetch 在编译期校验 path/method/参数/响应形状。
//
// 用法: npm run gen:api  (后端契约变更后必须重跑, 否则类型与运行时漂移)
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

const specUrl = new URL("../../docs/api/openapi.json", import.meta.url);
const outFile = new URL("../src/api/openapi.d.ts", import.meta.url);

const spec = JSON.parse(readFileSync(specUrl, "utf8"));
const generated = await openapiTS(spec);
const body = typeof generated === "string" ? generated : astToString(generated);

const banner = [
  "/* eslint-disable */",
  "// 本文件由 scripts/gen-api-types.mjs 从 docs/api/openapi.json 自动生成, 请勿手改。",
  `// 契约版本: ${spec?.info?.version ?? "unknown"} | 路径数: ${Object.keys(spec?.paths ?? {}).length}`,
  "// 重新生成: npm run gen:api",
  "",
].join("\n");

writeFileSync(fileURLToPath(outFile), banner + body, "utf8");
console.log(`[gen:api] 已生成 ${fileURLToPath(outFile)} (paths=${Object.keys(spec?.paths ?? {}).length})`);
