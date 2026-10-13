/** 会话端点 (routes_sessions.py)。
 *
 * `/sessions*` 三个端点在 tokens[] 模式下按 `memory:read` 收窄 (会话内容属记忆读
 * 权限范畴); 无 metadata_store 时 `/messages` 返回空列表而非 404。
 */

import { client, unwrap } from "./client";
import type { SessionDto, SessionListResult, SessionMessagesResult } from "./types";

export function listSessions(agentId?: string): Promise<SessionListResult> {
  return unwrap<SessionListResult>(
    client.GET("/api/v1/sessions", { params: { query: { agent_id: agentId } } }),
    "/api/v1/sessions",
  );
}

export function getSession(sessionId: string): Promise<SessionDto> {
  return unwrap<SessionDto>(
    client.GET("/api/v1/sessions/{session_id}", { params: { path: { session_id: sessionId } } }),
    `/api/v1/sessions/${sessionId}`,
  );
}

export function getSessionMessages(sessionId: string, limit = 100): Promise<SessionMessagesResult> {
  return unwrap<SessionMessagesResult>(
    client.GET("/api/v1/sessions/{session_id}/messages", {
      params: { path: { session_id: sessionId }, query: { limit } },
    }),
    `/api/v1/sessions/${sessionId}/messages`,
  );
}
