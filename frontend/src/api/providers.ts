/** Provider / 模型目录 / 制品端点 (routes_providers.py)。
 *
 * 条件挂载: providers 组需 ProviderManager + ModelCatalog 注入, artifacts 组需
 * ArtifactStore; 未启用时端点不存在 → ApiError.kind === "unavailable"。
 */

import { client, unwrap } from "./client";
import type { ArtifactMeta, ModelDescriptor, ProviderSummary, ProviderTestResult, StatusResult } from "./types";

export function listProviders(): Promise<{ providers: ProviderSummary[] }> {
  return unwrap<{ providers: ProviderSummary[] }>(
    client.GET("/api/v1/providers"),
    "/api/v1/providers",
  );
}

export function listModels(): Promise<{ models: ModelDescriptor[] }> {
  return unwrap<{ models: ModelDescriptor[] }>(
    client.GET("/api/v1/providers/models"),
    "/api/v1/providers/models",
  );
}

/** 最小健康测试 (写审计, 不回显凭据)。 */
export function testProvider(providerId: string, modelId = ""): Promise<ProviderTestResult> {
  return unwrap<ProviderTestResult>(
    client.POST("/api/v1/providers/{provider_id}/test", {
      params: { path: { provider_id: providerId }, query: { model_id: modelId } },
    }),
    `/api/v1/providers/${providerId}/test`,
  );
}

export function listArtifacts(): Promise<{ artifacts: ArtifactMeta[] }> {
  return unwrap<{ artifacts: ArtifactMeta[] }>(
    client.GET("/api/v1/artifacts"),
    "/api/v1/artifacts",
  );
}

export function getArtifact(artifactId: string): Promise<ArtifactMeta> {
  return unwrap<ArtifactMeta>(
    client.GET("/api/v1/artifacts/{artifact_id}", { params: { path: { artifact_id: artifactId } } }),
    `/api/v1/artifacts/${artifactId}`,
  );
}

/** 提前删除制品 (不可逆, UI 必须二次确认)。 */
export function deleteArtifact(artifactId: string): Promise<StatusResult> {
  return unwrap<StatusResult>(
    client.DELETE("/api/v1/artifacts/{artifact_id}", {
      params: { path: { artifact_id: artifactId } },
    }),
    `/api/v1/artifacts/${artifactId}`,
  );
}
