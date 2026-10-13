/** 记忆检索与治理端点 (routes_memory.py + routes_memory_admin.py)。
 *
 * - 读端点在 tokens[] 模式下按 `memory:read` 收窄, 治理写按 `memory:write`;
 * - `episodes` 已过滤软删 (deleted=0); 治理视图 `items` **包含**软删条目
 *   (export 口径), 用于"恢复"操作;
 * - 治理返回 `{ok, detail}`: ok=false 表示条目不存在或受保护拒绝, **不是 HTTP 错误**,
 *   UI 必须把 detail 原样呈现, 不能只按 ok 显示"成功"。
 */

import { client, unwrap } from "./client";
import type {
  GovernanceResult,
  MemoryEpisode,
  MemoryItemsResult,
  MemoryJargon,
  MemoryProfile,
} from "./types";

export function listEpisodes(
  agentId: string,
  limit = 100,
): Promise<{ episodes: MemoryEpisode[] }> {
  return unwrap<{ episodes: MemoryEpisode[] }>(
    client.GET("/api/v1/memory/{agent_id}/episodes", {
      params: { path: { agent_id: agentId }, query: { limit } },
    }),
    `/api/v1/memory/${agentId}/episodes`,
  );
}

export function listProfiles(agentId: string): Promise<{ profiles: MemoryProfile[] }> {
  return unwrap<{ profiles: MemoryProfile[] }>(
    client.GET("/api/v1/memory/{agent_id}/profiles", { params: { path: { agent_id: agentId } } }),
    `/api/v1/memory/${agentId}/profiles`,
  );
}

export function listJargon(agentId: string): Promise<{ jargon: MemoryJargon[] }> {
  return unwrap<{ jargon: MemoryJargon[] }>(
    client.GET("/api/v1/memory/{agent_id}/jargon", { params: { path: { agent_id: agentId } } }),
    `/api/v1/memory/${agentId}/jargon`,
  );
}

/** 治理视图 (含软删条目), 分页。 */
export function listMemoryItems(
  agentId: string,
  opts: { limit?: number; offset?: number } = {},
): Promise<MemoryItemsResult> {
  return unwrap<MemoryItemsResult>(
    client.GET("/api/v1/memory/{agent_id}/items", {
      params: { path: { agent_id: agentId }, query: { limit: opts.limit ?? 500, offset: opts.offset ?? 0 } },
    }),
    `/api/v1/memory/${agentId}/items`,
  );
}

function itemPath(agentId: string, itemId: string): string {
  return `/api/v1/memory/${agentId}/items/${itemId}`;
}

/** 冻结 (不参与剪枝/压缩)。 */
export function freezeMemoryItem(agentId: string, itemId: string): Promise<GovernanceResult> {
  return unwrap<GovernanceResult>(
    client.POST("/api/v1/memory/{agent_id}/items/{item_id}/freeze", {
      params: { path: { agent_id: agentId, item_id: itemId } },
    }),
    `${itemPath(agentId, itemId)}/freeze`,
  );
}

/** 保护 (拒绝删除)。 */
export function protectMemoryItem(agentId: string, itemId: string): Promise<GovernanceResult> {
  return unwrap<GovernanceResult>(
    client.POST("/api/v1/memory/{agent_id}/items/{item_id}/protect", {
      params: { path: { agent_id: agentId, item_id: itemId } },
    }),
    `${itemPath(agentId, itemId)}/protect`,
  );
}

/** 纠正内容 (保留 revision 历史)。 */
export function correctMemoryItem(
  agentId: string,
  itemId: string,
  newContent: string,
): Promise<GovernanceResult> {
  return unwrap<GovernanceResult>(
    client.PATCH("/api/v1/memory/{agent_id}/items/{item_id}", {
      params: { path: { agent_id: agentId, item_id: itemId } },
      body: { new_content: newContent },
    }),
    itemPath(agentId, itemId),
  );
}

/** 软删除 (受保护条目会被拒绝, detail 说明原因)。 */
export function deleteMemoryItem(agentId: string, itemId: string): Promise<GovernanceResult> {
  return unwrap<GovernanceResult>(
    client.DELETE("/api/v1/memory/{agent_id}/items/{item_id}", {
      params: { path: { agent_id: agentId, item_id: itemId } },
    }),
    itemPath(agentId, itemId),
  );
}

export function restoreMemoryItem(agentId: string, itemId: string): Promise<GovernanceResult> {
  return unwrap<GovernanceResult>(
    client.POST("/api/v1/memory/{agent_id}/items/{item_id}/restore", {
      params: { path: { agent_id: agentId, item_id: itemId } },
    }),
    `${itemPath(agentId, itemId)}/restore`,
  );
}
