/** 插件市场与生命周期端点 (routes_plugins.py, F4)。
 *
 * `control.plugins.allow_install=false` 时后端只挂载读端点 (marketplace/failed),
 * 写端点 404/405 —— 前端据 `ApiError.kind === "unavailable"` 渲染"安装被禁用"
 * 引导, 而不是报错。
 */

import { client, unwrap } from "./client";
import type {
  FailedPluginsResult,
  LoadedPluginsResult,
  MarketplaceResult,
  PluginActionResult,
  PluginInstallSource,
} from "./types";

export function listLoadedPlugins(): Promise<LoadedPluginsResult> {
  return unwrap<LoadedPluginsResult>(client.GET("/api/v1/plugins/loaded"), "/api/v1/plugins/loaded");
}

/** refresh=true 强制重拉远程清单 (否则用进程内缓存)。 */
export function listMarketplace(refresh = false): Promise<MarketplaceResult> {
  return unwrap<MarketplaceResult>(
    client.GET("/api/v1/plugins/marketplace", { params: { query: { refresh } } }),
    "/api/v1/plugins/marketplace",
  );
}

/** 加载失败清单: name → 错误信息 (进程内, 重启清空)。 */
export function listFailedPlugins(): Promise<FailedPluginsResult> {
  return unwrap<FailedPluginsResult>(client.GET("/api/v1/plugins/failed"), "/api/v1/plugins/failed");
}

/** 一键安装 (market / git / url / upload 四种源)。 */
export function installPlugin(source: PluginInstallSource): Promise<PluginActionResult> {
  return unwrap<PluginActionResult>(
    client.POST("/api/v1/plugins/install", { body: { source } }),
    "/api/v1/plugins/install",
  );
}

/** 热重载 (unload + 重新 load_entry + 激活 + 同步运行中 Agent)。 */
export function reloadPlugin(name: string): Promise<PluginActionResult> {
  return unwrap<PluginActionResult>(
    client.POST("/api/v1/plugins/{name}/reload", { params: { path: { name } } }),
    `/api/v1/plugins/${name}/reload`,
  );
}

/** 卸载 (含共享注册表与运行中 Agent 的来源清理)。 */
export function uninstallPlugin(name: string): Promise<PluginActionResult> {
  return unwrap<PluginActionResult>(
    client.DELETE("/api/v1/plugins/{name}", { params: { path: { name } } }),
    `/api/v1/plugins/${name}`,
  );
}

/** 失败插件重试加载。 */
export function retryPlugin(name: string): Promise<PluginActionResult> {
  return unwrap<PluginActionResult>(
    client.POST("/api/v1/plugins/{name}/retry", { params: { path: { name } } }),
    `/api/v1/plugins/${name}/retry`,
  );
}
